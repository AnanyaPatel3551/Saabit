from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_sample_path, get_storage_root
from app.api.sample import get_sample_cache_dir
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def sample_cache(tmp_path: Path) -> Path:
    return tmp_path / "sample_cache"


@pytest.fixture
def client(tmp_path: Path, storage_root: Path, sample_cache: Path) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: FIXTURES / "amazon_300.csv.gz"
    app.dependency_overrides[get_sample_cache_dir] = lambda: sample_cache
    return TestClient(app)
