"""Groq client: OpenAI-compatible chat completions over httpx, with a timeout and one retry.

No SDK is used and nothing here is imported at app startup; the planner imports it lazily.
The API key comes from the GROQ_API_KEY environment variable and is never logged, and
prompts are never logged either.

The default model, openai/gpt-oss-120b, is a reasoning model: it is asked for low reasoning
effort, its reasoning is not returned, and only the final message content is parsed.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.llm.config import PROVIDER, LLMConfig, record

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


RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "retry-after",
)


def request_body(config: LLMConfig, system: str, user: str) -> dict[str, Any]:
    return {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "reasoning_effort": REASONING_EFFORT,
        "include_reasoning": False,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }


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
        return LLMUnavailable("server_error", f"Groq server error ({detail})")
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

    Retries once on timeouts, connection errors, 429 and 5xx. Raises LLMUnavailable (with a
    specific kind) when the key is missing, the request is refused, or both attempts fail;
    raises ModelOutputError when the reply is not a JSON object.
    """
    config = config or LLMConfig.from_env()
    if not config.api_key:
        failure = LLMUnavailable("not_configured", "GROQ_API_KEY is not set")
        record("not_configured", failure.reason)
        raise failure
    body = request_body(config, system, user)
    headers = {"Authorization": f"Bearer {config.api_key}"}
    failure = LLMUnavailable("unreachable", "no attempt made")
    wait = RETRY_DELAY_SECONDS
    for attempt in range(1, RETRIES + 2):
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
                log_call(config.model, attempt, f"HTTP {response.status_code}", latency_ms,
                         result.usage)
                record("ok", None)
                return result
            failure = classify(response, config.model)
            log_call(config.model, attempt, failure.reason, latency_ms)
            if response.status_code not in TRANSIENT_STATUS:
                break
            suggested = retry_after_seconds(response)
            if suggested is not None:
                wait = min(max(suggested, RETRY_DELAY_SECONDS), MAX_RETRY_WAIT_SECONDS)
            continue
        log_call(config.model, attempt, failure.reason,
                 round((time.perf_counter() - started) * 1000))
    record("unavailable", f"{failure.kind}: {failure.reason}")
    raise failure


def log_call(model: str, attempt: int, outcome: str, latency_ms: int,
             usage: dict[str, int] | None = None) -> None:
    tokens = ""
    if usage:
        tokens = (f" prompt_tokens={usage.get('prompt_tokens')} "
                  f"completion_tokens={usage.get('completion_tokens')}")
    logger.info("llm provider=%s model=%s attempt=%d outcome=%s latency_ms=%d%s",
                PROVIDER, model, attempt, outcome, latency_ms, tokens)


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
        parsed = json.loads(content)
    except ValueError as error:
        raise ModelOutputError("the reply was not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ModelOutputError("the reply was JSON but not an object")
    usage = {k: int(v) for k, v in (payload.get("usage") or {}).items()
             if isinstance(v, int | float) and k.endswith("tokens")}
    limits = {h: response.headers[h] for h in RATE_LIMIT_HEADERS if h in response.headers}
    return CallResult(data=parsed, latency_ms=latency_ms, usage=usage, rate_limits=limits)


def list_models(
    config: LLMConfig | None = None, transport: httpx.BaseTransport | None = None
) -> list[str]:
    """Model ids the key can use (GET /models). Raises LLMUnavailable on failure."""
    config = config or LLMConfig.from_env()
    if not config.api_key:
        raise LLMUnavailable("not_configured", "GROQ_API_KEY is not set")
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
