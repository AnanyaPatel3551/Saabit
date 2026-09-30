import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import SAMPLE_PATH, SAMPLE_ROLES, get_sample_path, get_storage_root
from app.core.ingest import read_bundled_file
from app.main import create_app
from tests.conftest import FIXTURES

ORIGINAL_CSV = SAMPLE_PATH.with_suffix("")


def make_client(tmp_path: Path, storage_root: Path, sample: Path) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: sample
    return TestClient(app)


def test_bundled_sample_is_a_gzipped_csv() -> None:
    assert SAMPLE_PATH.name == "amazon_sale_report.csv.gz"
    assert SAMPLE_PATH.is_file()


def test_sample_loads_from_csv_gz_with_128975_rows(tmp_path: Path, storage_root: Path) -> None:
    client = make_client(tmp_path, storage_root, SAMPLE_PATH)

    body = client.post("/api/datasets/sample").json()

    assert body["rows"] == 128975
    assert body["roles_confirmed"] is True
    assert {r["role"]: r["column"] for r in body["roles"]} == SAMPLE_ROLES


def test_bundled_sample_reads_128975_rows() -> None:
    assert len(read_bundled_file(SAMPLE_PATH)) == 128975


@pytest.mark.skipif(not ORIGINAL_CSV.is_file(), reason="original CSV is not in the repo")
def test_gz_decompresses_to_the_original_csv_byte_for_byte() -> None:
    assert gzip.decompress(SAMPLE_PATH.read_bytes()) == ORIGINAL_CSV.read_bytes()


def test_two_sample_requests_do_not_create_two_copies(
    client: TestClient, storage_root: Path
) -> None:
    first = client.post("/api/datasets/sample").json()
    second = client.post("/api/datasets/sample").json()

    assert first["dataset_id"] == second["dataset_id"]
    assert first == second
    assert len(list(storage_root.iterdir())) == 1


def test_sample_folder_holds_metadata_only(client: TestClient, storage_root: Path) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]

    assert [p.name for p in (storage_root / dataset_id).iterdir()] == ["metadata.json"]


def test_sample_is_reused_after_a_restart(tmp_path: Path, storage_root: Path) -> None:
    sample = FIXTURES / "amazon_300.csv.gz"
    before = make_client(tmp_path, storage_root, sample).post("/api/datasets/sample").json()

    after = make_client(tmp_path, storage_root, sample).post("/api/datasets/sample").json()

    assert after == before


def test_sample_is_preloaded_at_startup(tmp_path: Path, storage_root: Path) -> None:
    client = make_client(tmp_path, storage_root, FIXTURES / "amazon_300.csv.gz")

    with client:
        folders = list(storage_root.iterdir())

    assert len(folders) == 1
    assert (folders[0] / "metadata.json").is_file()


def test_missing_sample_does_not_stop_startup(tmp_path: Path, storage_root: Path) -> None:
    client = make_client(tmp_path, storage_root, tmp_path / "missing.csv.gz")

    with client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/datasets/sample").status_code == 503


def test_sample_can_be_fetched_by_its_id(client: TestClient) -> None:
    created = client.post("/api/datasets/sample").json()

    assert client.get(f"/api/datasets/{created['dataset_id']}").json() == created
