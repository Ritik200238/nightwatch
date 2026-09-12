"""Resilient HTTP transport shared by all sources.

Why this exists
---------------
Every upstream we use is a free public endpoint with its own failure modes: Bitget
throttles per IP and reports remaining budget in a header; Yahoo blocks default
user agents; Nasdaq needs browser-like headers; FRED occasionally returns 5xx.
One transport with retries, backoff, a token-bucket limiter and header-aware
slow-down keeps every source honest without duplicating that logic five times.

Behaviour
---------
* Retries on connection errors, timeouts, HTTP 429 and 5xx with exponential backoff
  and full jitter; honours ``Retry-After`` when present.
* Never retries non-idempotent requests unless told to (all our calls are GETs).
* Token-bucket rate limiting per client instance (thread-safe).
* Optional ``remaining_header``: when the upstream says fewer than ``slow_threshold``
  requests remain in the window, the client sleeps until the window rolls over.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class TransportError(RuntimeError):
    """Raised when a request fails after all retries."""


class UpstreamError(RuntimeError):
    """Raised for a well-formed but non-success upstream payload (e.g. Bitget code != 00000)."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class TokenBucket:
    """Classic token bucket; ``acquire`` blocks until a token is available."""

    def __init__(self, rate_per_sec: float, burst: int):
        if rate_per_sec <= 0 or burst <= 0:
            raise ValueError("rate and burst must be positive")
        self.rate = float(rate_per_sec)
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            time.sleep(wait)


@dataclass
class RetryPolicy:
    max_attempts: int = 6
    base_delay: float = 0.5
    max_delay: float = 20.0
    retry_on_status: frozenset[int] = field(default_factory=lambda: RETRYABLE_STATUS)

    def delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(self.max_delay, max(0.0, retry_after))
        cap = min(self.max_delay, self.base_delay * (2**attempt))
        return random.uniform(0, cap)  # full jitter


class HttpClient:
    def __init__(
        self,
        base_url: str = "",
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        rate_per_sec: float = 8.0,
        burst: int = 8,
        retry: RetryPolicy | None = None,
        remaining_header: str | None = None,
        slow_threshold: int = 2,
        slow_sleep: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._client = httpx.Client(
            base_url=base_url,
            headers=dict(headers or {}),
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )
        self._bucket = TokenBucket(rate_per_sec, burst)
        self._retry = retry or RetryPolicy()
        self._remaining_header = remaining_header
        self._slow_threshold = slow_threshold
        self._slow_sleep = slow_sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._retry.max_attempts):
            self._bucket.acquire()
            try:
                resp = self._client.get(path, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                delay = self._retry.delay(attempt, None)
                log.warning("GET %s failed (%s); retry %d in %.2fs", path, exc, attempt + 1, delay)
                time.sleep(delay)
                continue

            self._observe_budget(resp)

            if resp.status_code in self._retry.retry_on_status:
                last_error = httpx.HTTPStatusError(
                    f"status {resp.status_code}", request=resp.request, response=resp
                )
                delay = self._retry.delay(attempt, _retry_after_seconds(resp))
                log.warning(
                    "GET %s -> %d; retry %d in %.2fs", path, resp.status_code, attempt + 1, delay
                )
                time.sleep(delay)
                continue

            return resp

        raise TransportError(f"GET {path} failed after {self._retry.max_attempts} attempts") from last_error

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        resp = self.get(path, params)
        if resp.status_code >= 400:
            raise UpstreamError(
                f"GET {path} -> HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise UpstreamError(f"GET {path}: non-JSON body: {resp.text[:200]}") from exc

    def get_text(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        resp = self.get(path, params)
        if resp.status_code >= 400:
            raise UpstreamError(
                f"GET {path} -> HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
            )
        return resp.text

    def _observe_budget(self, resp: httpx.Response) -> None:
        if not self._remaining_header:
            return
        raw = resp.headers.get(self._remaining_header)
        if raw is None:
            return
        try:
            remaining = int(raw)
        except ValueError:
            return
        if remaining <= self._slow_threshold:
            log.info("upstream budget low (%s=%d); sleeping %.1fs", self._remaining_header, remaining, self._slow_sleep)
            time.sleep(self._slow_sleep)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
