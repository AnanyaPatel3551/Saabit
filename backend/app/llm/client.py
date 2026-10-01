"""LLM client: OpenAI-compatible chat completions over httpx, Groq first, then NVIDIA NIM.

No SDK is used and nothing here is imported at app startup; the planner imports it lazily.
API keys come from environment variables and are never logged, and prompts are never logged.

Providers are tried in LLM_PROVIDERS order. A rate limit, server error, timeout or connection
failure falls through to the next provider; a refused request (400, 401, 403, 404) does not.
A rate limit with a long wait (a daily cap) puts that provider on a cool-down until its
retry-after, so later requests skip it. Only the last available provider retries.

The models are reasoning models: they are asked for low reasoning effort and only the final
message content is parsed, never the reasoning.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.llm.config import (
    LLMConfig,
    ProviderConfig,
    available_providers,
    cool_down,
    providers_from_env,
    record,
)

__all__ = ["LLMConfig", "LLMUnavailable", "ModelOutputError", "complete_json", "list_models"]

TIMEOUT_SECONDS = 15.0
RETRIES = 1  # one retry after a transient failure
RETRY_DELAY_SECONDS = 0.5
MAX_COMPLETION_TOKENS = 2048  # reasoning tokens count here too; low effort stays well below
REASONING_EFFORT = "low"
TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
MAX_LOGGED_MESSAGE = 200
MAX_RETRY_WAIT_SECONDS = 5.0  # honour Groq's retry-after up to this; keeps answers under 8 s
ACCOUNT_ID = re.compile(r"org_[A-Za-z0-9]+")
FALLBACK_KINDS = {"rate_limited", "server_error", "timeout", "unreachable"}
LONG_LIMIT_SECONDS = 60.0  # a 429 asking to wait this long or more is a daily-style cap
DEFAULT_COOL_DOWN_SECONDS = 3600.0
DAILY_WORDS = ("per day", "(tpd)", "(rpd)")

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The model could not be reached or refused the request; typed questions pause.

    kind is one of: not_configured, bad_key, model_not_found, rate_limited, timeout,
    server_error, unreachable, bad_request. reason is a short technical note for logs and
    /api/health. message is what users see.
    """

    code = "llm_unavailable"
    message = ("The language model is unavailable right now, so typed questions are paused. "
               "Data checks, insights and edited plans still work.")

    def __init__(self, kind: str, reason: str) -> None:
        self.kind = kind
        self.reason = reason
        super().__init__(f"{self.message} ({kind}: {reason})")


class ModelOutputError(ValueError):
    """The model answered, but not with a usable JSON object."""


@dataclass
class CallResult:
    """A parsed reply plus what the call cost."""

    data: dict[str, Any]
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)
    rate_limits: dict[str, str] = field(default_factory=dict)
    provider: str = ""
    model: str = ""


RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "retry-after",
)


def request_body(config: LLMConfig, system: str, user: str) -> dict[str, Any]:
    """The chat request. The system prompt (static parts first) and the user turn stay
    separate, so providers that cache prompt prefixes can reuse the system part."""
    body: dict[str, Any] = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if config.name == "groq":
        body["include_reasoning"] = False  # Groq-only switch
        body["max_completion_tokens"] = MAX_COMPLETION_TOKENS
    else:
        body["max_tokens"] = MAX_COMPLETION_TOKENS
    return body


def groq_error(response: httpx.Response) -> tuple[str, str]:
    """Groq's error code and message from the body, shortened; never echoes our request.

    Account identifiers (organisation ids) are removed: this text reaches logs and the
    public /api/health endpoint.
    """
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return "", ""
    code = str(error.get("code") or error.get("type") or "")
    message = ACCOUNT_ID.sub("[redacted]", str(error.get("message") or ""))
    return code, message[:MAX_LOGGED_MESSAGE]


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Groq's retry-after header in seconds, if present and numeric."""
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def classify(response: httpx.Response, model: str) -> LLMUnavailable:
    """Turn a failed HTTP response into a specific, loggable LLMUnavailable."""
    status = response.status_code
    code, text = groq_error(response)
    detail = f"HTTP {status}" + (f" {code}" if code else "") + (f": {text}" if text else "")
    if status in (401, 403):
        return LLMUnavailable("bad_key", f"the API key was rejected ({detail})")
    if status == 404:
        return LLMUnavailable("model_not_found", f"model '{model}' was not found ({detail})")
    if status == 429:
        wait = response.headers.get("retry-after")
        return LLMUnavailable("rate_limited", f"rate limit reached ({detail}"
                              + (f", retry after {wait}s)" if wait else ")"))
    if status >= 500:
        return LLMUnavailable("server_error", f"server error ({detail})")
    return LLMUnavailable("bad_request", f"request rejected ({detail})")


def complete_json(
    system: str,
    user: str,
    *,
    config: LLMConfig | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Ask the model for one JSON object and return it parsed (see call_json)."""
    return call_json(system, user, config=config, transport=transport).data


def call_json(
    system: str,
    user: str,
    *,
    config: LLMConfig | None = None,
    transport: httpx.BaseTransport | None = None,
) -> CallResult:
    """One JSON completion with temperature 0, JSON mode and low reasoning effort.

    With config, only that provider is used. Otherwise providers are tried in order (see the
    module docstring). Raises LLMUnavailable (with a specific kind) when no provider can
    answer; raises ModelOutputError when the reply is not a JSON object.
    """
    providers = [config] if config is not None else available_providers()
    if not providers or not providers[0].api_key:
        failure = no_provider_failure(config)
        record(failure.kind, failure.reason)
        raise failure
    failure = LLMUnavailable("unreachable", "no attempt made")
    for index, provider in enumerate(providers):
        last = index == len(providers) - 1
        try:
            result = call_provider(provider, system, user, transport,
                                   retries=RETRIES if last else 0)
        except LLMUnavailable as error:
            failure = error
            if error.kind not in FALLBACK_KINDS or last:
                break
            logger.info("llm provider=%s failed (%s); trying %s", provider.name, error.kind,
                        providers[index + 1].name)
            continue
        record("ok", None, provider.name, provider.model)
        return result
    record("unavailable", f"{failure.kind}: {failure.reason}")
    raise failure


def no_provider_failure(config: LLMConfig | None) -> LLMUnavailable:
    """Why no provider can be used: none has a key, or every configured one is cooling down."""
    if config is not None:
        return LLMUnavailable("not_configured", f"{config.key_env} is not set")
    configs = providers_from_env()
    if not any(p.api_key for p in configs):
        missing = "; ".join(f"{p.key_env} is not set" for p in configs) or "no provider listed"
        return LLMUnavailable("not_configured", missing)
    names = ", ".join(p.name for p in configs if p.api_key)
    return LLMUnavailable("rate_limited",
                          f"every provider is cooling down after a rate limit ({names})")


def call_provider(
    config: ProviderConfig,
    system: str,
    user: str,
    transport: httpx.BaseTransport | None,
    retries: int,
) -> CallResult:
    """Call one provider, retrying transient failures `retries` times."""
    body = request_body(config, system, user)
    headers = {"Authorization": f"Bearer {config.api_key}"}
    failure = LLMUnavailable("unreachable", "no attempt made")
    wait = RETRY_DELAY_SECONDS
    for attempt in range(1, retries + 2):
        if attempt > 1:
            time.sleep(wait)
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
                response = client.post(f"{config.base_url}/chat/completions",
                                       json=body, headers=headers)
        except httpx.TimeoutException:
            failure = LLMUnavailable("timeout", f"no reply within {TIMEOUT_SECONDS:g} s")
        except httpx.TransportError as error:
            failure = LLMUnavailable("unreachable", f"could not connect ({type(error).__name__})")
        else:
            latency_ms = round((time.perf_counter() - started) * 1000)
            if response.status_code < 400:
                result = parse_reply(response, latency_ms)
                result.provider, result.model = config.name, config.model
                log_call(config, attempt, f"HTTP {response.status_code}", latency_ms,
                         result.usage)
                return result
            failure = classify(response, config.model)
            log_call(config, attempt, failure.reason, latency_ms)
            if response.status_code not in TRANSIENT_STATUS:
                break
            suggested = retry_after_seconds(response)
            if response.status_code == 429 and is_long_limit(failure.reason, suggested):
                seconds = suggested or DEFAULT_COOL_DOWN_SECONDS
                cool_down(config.name, seconds)
                logger.info("llm provider=%s cooling down for %.0f s", config.name, seconds)
                break
            if suggested is not None:
                wait = min(max(suggested, RETRY_DELAY_SECONDS), MAX_RETRY_WAIT_SECONDS)
            continue
        log_call(config, attempt, failure.reason, round((time.perf_counter() - started) * 1000))
    raise failure


def is_long_limit(reason: str, retry_after: float | None) -> bool:
    """A daily cap (or any limit asking for a minute or more) is not worth waiting for."""
    lowered = reason.lower()
    return any(w in lowered for w in DAILY_WORDS) or (
        retry_after is not None and retry_after >= LONG_LIMIT_SECONDS)


def log_call(config: ProviderConfig, attempt: int, outcome: str, latency_ms: int,
             usage: dict[str, int] | None = None) -> None:
    tokens = ""
    if usage:
        tokens = (f" prompt_tokens={usage.get('prompt_tokens')} "
                  f"completion_tokens={usage.get('completion_tokens')} "
                  f"cached_tokens={usage.get('cached_tokens', 0)}")
    logger.info("llm provider=%s model=%s attempt=%d outcome=%s latency_ms=%d%s",
                config.name, config.model, attempt, outcome, latency_ms, tokens)


def parse_reply(response: httpx.Response, latency_ms: int) -> CallResult:
    """Parse only the final message content; any returned reasoning is ignored."""
    try:
        payload = response.json()
        choice = payload["choices"][0]
        content = choice["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ModelOutputError(f"the reply had no message ({type(error).__name__})") from error
    if not content.strip():
        reason = choice.get("finish_reason") or "unknown"
        raise ModelOutputError(f"the reply was empty (finish_reason: {reason})")
    try:
        parsed = json.loads(strip_fences(content))
    except ValueError as error:
        raise ModelOutputError("the reply was not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ModelOutputError("the reply was JSON but not an object")
    usage = usage_counts(payload.get("usage") or {})
    limits = {h: response.headers[h] for h in RATE_LIMIT_HEADERS if h in response.headers}
    return CallResult(data=parsed, latency_ms=latency_ms, usage=usage, rate_limits=limits)


def strip_fences(content: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode; remove them."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def usage_counts(usage: dict[str, Any]) -> dict[str, int]:
    """Token counts from the usage field, plus cached prompt tokens when reported."""
    counts = {k: int(v) for k, v in usage.items()
              if isinstance(v, int | float) and k.endswith("tokens")}
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if isinstance(cached, int | float) and cached:
        counts["cached_tokens"] = int(cached)
    return counts


def list_models(
    config: LLMConfig | None = None, transport: httpx.BaseTransport | None = None
) -> list[str]:
    """Model ids the key can use (GET /models). Raises LLMUnavailable on failure."""
    config = config or LLMConfig.from_env()
    if not config.api_key:
        raise LLMUnavailable("not_configured", f"{config.key_env} is not set")
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = client.get(f"{config.base_url}/models",
                                  headers={"Authorization": f"Bearer {config.api_key}"})
    except httpx.TimeoutException as error:
        raise LLMUnavailable("timeout", f"no reply within {TIMEOUT_SECONDS:g} s") from error
    except httpx.TransportError as error:
        raise LLMUnavailable("unreachable",
                             f"could not connect ({type(error).__name__})") from error
    if response.status_code >= 400:
        raise classify(response, config.model)
    return sorted(str(m.get("id")) for m in response.json().get("data", []))
