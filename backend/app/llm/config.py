"""LLM providers from the environment, their cool-downs, and the last known LLM status.

Cheap to import (no network libraries), so the health route can use it without loading
the client. Keys come only from environment variables and are never logged or returned.

Providers are tried in the order given by LLM_PROVIDERS (default "groq,nim"):
- groq: GROQ_API_KEY, GROQ_MODEL, GROQ_BASE_URL
- nim:  NIM_API_KEY, NIM_MODEL, NIM_BASE_URL (NVIDIA NIM, OpenAI-compatible)
"""

import logging
import os
import threading
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Which provider answered the latest LLM call in this request (for the request log).
served_by: ContextVar[str | None] = ContextVar("served_by", default=None)

PROVIDERS_ENV = "LLM_PROVIDERS"
DEFAULT_PROVIDERS = "groq,nim"

# Kept for callers that only know Groq.
PROVIDER = "groq"
API_KEY_ENV = "GROQ_API_KEY"
MODEL_ENV = "GROQ_MODEL"
BASE_URL_ENV = "GROQ_BASE_URL"
# Llama 3.3 70B (llama-3.3-70b-versatile) was retired by Groq on 16 Aug 2026.
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class ProviderSpec:
    """Where a provider's settings live and their defaults."""

    key_env: str
    model_env: str
    base_url_env: str
    default_model: str
    default_base_url: str
    timeout_s: float  # per call; the fallback gets longer because it only runs when needed


SPECS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec(API_KEY_ENV, MODEL_ENV, BASE_URL_ENV, DEFAULT_MODEL, DEFAULT_BASE_URL,
                         15.0),
    # NIM does not serve openai/gpt-oss-120b (checked 1 Oct 2026); see docs for the choice.
    "nim": ProviderSpec("NIM_API_KEY", "NIM_MODEL", "NIM_BASE_URL",
                        "nvidia/nemotron-3-super-120b-a12b",
                        "https://integrate.api.nvidia.com/v1", 30.0),
}


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str
    model: str
    base_url: str
    name: str = PROVIDER

    @property
    def key_env(self) -> str:
        return SPECS[self.name].key_env

    @property
    def timeout(self) -> float:
        return SPECS[self.name].timeout_s

    @classmethod
    def from_env(cls, name: str = PROVIDER) -> "ProviderConfig":
        spec = SPECS[name]
        return cls(
            api_key=os.environ.get(spec.key_env, ""),
            model=os.environ.get(spec.model_env) or spec.default_model,
            base_url=(os.environ.get(spec.base_url_env) or spec.default_base_url).rstrip("/"),
            name=name,
        )


LLMConfig = ProviderConfig  # the original name, still used by callers and tests


def provider_names() -> list[str]:
    """Provider order from LLM_PROVIDERS; unknown names are skipped with a warning."""
    names = []
    for raw in (os.environ.get(PROVIDERS_ENV) or DEFAULT_PROVIDERS).split(","):
        name = raw.strip().lower()
        if not name:
            continue
        if name not in SPECS:
            logger.warning("unknown LLM provider '%s' in %s is ignored", name, PROVIDERS_ENV)
        elif name not in names:
            names.append(name)
    return names


def providers_from_env() -> list[ProviderConfig]:
    """Every provider in order, configured or not."""
    return [ProviderConfig.from_env(name) for name in provider_names()]


# --- cool-downs: a provider that hit a long rate limit (e.g. its daily cap) is skipped ----

_lock = threading.Lock()
_cooling: dict[str, float] = {}  # provider -> time.time() until which it is skipped


def cool_down(name: str, seconds: float) -> None:
    with _lock:
        _cooling[name] = time.time() + seconds


def cooling_until(name: str) -> float | None:
    """Epoch seconds until which the provider is skipped, or None when it is usable."""
    with _lock:
        until = _cooling.get(name)
        if until is not None and until <= time.time():
            del _cooling[name]
            until = None
    return until


def clear_cool_downs() -> None:
    with _lock:
        _cooling.clear()


def available_providers() -> list[ProviderConfig]:
    """Configured providers that are not cooling down, in order."""
    return [p for p in providers_from_env() if p.api_key and cooling_until(p.name) is None]


# --- status for /api/health -------------------------------------------------------------

@dataclass(frozen=True)
class LLMStatus:
    """What /api/health reports. 'unknown' until the first call in this process."""

    provider: str
    model: str
    status: str  # "ok", "unavailable", "not_configured" or "unknown"
    reason: str | None
    checked_at: str | None
    providers: list[dict]
    state: str  # last call: "ok" (first provider), "fallback", "down"; "unknown" before any call


_last: tuple[str, str | None, str, str | None, str | None] | None = None
# (status, reason, when, provider, model)


def record(status: str, reason: str | None, provider: str | None = None,
           model: str | None = None) -> None:
    """Remember the outcome of the latest LLM call (never includes the key or prompt)."""
    global _last
    with _lock:
        _last = (status, reason, datetime.now(UTC).isoformat(), provider, model)


def provider_rows(configs: list[ProviderConfig]) -> list[dict]:
    rows = []
    for p in configs:
        until = cooling_until(p.name)
        rows.append({"name": p.name, "model": p.model, "configured": bool(p.api_key),
                     "cooling_until": datetime.fromtimestamp(until, UTC).isoformat()
                     if until else None})
    return rows


def current_status() -> LLMStatus:
    configs = providers_from_env()
    rows = provider_rows(configs)
    configured = [p for p in configs if p.api_key]
    if not configured:
        first = configs[0] if configs else ProviderConfig.from_env()
        missing = "; ".join(f"{p.key_env} is not set" for p in configs) or "no provider listed"
        return LLMStatus(first.name, first.model, "not_configured", missing, None, rows, "down")
    usable = [p for p in configured if cooling_until(p.name) is None]
    active = usable[0] if usable else configured[0]
    with _lock:
        last = _last
    if last is None:
        return LLMStatus(active.name, active.model, "unknown", "no call made yet", None, rows,
                         "unknown")
    status, reason, when, provider, model = last
    state = call_state(status, provider, configured[0].name)
    return LLMStatus(provider or active.name, model or active.model, status, reason, when, rows,
                     state)


def call_state(status: str, provider: str | None, first: str) -> str:
    """ok: the first configured provider answered; fallback: a later one did; down: none."""
    if status != "ok":
        return "down"
    return "ok" if provider in (None, first) else "fallback"


def status_dict() -> dict:
    return asdict(current_status())
