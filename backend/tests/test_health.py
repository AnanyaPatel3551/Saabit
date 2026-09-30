from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import config
from app.main import create_app


@pytest.fixture(autouse=True)
def fresh_llm_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_last", None)


def test_health_returns_ok(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dist=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["version"]) == ("ok", "0.1.0")
    assert body["llm"]["provider"] == "groq"


def test_health_says_llm_not_configured_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    llm = TestClient(create_app(frontend_dist=tmp_path)).get("/api/health").json()["llm"]

    assert llm["status"] == "not_configured"
    assert llm["reason"] == "GROQ_API_KEY is not set"
    assert llm["model"] == "openai/gpt-oss-120b"


def test_health_shows_the_last_llm_failure_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    config.record("unavailable", "model_not_found: model 'x' was not found (HTTP 404)")

    llm = TestClient(create_app(frontend_dist=tmp_path)).get("/api/health").json()["llm"]

    assert llm["status"] == "unavailable"
    assert "model_not_found" in llm["reason"]
    assert "test-key" not in str(llm)


def test_root_shows_placeholder_when_frontend_is_not_built(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dist=tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert "frontend has not been built" in response.text
