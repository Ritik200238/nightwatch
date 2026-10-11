"""One computation per key at a time; concurrent callers for the same key share its result.

The cached pages each take 5-45 s to recompute on the box, under the analysis lock. With the
cache empty or expired, every concurrent request for the same page recomputed it on its own:
after one restart, four ``/misses`` recomputes held the lock 28, 7, 5 and 4 s for one answer
while a visitor's chat queued 12.5 s behind them. Now the first caller computes and the others
wait for it.

Runs on the event loop: the map of flights is only touched from coroutines on one loop, so it
needs no lock. Every way the computation can end releases the waiters:

* it returns: each waiter gets the same result;
* it raises: each waiter gets the same exception (nothing is cached on failure, so the next
  caller after it starts afresh);
* the computing request is cancelled (its client went away): waiters are told the computation
  is gone and one of them computes instead, so they are not failed for someone else's leaving;
* a waiter's own wait runs out: it stops waiting and computes by itself, as before this existed;
  the flight it left carries on for the others.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class _Gone(Exception):
    """The computing caller was cancelled before it finished."""


def _retrieve(fut: asyncio.Future) -> None:
    # A flight nobody waited on would otherwise log "exception was never retrieved".
    if not fut.cancelled():
        fut.exception()


class SingleFlight(Generic[T]):
    def __init__(self) -> None:
        self._flights: dict[str, asyncio.Future[T]] = {}
        self.computed = 0
        self.joined = 0

    def running(self, key: str) -> bool:
        return key in self._flights

    async def run(self, key: str, compute: Callable[[], Awaitable[T]], *, wait_s: float) -> tuple[T, bool]:
        """``compute()`` once for ``key``, or the result of the run already going.

        Returns (result, computed_here). ``compute`` should store anything it wants cached
        before it returns: the flight ends in the same step as it returns, so no caller can
        slip in between and find neither the flight nor the cache entry."""
        while (fut := self._flights.get(key)) is not None:
            try:
                result = await asyncio.wait_for(asyncio.shield(fut), wait_s)
            except _Gone:
                continue  # the computing caller left; the first waiter back takes over
            except TimeoutError:
                if fut.done():
                    raise  # the computation's own error, shared, not this wait running out
                break  # waited long enough: compute here, outside the flight
            self.joined += 1
            return result, False
        else:
            fut = asyncio.get_running_loop().create_future()
            fut.add_done_callback(_retrieve)
            self._flights[key] = fut
            try:
                result = await compute()
            except asyncio.CancelledError:
                fut.set_exception(_Gone())
                raise
            except BaseException as exc:
                fut.set_exception(exc)
                raise
            else:
                fut.set_result(result)
                self.computed += 1
                return result, True
            finally:
                if self._flights.get(key) is fut:
                    del self._flights[key]
                if not fut.done():
                    fut.set_exception(_Gone())
        # Only reached when a waiter gave up on a flight that is still running.
        self.computed += 1
        return await compute(), True
