"""Per-upload access keys: an upload is readable only with the key returned at upload time.

Without the key, every dataset and card endpoint answers 404, exactly like an unknown id.
The shared sample stays public. Only the key's hash is stored, and the key never appears
in a later response or in the logs.
"""

import hashlib
import json
import logging
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_sample_path, get_storage_root
from app.api.sample import SHOPIFY_PATH, build_shopify_cache, get_sample_cache_dir
from app.main import create_app
from tests.conftest import FIXTURES, SMALL_SAMPLE

KEY = "X-Dataset-Key"


def upload_and_answer(client: TestClient) -> tuple[str, str, str]:
    """Upload, confirm and answer one question with the key; return (dataset id, key, card id)."""
    files = {"file": ("orders.csv", (FIXTURES / "amazon_300.csv").read_bytes(), "text/csv")}
    created = client.post("/api/datasets", files=files).json()
    dataset_id, key = created["dataset_id"], created["access_key"]
    roles = {r["role"]: r["column"] for r in created["roles"]}
    headers = {KEY: key}
    assert client.post(f"/api/datasets/{dataset_id}/confirm", json={"roles": roles},
                       headers=headers).status_code == 200
    run = client.post(f"/api/datasets/{dataset_id}/run", json={"metric": "orders"},
                      headers=headers)
    assert run.status_code == 200
    return dataset_id, key, run.json()["card"]["card_id"]


def every_request(dataset_id: str, card_id: str) -> list[tuple[str, str, dict]]:
    """(method, path, request options) for every endpoint about one dataset or its cards."""
    return [
        ("GET", f"/api/datasets/{dataset_id}", {}),
        ("POST", f"/api/datasets/{dataset_id}/confirm", {"json": {"roles": {}}}),
        ("GET", f"/api/datasets/{dataset_id}/overview", {}),
        ("POST", f"/api/datasets/{dataset_id}/plan", {"json": {"question": "orders"}}),
        ("POST", f"/api/datasets/{dataset_id}/run", {"json": {"metric": "orders"}}),
        ("GET", f"/api/datasets/{dataset_id}/fixes", {}),
        ("GET", f"/api/cards/{card_id}", {}),
        ("POST", f"/api/cards/{card_id}/sentence", {"json": {"question": "orders"}}),
        ("GET", f"/api/cards/{card_id}/rows", {}),
        ("GET", f"/api/cards/{card_id}/rows?format=csv", {}),
        ("DELETE", f"/api/datasets/{dataset_id}", {}),
    ]


@pytest.mark.parametrize("headers", [{}, {KEY: "not-the-key"}, {KEY: ""}],
                         ids=["no key", "wrong key", "empty key"])
def test_without_the_right_key_every_dataset_and_card_endpoint_returns_404(
        client: TestClient, headers: dict) -> None:
    dataset_id, _, card_id = upload_and_answer(client)

    for method, path, options in every_request(dataset_id, card_id):
        response = client.request(method, path, headers=headers, **options)
        assert response.status_code == 404, (method, path, response.text)


def test_a_wrong_key_looks_exactly_like_an_unknown_dataset(client: TestClient) -> None:
    dataset_id, _, _ = upload_and_answer(client)
    unknown = "0123456789ab"

    wrong = client.get(f"/api/datasets/{dataset_id}", headers={KEY: "guess"}).json()
    missing = client.get(f"/api/datasets/{unknown}", headers={KEY: "guess"}).json()

    assert wrong["error"]["code"] == missing["error"]["code"] == "dataset_not_found"
    assert wrong["error"]["message"].replace(dataset_id, unknown) == missing["error"]["message"]


def test_with_the_key_every_dataset_and_card_endpoint_works(client: TestClient) -> None:
    dataset_id, key, card_id = upload_and_answer(client)
    created = client.get(f"/api/datasets/{dataset_id}", headers={KEY: key}).json()
    roles = {r["role"]: r["column"] for r in created["roles"]}
    requests = every_request(dataset_id, card_id)
    requests[1] = ("POST", f"/api/datasets/{dataset_id}/confirm", {"json": {"roles": roles}})

    for method, path, options in requests:
        response = client.request(method, path, headers={KEY: key}, **options)
        # /plan needs an LLM, and tests never reach one: 503 means the key was accepted
        expected = 503 if path.endswith("/plan") else 200
        assert response.status_code == expected, (method, path, response.text)


def test_card_rows_and_the_csv_download_need_the_key(client: TestClient) -> None:
    _, key, card_id = upload_and_answer(client)

    assert client.get(f"/api/cards/{card_id}/rows").status_code == 404
    assert client.get(f"/api/cards/{card_id}/rows?format=csv").status_code == 404
    csv = client.get(f"/api/cards/{card_id}/rows?format=csv", headers={KEY: key})
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")


def test_the_shared_sample_works_without_a_key(client: TestClient) -> None:
    sample_id = client.post("/api/datasets/sample").json()["dataset_id"]

    assert "access_key" not in client.post("/api/datasets/sample").json()
    assert client.get(f"/api/datasets/{sample_id}").status_code == 200
    assert client.get(f"/api/datasets/{sample_id}/overview").status_code == 200
    assert client.get(f"/api/datasets/{sample_id}/fixes").status_code == 200
    run = client.post(f"/api/datasets/{sample_id}/run", json={"metric": "orders"})
    assert run.status_code == 200
    card_id = run.json()["card"]["card_id"]
    assert client.get(f"/api/cards/{card_id}").status_code == 200
    assert client.get(f"/api/cards/{card_id}/rows?format=csv").status_code == 200


def test_the_sample_still_cannot_be_deleted(client: TestClient) -> None:
    sample_id = client.post("/api/datasets/sample").json()["dataset_id"]

    assert client.delete(f"/api/datasets/{sample_id}").status_code == 403


def test_the_shopify_copy_gets_its_own_key_and_needs_it(
        tmp_path: Path, storage_root: Path, sample_cache: Path) -> None:
    cache = tmp_path / "cache"
    shutil.copytree(sample_cache, cache)
    build_shopify_cache(SHOPIFY_PATH, cache)
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: SMALL_SAMPLE
    app.dependency_overrides[get_sample_cache_dir] = lambda: cache
    client = TestClient(app)

    copy = client.post("/api/datasets/sample/shopify").json()

    assert copy["access_key"]
    assert client.get(f"/api/datasets/{copy['dataset_id']}").status_code == 404
    assert client.get(f"/api/datasets/{copy['dataset_id']}",
                      headers={KEY: copy["access_key"]}).status_code == 200


def test_only_the_keys_hash_is_stored_and_it_survives_confirm(
        client: TestClient, storage_root: Path) -> None:
    dataset_id, key, _ = upload_and_answer(client)

    stored = (storage_root / dataset_id / "metadata.json").read_text(encoding="utf-8")

    assert key not in stored
    assert json.loads(stored)["key_sha256"] == hashlib.sha256(key.encode()).hexdigest()
    for path in (storage_root / dataset_id).rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes(), path


def test_the_key_never_appears_in_later_responses_or_in_the_logs(
        client: TestClient, caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str]) -> None:
    caplog.set_level(logging.DEBUG)
    dataset_id, key, card_id = upload_and_answer(client)
    created = client.get(f"/api/datasets/{dataset_id}", headers={KEY: key}).json()
    roles = {r["role"]: r["column"] for r in created["roles"]}
    requests = every_request(dataset_id, card_id)
    requests[1] = ("POST", f"/api/datasets/{dataset_id}/confirm", {"json": {"roles": roles}})

    bodies = [client.request(method, path, headers={KEY: key}, **options)
              for method, path, options in requests]

    for response in bodies:
        assert key not in response.text
        assert key not in json.dumps(dict(response.headers))
    captured = capsys.readouterr()
    assert key not in caplog.text
    assert key not in captured.out + captured.err
    assert dataset_id in caplog.text  # the request log did run
