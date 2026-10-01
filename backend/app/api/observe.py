"""Request ids, one structured JSON log line per request, and security headers.

The log line holds only: request id, method, path (never the query string, which can carry a
question), dataset id, status, outcome, latency, and the fields routes add with note():
plan status, verified flag, answer source and LLM provider. Never rows, cell values,
questions or keys (PRD Observability).
"""

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response

request_log = logging.getLogger("saabit.requests")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}
DATASET_IN_PATH = re.compile(r"^/api/(?:datasets|cards)/([0-9a-f]{12})(?:[-/]|$)")
ALLOWED_FIELDS = {"plan_status", "verified", "source", "llm_provider"}


def note(request: Request, **fields: Any) -> None:
    """Add safe, non-data fields to this request's log line (see ALLOWED_FIELDS)."""
    unknown = set(fields) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"not allowed in request logs: {sorted(unknown)}")
    request.state.log.update(fields)


def outcome_of(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "error"
    return "client_error" if status >= 400 else "ok"


def log_line(request: Request, status: int, started: float, outcome: str | None = None) -> str:
    match = DATASET_IN_PATH.match(request.url.path)
    record = {
        "request_id": request.state.request_id,
        "method": request.method,
        "path": request.url.path,
        "dataset_id": match.group(1) if match else None,
        "status": status,
        "outcome": outcome or request.state.log.pop("outcome", None) or outcome_of(status),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        **request.state.log,
    }
    return json.dumps(record, separators=(",", ":"))


def add_security_headers(response: Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)


def setup_logging() -> None:
    """Print request lines to stdout when nothing else (uvicorn, pytest) has set up logging."""
    request_log.setLevel(logging.INFO)
    if not request_log.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        request_log.addHandler(handler)


def install(app: FastAPI) -> None:
    """Attach the request middleware to the app."""
    setup_logging()

    @app.middleware("http")
    async def observe(request: Request,
                      call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        request.state.request_id = uuid.uuid4().hex[:12]
        request.state.log = {}
        try:
            response = await call_next(request)
        except Exception:
            # The catch-all handler answers the user; this records the failed request.
            request_log.info(log_line(request, 500, started, "error"))
            raise
        response.headers["X-Request-ID"] = request.state.request_id
        add_security_headers(response)
        request_log.info(log_line(request, response.status_code, started))
        return response
