from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dist=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_root_shows_placeholder_when_frontend_is_not_built(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dist=tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert "frontend has not been built" in response.text
