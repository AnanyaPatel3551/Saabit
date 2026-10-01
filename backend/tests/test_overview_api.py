from pathlib import Path

from fastapi.testclient import TestClient

from app.core.overview import mark_computing
from tests.conftest import FIXTURES


def upload(client: TestClient) -> dict:
    content = (FIXTURES / "amazon_300.csv").read_bytes()
    return client.post("/api/datasets", files={"file": ("a.csv", content)}).json()


def confirm(client: TestClient, created: dict) -> None:
    roles = {r["role"]: r["column"] for r in created["roles"]}
    client.post(f"/api/datasets/{created['dataset_id']}/confirm", json={"roles": roles})


def test_sample_overview_comes_from_the_cache(client: TestClient) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]

    body = client.get(f"/api/datasets/{dataset_id}/overview").json()

    assert body["status"] == "ready"
    assert [i["code"] for i in body["insights"]] == ["E1", "E2", "E3", "E4", "E5"]
    assert body["data_check"]["rows_out"] == 300
    # the 300-line fixture covers one day, so no rule can be backtested
    assert body["recommendations"] == []
    assert all("two full months" in r["reason"] for r in body["rules"])


def test_overview_is_computed_in_the_background_after_confirm(
    client: TestClient, storage_root: Path
) -> None:
    created = upload(client)
    confirm(client, created)

    body = client.get(f"/api/datasets/{created['dataset_id']}/overview").json()

    assert body["status"] == "ready"
    assert body["insights"][0]["status"] == "ok"
    assert (storage_root / created["dataset_id"] / "overview.json").is_file()


def test_overview_says_computing_until_ready(client: TestClient, storage_root: Path) -> None:
    created = upload(client)
    confirm(client, created)
    mark_computing(storage_root / created["dataset_id"] / "overview.json")

    body = client.get(f"/api/datasets/{created['dataset_id']}/overview").json()

    assert body["status"] == "computing"
    assert body["insights"] == []


def test_overview_before_confirm_returns_409(client: TestClient) -> None:
    created = upload(client)

    response = client.get(f"/api/datasets/{created['dataset_id']}/overview")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_cleaned"


def test_insight_card_rows_can_be_opened(client: TestClient) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]
    card_id = client.get(f"/api/datasets/{dataset_id}/overview").json()["insights"][0][
        "card_ids"][0]

    response = client.get(f"/api/cards/{card_id}/rows")

    assert response.status_code == 200
    assert response.json()["total_rows"] == 300


def test_an_insight_card_can_be_fetched_by_id(client: TestClient) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]
    card_id = client.get(f"/api/datasets/{dataset_id}/overview").json()["insights"][0][
        "card_ids"][0]

    card = client.get(f"/api/cards/{card_id}").json()

    assert card["card_id"] == card_id
    assert card["verified"] is True
    assert card["sql"].startswith("SELECT")
    assert card["plan"]["metric"] == "cancellation_rate"


def test_unknown_card_id_returns_404(client: TestClient) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]

    response = client.get(f"/api/cards/{dataset_id}-00000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"
