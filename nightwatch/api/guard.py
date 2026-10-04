"""Edge protection for the API: a shared secret from the Vercel proxy and per-client
rate limits.

The API sits behind a same-origin proxy, but its port is public. With
NIGHTWATCH_PROXY_SECRET set, only the proxy (or the box itself) is let in, so a stranger
cannot spend the model budget by calling the box directly. Unset, the check is off, which
keeps the first rollout safe. Limits are in-process token buckets: one worker, one box.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import OrderedDict

SECRET_ENV = "NIGHTWATCH_PROXY_SECRET"
SECRET_HEADER = "x-nightwatch-proxy-secret"
CLIENT_IP_HEADER = "x-nightwatch-client-ip"
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})
MAX_BUCKETS = 5000

# Chat and analyze are what a person clicks through quickly: five to eight messages in
# a few seconds is ordinary for a judge trying the example chips. A burst of 12 that
# refills one every 3 seconds is more than a hand can spend, and the same bucket still
# caps a script at 20 a minute. The model slots (providers.llm_slot) bound the cost of whatever gets in.
CHAT_PER_MIN = 20
CHAT_BURST = 12

# (method or None for any, path prefix, per-minute rate, burst). First match wins.
RULES: tuple[tuple[str | None, str, float, int], ...] = (
    ("POST", "/chat", CHAT_PER_MIN, CHAT_BURST),
    ("POST", "/analyze", CHAT_PER_MIN, CHAT_BURST),
    ("POST", "/agent/", 3, 3),
    ("POST", "/analyst/", 10, 5),
    ("POST", "/tonight", 4, 2),
    (None, "/mcp", 20, 10),
    ("POST", "/watch", 10, 5),
    ("POST", "/tripwire", 10, 5),
    ("POST", "/plan", 10, 5),
    ("POST", "/feedback", 10, 5),
)


def proxy_secret() -> str:
    return os.environ.get(SECRET_ENV, "")


def secret_ok(headers: dict[str, str] | object, secret: str) -> bool:
    """Constant-time check of the proxy header against the configured secret."""
    given = headers.get(SECRET_HEADER, "") if hasattr(headers, "get") else ""
    return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())


def is_local(host: str | None) -> bool:
    return (host or "") in LOCAL_HOSTS


def rule_for(method: str, path: str) -> tuple[str, float, int] | None:
    for m, prefix, rate, burst in RULES:
        if (m is None or m == method) and (path == prefix.rstrip("/") or path.startswith(prefix)):
            return prefix.strip("/"), rate, burst
    return None


class RateLimiter:
    """Token buckets keyed by (group, client), least-recently-used evicted past a cap."""

    def __init__(self, max_buckets: int = MAX_BUCKETS, clock=time.monotonic):  # noqa: ANN001
        self._buckets: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_buckets
        self._clock = clock

    def __len__(self) -> int:
        return len(self._buckets)

    def take(self, group: str, client: str, rate_per_min: float, burst: int) -> float:
        """0.0 if allowed, else seconds until a token is available."""
        now = self._clock()
        per_s = rate_per_min / 60.0
        key = (group, client)
        with self._lock:
            tokens, last = self._buckets.pop(key, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * per_s)
            if tokens >= 1.0:
                tokens -= 1.0
                wait = 0.0
            else:
                wait = (1.0 - tokens) / per_s
            self._buckets[key] = (tokens, now)
            while len(self._buckets) > self._max:
                self._buckets.popitem(last=False)
        return wait
