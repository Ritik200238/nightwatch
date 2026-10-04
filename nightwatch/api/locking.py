"""A lock that lets people go before the background warm-up.

Every analysis shares one frame cache, so they run one at a time under a single lock.
The warm-up loop takes that lock too, once per token, to build all twenty-four frames
after a restart and again at the top of every hour. A plain lock is not fair: the warm
loop releases it and takes it straight back, so a chat that arrived meanwhile waited for
the whole pass. Measured on the box after a restart, a weekend NVDA question sent while
the warm-up was at 14 of 24 tokens took 26 s; it needs one frame and builds it in about one.

Requests use it exactly like ``threading.Lock`` (``with lock:``). The warm-up uses
``with lock.background():``, which first waits until no request holds or wants the lock.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class RequestFirstLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cv = threading.Condition()
        self._wanted = 0  # requests that hold the lock or are waiting for it

    def __enter__(self) -> RequestFirstLock:
        with self._cv:
            self._wanted += 1
        try:
            self._lock.acquire()
        except BaseException:
            self._done()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self._lock.release()
        self._done()

    def _done(self) -> None:
        with self._cv:
            self._wanted -= 1
            self._cv.notify_all()

    @property
    def wanted(self) -> int:
        return self._wanted

    @contextmanager
    def background(self, max_wait_s: float | None = None) -> Iterator[None]:
        """Hold the lock for background work, once no request wants it.

        A request that arrives after this has started still waits for this one step, so
        background steps must stay short (one token's frame, about a second)."""
        with self._cv:
            self._cv.wait_for(lambda: self._wanted == 0, timeout=max_wait_s)
        with self._lock:
            yield
