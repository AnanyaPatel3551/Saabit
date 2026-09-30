import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.datasets import SAMPLE_ROLES, get_sample_path
from app.core.ingest import MAX_BYTES
from tests.conftest import FIXTURES

ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


def upload(client: TestClient, name: str, data: bytes | None = None, filename: str | None = None):
    content = data if data is not None else (FIXTURES / name).read_bytes()
    return client.post("/api/datasets", files={"file": (filename or name, content)})


def test_upload_returns_dataset_id_and_suggestions(client: TestClient) -> None:
    response = upload(client, "amazon_300.csv")

    assert response.status_code == 200
    body = response.json()
    assert ID_PATTERN.match(body["dataset_id"])
    assert body["rows"] == 300
    assert body["roles_confirmed"] is False
    assert {r["role"]: r["column"] for r in body["roles"]} == SAMPLE_ROLES
    assert all({"confidence", "reasons", "samples"} <= r.keys() for r in body["roles"])


def test_raw_file_is_stored_unchanged(client: TestClient, storage_root: Path) -> None:
    original = (FIXTURES / "latin1.csv").read_bytes()

    dataset_id = upload(client, "latin1.csv").json()["dataset_id"]

    assert (storage_root / dataset_id / "raw.csv").read_bytes() == original


def test_xlsx_is_stored_unchanged(client: TestClient, storage_root: Path) -> None:
    original = (FIXTURES / "orders.xlsx").read_bytes()

    dataset_id = upload(client, "orders.xlsx").json()["dataset_id"]

    assert (storage_root / dataset_id / "raw.xlsx").read_bytes() == original


def test_metadata_json_is_written(client: TestClient, storage_root: Path) -> None:
    body = upload(client, "semicolon.csv").json()

    metadata = json.loads((storage_root / body["dataset_id"] / "metadata.json").read_text("utf-8"))

    assert metadata["dataset_id"] == body["dataset_id"]
    assert metadata["filename"] == "semicolon.csv"
    assert metadata["size_bytes"] == len((FIXTURES / "semicolon.csv").read_bytes())
    assert metadata["rows"] == 20
    assert metadata["created_at"]


def test_uploaded_filename_is_never_used_as_a_path(client: TestClient, storage_root: Path) -> None:
    response = upload(client, "semicolon.csv", filename="../../escape.csv")

    dataset_id = response.json()["dataset_id"]
    stored = sorted(p.name for p in (storage_root / dataset_id).iterdir())
    assert stored == ["metadata.json", "raw.csv"]
    assert not (storage_root.parent / "escape.csv").exists()
    assert response.json()["filename"] == "../../escape.csv"


def test_get_dataset_returns_metadata_and_roles(client: TestClient) -> None:
    created = upload(client, "shopify_orders.csv").json()

    response = client.get(f"/api/datasets/{created['dataset_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_unknown_dataset_returns_404(client: TestClient) -> None:
    response = client.get("/api/datasets/0123456789ab")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_malformed_dataset_id_returns_404(client: TestClient) -> None:
    response = client.get("/api/datasets/..%2F..%2Fetc")

    assert response.status_code == 404


def test_oversized_upload_returns_400_with_readable_message(client: TestClient) -> None:
    response = upload(client, "big.csv", data=b"x" * (MAX_BYTES + 1))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "file_too_large"
    assert "25 MB" in error["message"]


def test_oversized_message_does_not_claim_a_wrong_size(client: TestClient) -> None:
    response = upload(client, "huge.csv", data=b"x" * (MAX_BYTES * 2))

    message = response.json()["error"]["message"]
    assert "25.0 MB" not in message
    assert "over 25 MB" in message


def test_unsupported_extension_returns_400(client: TestClient) -> None:
    response = upload(client, "orders.json", data=b'{"a": 1}')

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_empty_upload_returns_400(client: TestClient) -> None:
    response = upload(client, "empty.csv")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_rejected_upload_stores_nothing(client: TestClient, storage_root: Path) -> None:
    upload(client, "empty.csv")

    assert not storage_root.exists() or not any(storage_root.iterdir())


def test_upload_without_file_returns_typed_error(client: TestClient) -> None:
    response = client.post("/api/datasets")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_sample_loads_with_roles_confirmed(client: TestClient, storage_root: Path) -> None:
    response = client.post("/api/datasets/sample")

    assert response.status_code == 200
    body = response.json()
    assert body["roles_confirmed"] is True
    assert {r["role"]: r["column"] for r in body["roles"]} == SAMPLE_ROLES
    assert all(r["confidence"] == 1.0 for r in body["roles"])
    assert body["missing_required"] == []
    raw = storage_root / body["dataset_id"] / "raw.csv"
    assert raw.read_bytes() == (FIXTURES / "amazon_300.csv").read_bytes()


def test_sample_unavailable_returns_503(client: TestClient, tmp_path: Path) -> None:
    client.app.dependency_overrides[get_sample_path] = lambda: tmp_path / "missing.csv"

    response = client.post("/api/datasets/sample")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sample_unavailable"
