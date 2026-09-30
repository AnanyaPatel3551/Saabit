"""LLM settings from the environment, and the last known LLM status for /api/health.

Cheap to import (no network libraries), so the health route can use it without loading
the client.
"""

import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

PROVIDER = "groq"
API_KEY_ENV = "GROQ_API_KEY"
MODEL_ENV = "GROQ_MODEL"
BASE_URL_ENV = "GROQ_BASE_URL"
# Llama 3.3 70B (llama-3.3-70b-versatile) was retired by Groq on 16 Aug 2026.
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.environ.get(API_KEY_ENV, ""),
            model=os.environ.get(MODEL_ENV) or DEFAULT_MODEL,
            base_url=(os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/"),
        )


@dataclass(frozen=True)
class LLMStatus:
    """What /api/health reports. 'unknown' until the first call in this process."""

    provider: str
    model: str
    status: str  # "ok", "unavailable", "not_configured" or "unknown"
    reason: str | None
    checked_at: str | None


_lock = threading.Lock()
_last: tuple[str, str | None, str] | None = None  # (status, reason, when)


def record(status: str, reason: str | None) -> None:
    """Remember the outcome of the latest LLM call (never includes the key or prompt)."""
    global _last
    with _lock:
        _last = (status, reason, datetime.now(UTC).isoformat())


def current_status() -> LLMStatus:
    config = LLMConfig.from_env()
    if not config.api_key:
        return LLMStatus(PROVIDER, config.model, "not_configured",
                         f"{API_KEY_ENV} is not set", None)
    with _lock:
        last = _last
    if last is None:
        return LLMStatus(PROVIDER, config.model, "unknown", "no call made yet", None)
    status, reason, when = last
    return LLMStatus(PROVIDER, config.model, status, reason, when)


def status_dict() -> dict:
    return asdict(current_status())
