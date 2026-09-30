import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import sample as sample_module
from app.api.datasets import get_storage_root
from app.api.sample import (
    SAMPLE_PATH,
    SAMPLE_ROLES,
    build_sample_cache,
    get_sample_cache_dir,
    get_sample_path,
)
from app.core import ingest
from app.main import create_app
from tests.conftest import FIXTURES

ORIGINAL_CSV = SAMPLE_PATH.with_suffix("")
SMALL_SAMPLE = FIXTURES / "amazon_300.csv.gz"


def make_client(tmp_path: Path, sample: Path, cache: Path) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: tmp_path / "storage"
    app.dependency_overrides[get_sample_path] = lambda: sample
    app.dependency_overrides[get_sample_cache_dir] = lambda: cache
    return TestClient(app)


def forbid_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the sample file was parsed")

    monkeypatch.setattr(ingest, "read_bundled_file", fail)
    monkeypatch.setattr(sample_module.ingest, "read_bundled_file", fail)


def test_bundled_sample_is_a_gzipped_csv() -> None:
    assert SAMPLE_PATH.name == "amazon_sale_report.csv.gz"
    assert SAMPLE_PATH.is_file()


def test_sample_loads_from_csv_gz_with_128975_rows(tmp_path: Path) -> None:
    client = make_client(tmp_path, SAMPLE_PATH, tmp_path / "cache")

    body = client.post("/api/datasets/sample").json()

    assert body["rows"] == 128975
    assert body["roles_confirmed"] is True
    assert {r["role"]: r["column"] for r in body["roles"]} == SAMPLE_ROLES
    assert len(body["columns"]) == 24


def test_sample_row_count_comes_from_duckdb_over_the_whole_gzip_file(tmp_path: Path) -> None:
    table = ingest.read_bundled_file(SAMPLE_PATH, tmp_path, columns=["Order ID"])

    assert table.rows == 128975
    assert len(table.head) == ingest.HEAD_ROWS
    assert list(table.head.columns) == ["Order ID"]


@pytest.mark.skipif(not ORIGINAL_CSV.is_file(), reason="original CSV is not in the repo")
def test_gz_decompresses_to_the_original_csv_byte_for_byte() -> None:
    assert gzip.decompress(SAMPLE_PATH.read_bytes()) == ORIGINAL_CSV.read_bytes()


def test_prepare_writes_the_cache(tmp_path: Path) -> None:
    dataset = build_sample_cache(SMALL_SAMPLE, tmp_path / "cache")

    assert (tmp_path / "cache" / "metadata.json").is_file()
    assert dataset.rows == 300
    assert dataset.roles_confirmed is True


def test_prepared_sample_is_served_without_parsing_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = build_sample_cache(SMALL_SAMPLE, tmp_path / "cache")
    forbid_parsing(monkeypatch)
    client = make_client(tmp_path, SMALL_SAMPLE, tmp_path / "cache")

    body = client.post("/api/datasets/sample").json()

    assert body["dataset_id"] == prepared.dataset_id
    assert body["rows"] == 300


def test_startup_does_no_data_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_parsing(monkeypatch)
    client = make_client(tmp_path, SMALL_SAMPLE, tmp_path / "empty-cache")

    with client:
        assert client.get("/api/health").status_code == 200

    assert not (tmp_path / "empty-cache").exists()


def test_two_sample_requests_do_not_create_two_copies(
    client: TestClient, storage_root: Path, sample_cache: Path
) -> None:
    first = client.post("/api/datasets/sample").json()
    second = client.post("/api/datasets/sample").json()

    assert first == second
    assert not storage_root.exists() or not any(storage_root.iterdir())
    assert [p.name for p in sample_cache.iterdir()] == ["metadata.json"]


def test_sample_is_reused_after_a_restart(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    before = make_client(tmp_path, SMALL_SAMPLE, cache).post("/api/datasets/sample").json()

    after = make_client(tmp_path, SMALL_SAMPLE, cache).post("/api/datasets/sample").json()

    assert after == before


def test_missing_sample_and_cache_return_503_without_stopping_startup(tmp_path: Path) -> None:
    client = make_client(tmp_path, tmp_path / "missing.csv.gz", tmp_path / "cache")

    with client:
        assert client.get("/api/health").status_code == 200
        response = client.post("/api/datasets/sample")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sample_unavailable"


def test_sample_can_be_fetched_by_its_id(client: TestClient) -> None:
    created = client.post("/api/datasets/sample").json()

    assert client.get(f"/api/datasets/{created['dataset_id']}").json() == created
