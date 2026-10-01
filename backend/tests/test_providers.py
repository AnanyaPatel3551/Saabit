"""Groq first, NIM as fallback: when to fall back, when not to, and the daily-limit cool-down.

All fakes (httpx.MockTransport); nothing here reaches the network.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import client as llm
from app.llm import config
from app.main import create_app


@pytest.fixture
def both_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("NIM_API_KEY", "nim-key")
    monkeypatch.setenv("GROQ_BASE_URL", "https://groq.test/v1")
    monkeypatch.setenv("NIM_BASE_URL", "https://nim.test/v1")
    monkeypatch.setenv("NIM_MODEL", "nim/test-model")
    monkeypatch.setattr(llm, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(config, "_last", None)


def ok_reply(usage: dict | None = None) -> httpx.Response:
    body = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 2}}
    return httpx.Response(200, json=body)


class Fake:
    """Answers per host and records which hosts were called, with their request bodies."""

    def __init__(self, groq: list, nim: list | None = None) -> None:
        self.replies = {"groq.test": list(groq), "nim.test": list(nim or [ok_reply()])}
        self.calls: list[str] = []
        self.bodies: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.calls.append(host)
        self.bodies[host] = json.loads(request.content)
        reply = self.replies[host].pop(0) if len(self.replies[host]) > 1 \
            else self.replies[host][0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def limited(retry_after: str, message: str = "Rate limit reached on tokens per minute (TPM)"):
    return httpx.Response(429, headers={"retry-after": retry_after},
                          json={"error": {"message": message, "code": "rate_limit_exceeded"}})


def test_groq_429_falls_back_to_nim(both_providers: None) -> None:
    fake = Fake(groq=[limited("3")])

    result = llm.call_json("s", "u", transport=fake.transport())

    assert fake.calls == ["groq.test", "nim.test"]
    assert (result.provider, result.model) == ("nim", "nim/test-model")


def test_groq_5xx_falls_back_to_nim(both_providers: None) -> None:
    fake = Fake(groq=[httpx.Response(503)])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "nim"
    assert fake.calls == ["groq.test", "nim.test"]


def test_groq_timeout_falls_back_to_nim(both_providers: None) -> None:
    fake = Fake(groq=[httpx.ReadTimeout("slow")])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "nim"


@pytest.mark.parametrize("status", [400, 401])
def test_400_and_401_do_not_fall_back(both_providers: None, status: int) -> None:
    fake = Fake(groq=[httpx.Response(status, json={"error": {"message": "no", "code": "x"}})])

    with pytest.raises(llm.LLMUnavailable):
        llm.call_json("s", "u", transport=fake.transport())

    assert fake.calls == ["groq.test"]


def test_daily_limit_skips_groq_until_retry_after(both_providers: None) -> None:
    daily = limited("638", "Rate limit reached on tokens per day (TPD): Limit 200000")
    fake = Fake(groq=[daily, ok_reply()])

    first = llm.call_json("s", "u", transport=fake.transport())
    second = llm.call_json("s", "u", transport=fake.transport())

    assert (first.provider, second.provider) == ("nim", "nim")
    assert fake.calls == ["groq.test", "nim.test", "nim.test"]
    assert config.cooling_until("groq") is not None


def test_groq_is_used_again_after_its_cool_down(both_providers: None,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    config.cool_down("groq", 600)
    clock = config.time.time() + 601
    monkeypatch.setattr(config.time, "time", lambda: clock)
    fake = Fake(groq=[ok_reply()])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "groq"


def test_short_rate_limit_does_not_start_a_cool_down(both_providers: None) -> None:
    fake = Fake(groq=[limited("3")])

    llm.call_json("s", "u", transport=fake.transport())

    assert config.cooling_until("groq") is None


def test_provider_order_comes_from_LLM_PROVIDERS(both_providers: None,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDERS", "nim,groq")
    fake = Fake(groq=[ok_reply()])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "nim"
    assert fake.calls == ["nim.test"]
    monkeypatch.setenv("LLM_PROVIDERS", "groq")
    assert [p.name for p in config.providers_from_env()] == ["groq"]


def test_unconfigured_provider_is_skipped(both_providers: None,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY")
    fake = Fake(groq=[ok_reply()])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "nim"
    assert fake.calls == ["nim.test"]


def test_last_provider_still_retries_once(both_providers: None) -> None:
    fake = Fake(groq=[httpx.Response(503)], nim=[httpx.Response(503), ok_reply()])

    assert llm.call_json("s", "u", transport=fake.transport()).provider == "nim"
    assert fake.calls == ["groq.test", "nim.test", "nim.test"]


def test_nim_body_has_no_groq_only_fields(both_providers: None) -> None:
    fake = Fake(groq=[httpx.Response(503)])

    llm.call_json("sys", "user", transport=fake.transport())

    nim, groq = fake.bodies["nim.test"], fake.bodies["groq.test"]
    assert "include_reasoning" not in nim
    assert nim["response_format"] == {"type": "json_object"}
    assert nim["reasoning_effort"] == "low"
    assert nim["model"] == "nim/test-model"
    assert groq["include_reasoning"] is False


def test_cached_tokens_are_read_from_usage(both_providers: None) -> None:
    usage = {"prompt_tokens": 1800, "completion_tokens": 40,
             "prompt_tokens_details": {"cached_tokens": 1536}}
    fake = Fake(groq=[ok_reply(usage)])

    result = llm.call_json("s", "u", transport=fake.transport())

    assert result.usage == {"prompt_tokens": 1800, "completion_tokens": 40,
                            "cached_tokens": 1536}


def test_json_in_code_fences_is_accepted(both_providers: None) -> None:
    fenced = "`" * 3 + 'json\n{"ok": true}\n' + "`" * 3
    reply = httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})
    fake = Fake(groq=[reply])

    assert llm.call_json("s", "u", transport=fake.transport()).data == {"ok": True}


def test_health_shows_the_active_provider(both_providers: None, tmp_path) -> None:
    fake = Fake(groq=[limited("638", "tokens per day (TPD)")])
    llm.call_json("s", "u", transport=fake.transport())

    body = TestClient(create_app(frontend_dist=tmp_path)).get("/api/health").json()["llm"]

    assert (body["provider"], body["model"], body["status"]) == ("nim", "nim/test-model", "ok")
    rows = {p["name"]: p for p in body["providers"]}
    assert rows["groq"]["cooling_until"] is not None
    assert rows["nim"]["configured"] is True
    assert "groq-key" not in str(body) and "nim-key" not in str(body)


def test_every_provider_cooling_down_is_reported(both_providers: None) -> None:
    config.cool_down("groq", 600)
    config.cool_down("nim", 600)

    with pytest.raises(llm.LLMUnavailable) as error:
        llm.call_json("s", "u")

    assert error.value.kind == "rate_limited"
    assert "cooling down" in error.value.reason
