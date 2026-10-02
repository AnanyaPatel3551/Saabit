"""Small read-only additions for the UI: the synthetic Shopify sample, the eval summary and
the /how-we-test page route. The answer pipeline itself is unchanged."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_sample_path, get_storage_root
from app.api.sample import SHOPIFY_PATH, build_shopify_cache, get_sample_cache_dir
from app.main import create_app
from tests.conftest import FIXTURES, SMALL_SAMPLE


@pytest.fixture
def shopify_client(tmp_path: Path, storage_root: Path, sample_cache: Path) -> TestClient:
    cache = tmp_path / "cache"
    shutil.copytree(sample_cache, cache)
    build_shopify_cache(SHOPIFY_PATH, cache)
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: SMALL_SAMPLE
    app.dependency_overrides[get_sample_cache_dir] = lambda: cache
    return TestClient(app)


def test_shopify_sample_goes_through_confirm(shopify_client: TestClient) -> None:
    dataset = shopify_client.post("/api/datasets/sample/shopify").json()

    roles = {r["role"]: r["column"] for r in dataset["roles"]}
    assert dataset["roles_confirmed"] is False
    assert "synthetic" in dataset["filename"]
    assert roles["order_id"] == "Order Number" and roles["order_date"] == "Created at"
    assert roles["amount"] == "Total" and roles["state"] == "Shipping Province"
    assert roles["status"] == "Financial Status"

    check = shopify_client.post(f"/api/datasets/{dataset['dataset_id']}/confirm",
                                json={"roles": roles}).json()
    assert check["rows_out"] == dataset["rows"]
    orders = shopify_client.post(f"/api/datasets/{dataset['dataset_id']}/run",
                                 json={"metric": "orders", "group_by": ["month"]}).json()
    months = [row["month"] for row in orders["card"]["result"]]
    assert months == ["2024-01", "2024-02", "2024-03"]  # DD/MM/YYYY read day-first
    assert orders["verified"] is True


def test_each_visitor_gets_their_own_copy_of_the_shopify_sample(
    shopify_client: TestClient,
) -> None:
    first = shopify_client.post("/api/datasets/sample/shopify").json()["dataset_id"]
    second = shopify_client.post("/api/datasets/sample/shopify").json()["dataset_id"]

    assert first != second


def write(folder: Path, name: str, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


def test_eval_summary_reports_pending_when_files_are_missing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAABIT_EVAL_DIR", str(tmp_path / "no-eval"))

    assert client.get("/api/eval-summary").json() == {"eval": None, "baseline": None,
                                                      "tests": None}


def test_eval_summary_reads_the_latest_results(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = tmp_path / "eval" / "results"
    card = {"answerable": 40, "answerable_correct": 38, "unanswerable": 10,
            "refused_correctly": 10, "verified_but_wrong": 0}
    anchors = {"answerable": 13, "answerable_correct": 13, "unanswerable": 2,
               "refused_correctly": 2, "verified_but_wrong": 0}
    write(results, "latest.json", {"meta": {"finished_at": "2026-10-02 01:07",
                                            "served_by": {"nim nemotron": 65},
                                            "plans_from_cache": 0, "stopped": None},
                                   "scorecards": {"questions": card, "anchors": anchors}})
    write(results, "tests.json", {"passed": 378, "skipped": 2, "date": "2026-10-02"})
    monkeypatch.setenv("SAABIT_EVAL_DIR", str(tmp_path / "eval"))

    body = client.get("/api/eval-summary").json()

    assert body["eval"]["answerable"] == {"correct": 38, "total": 40}
    assert body["eval"]["anchors_answerable"] == {"correct": 13, "total": 13}
    assert body["eval"]["served_by"] == ["nim nemotron"]
    assert body["tests"]["passed"] == 378
    assert body["baseline"] is None


def test_a_stopped_eval_run_is_not_shown_as_a_result(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "eval" / "results", "latest.json",
          {"meta": {"stopped": "rate limited", "finished_at": "x"}, "scorecards": {}})
    monkeypatch.setenv("SAABIT_EVAL_DIR", str(tmp_path / "eval"))

    assert client.get("/api/eval-summary").json()["eval"] is None


def test_how_we_test_route_serves_the_app(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=root>app</div>", encoding="utf-8")

    response = TestClient(create_app(frontend_dist=dist)).get("/how-we-test")

    assert response.status_code == 200 and "app" in response.text


def test_deleting_an_upload_removes_its_folder_and_cards(client: TestClient,
                                                          storage_root: Path) -> None:
    files = {"file": ("orders.csv", (FIXTURES / "amazon_300.csv").read_bytes(), "text/csv")}
    dataset = client.post("/api/datasets", files=files).json()
    roles = {r["role"]: r["column"] for r in dataset["roles"]}
    client.post(f"/api/datasets/{dataset['dataset_id']}/confirm", json={"roles": roles})
    client.post(f"/api/datasets/{dataset['dataset_id']}/run", json={"metric": "orders"})
    folder = storage_root / dataset["dataset_id"]
    assert list((folder / "cards").glob("*.json"))

    response = client.delete(f"/api/datasets/{dataset['dataset_id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": dataset["dataset_id"]}
    assert not folder.exists()
    assert client.get(f"/api/datasets/{dataset['dataset_id']}").status_code == 404


def test_the_shared_sample_cannot_be_deleted(client: TestClient) -> None:
    sample = client.post("/api/datasets/sample").json()["dataset_id"]

    response = client.delete(f"/api/datasets/{sample}")

    assert response.status_code == 403
    assert "shared sample" in response.json()["error"]["message"]
    assert client.post("/api/datasets/sample").status_code == 200


def test_deleting_an_unknown_dataset_is_404(client: TestClient) -> None:
    assert client.delete("/api/datasets/0123456789ab").status_code == 404


def test_privacy_route_serves_the_app(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=root>app</div>", encoding="utf-8")

    assert TestClient(create_app(frontend_dist=dist)).get("/privacy").status_code == 200
