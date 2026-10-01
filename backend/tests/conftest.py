from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_sample_path, get_storage_root
from app.api.sample import SAMPLE_PATH, build_sample_cache, get_sample_cache_dir
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
SMALL_SAMPLE = FIXTURES / "amazon_300.csv.gz"


@pytest.fixture(autouse=True)
def no_real_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only tests marked live may reach Groq; the rest never use a real key or the network."""
    if "live" not in request.keywords:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture(scope="session")
def sample_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A sample cache prepared once, as the image build does, from the 300-row fixture."""
    cache = tmp_path_factory.mktemp("sample_cache")
    build_sample_cache(SMALL_SAMPLE, cache)
    return cache


@pytest.fixture(scope="session")
def real_sample_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The full 128,975-row sample, prepared once from the committed .csv.gz (works in CI)."""
    cache = tmp_path_factory.mktemp("real_sample_cache")
    build_sample_cache(SAMPLE_PATH, cache)
    return cache


@pytest.fixture
def client(tmp_path: Path, storage_root: Path, sample_cache: Path) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: SMALL_SAMPLE
    app.dependency_overrides[get_sample_cache_dir] = lambda: sample_cache
    return TestClient(app)
