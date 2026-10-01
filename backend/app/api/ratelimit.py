"""Per-client rate limits, kept in memory (PRD Production readiness: Abuse).

30 questions per 10 minutes and 5 uploads per hour per client IP. A sliding window: each
client's recent request times are kept and old ones dropped, so a limit frees up gradually.
State lives in this process only: a restart clears it, and several workers would each keep
their own counts (Render runs one).
"""

import ipaddress
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.api.errors import RateLimited

TRUSTED_PROXIES_ENV = "SAABIT_TRUSTED_PROXIES"
# Render's proxy reaches the app from a private address; a direct client does not.
DEFAULT_TRUSTED = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128,fc00::/7"
MAX_TRACKED_CLIENTS = 10_000  # caps memory if many addresses appear at once


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window_s: float
    message: str


QUESTION_LIMIT = "Too many questions from this connection: the limit is 30 every 10 minutes."
# Typed questions (/plan) and answers (/run, also used by chips) are counted separately, so a
# typed question, which needs both, is not counted twice against the same 30.
QUESTIONS = Limit("questions", 30, 600, QUESTION_LIMIT)
ANSWERS = Limit("answers", 30, 600, QUESTION_LIMIT)
SENTENCES = Limit("sentences", 30, 600, QUESTION_LIMIT)
UPLOADS = Limit("uploads", 5, 3600,
                "Too many uploads from this connection: the limit is 5 an hour.")


class RateLimiter:
    """Sliding-window counters per (limit, client). Thread-safe; routes run in a thread pool."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[tuple[str, str], deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, limit: Limit, client: str) -> None:
        """Count one request, or raise RateLimited with the seconds until the next free slot."""
        now = self.clock()
        with self.lock:
            hits = self.hits.setdefault((limit.name, client), deque())
            while hits and hits[0] <= now - limit.window_s:
                hits.popleft()
            if len(hits) >= limit.max_requests:
                retry_after = max(1, math.ceil(hits[0] + limit.window_s - now))
                raise RateLimited(f"{limit.message} Try again in {wait_text(retry_after)}.",
                                  retry_after)
            hits.append(now)
            if len(self.hits) > MAX_TRACKED_CLIENTS:
                self.forget_idle(now)

    def forget_idle(self, now: float) -> None:
        """Drop clients with no request inside their window (called under the lock)."""
        windows = {rule.name: rule.window_s
                   for rule in (QUESTIONS, ANSWERS, SENTENCES, UPLOADS)}
        for key in [k for k, v in self.hits.items()
                    if not v or v[-1] <= now - windows.get(k[0], 3600)]:
            del self.hits[key]


def wait_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get(TRUSTED_PROXIES_ENV) or DEFAULT_TRUSTED
    return [ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",")
            if part.strip()]


def is_trusted_proxy(host: str | None) -> bool:
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(address in network for network in trusted_networks())


def client_ip(request: Request) -> str:
    """The client's address. Behind the proxy (the socket peer is a trusted proxy address),
    the first address in X-Forwarded-For; otherwise the socket address, ignoring the header,
    because a direct client could write anything there."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and is_trusted_proxy(peer):
        first = forwarded.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(first))
        except ValueError:
            return peer
    return peer


def limit(rule: Limit) -> Callable[[Request], None]:
    """A route dependency that counts the request against `rule` for this client."""
    def dependency(request: Request) -> None:
        request.app.state.limiter.check(rule, client_ip(request))
    return dependency
