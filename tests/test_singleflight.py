"""Concurrent requests for the same cached page compute it once.

Measured on the box: after a restart four concurrent ``/misses`` requests each recomputed the
page, holding the analysis lock 28, 7, 5 and 4 s for one answer while a visitor's chat queued
12.5 s behind them. Pinned here: one computation per key, the same answer for everyone, other
keys untouched, and no way for a failure, a timeout or a cancelled caller to leave waiters
hanging or the cache poisoned.
"""

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.api.singleflight import SingleFlight
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


def run(coro):
    return asyncio.run(coro)


def test_concurrent_callers_for_one_key_share_one_computation():
    async def main():
        sf: SingleFlight[int] = SingleFlight()
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.1)
            return 42

        got = await asyncio.gather(*(sf.run("k", compute, wait_s=5) for _ in range(20)))
        assert calls == 1
        assert [r for r, _ in got] == [42] * 20
        assert sum(here for _, here in got) == 1
        assert not sf.running("k") and (sf.computed, sf.joined) == (1, 19)

    run(main())


def test_different_keys_compute_independently_and_at_the_same_time():
    async def main():
        sf: SingleFlight[str] = SingleFlight()
        running = 0
        most = 0

        def compute(key):
            async def go():
                nonlocal running, most
                running += 1
                most = max(most, running)
                await asyncio.sleep(0.1)
                running -= 1
                return key

            return go

        got = await asyncio.gather(*(sf.run(k, compute(k), wait_s=5) for k in ("a", "b", "c", "a", "b", "c")))
        assert [r for r, _ in got] == ["a", "b", "c", "a", "b", "c"]
        assert sf.computed == 3 and most == 3

    run(main())


def test_a_failure_reaches_every_waiter_and_the_next_call_computes_again():
    async def main():
        sf: SingleFlight[int] = SingleFlight()
        calls = 0

        async def boom():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            raise RuntimeError("database is locked")

        got = await asyncio.gather(*(sf.run("k", boom, wait_s=5) for _ in range(5)), return_exceptions=True)
        assert calls == 1
        assert all(isinstance(e, RuntimeError) for e in got)
        assert not sf.running("k")

        async def ok():
            return 7

        assert await sf.run("k", ok, wait_s=5) == (7, True), "the failure did not stick to the key"

    run(main())


def test_a_timeout_raised_by_the_computation_is_shared_not_mistaken_for_a_waiters_timeout():
    async def main():
        sf: SingleFlight[int] = SingleFlight()
        calls = 0

        async def times_out():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            raise TimeoutError("upstream")

        got = await asyncio.gather(*(sf.run("k", times_out, wait_s=5) for _ in range(4)), return_exceptions=True)
        assert calls == 1 and all(isinstance(e, TimeoutError) for e in got)

    run(main())


def test_when_the_computing_caller_is_cancelled_a_waiter_takes_over():
    async def main():
        sf: SingleFlight[str] = SingleFlight()
        calls = 0
        started = asyncio.Event()

        async def compute():
            nonlocal calls
            calls += 1
            started.set()
            await asyncio.sleep(0.2)
            return "done"

        leader = asyncio.create_task(sf.run("k", compute, wait_s=5))
        await started.wait()
        waiters = [asyncio.create_task(sf.run("k", compute, wait_s=5)) for _ in range(3)]
        await asyncio.sleep(0.01)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        got = await asyncio.wait_for(asyncio.gather(*waiters), 5)
        assert [r for r, _ in got] == ["done"] * 3
        assert calls == 2, "the cancelled one, then exactly one of the waiters"
        assert sum(here for _, here in got) == 1
        assert not sf.running("k")

    run(main())


def test_a_cancelled_waiter_does_not_cancel_the_computation():
    async def main():
        sf: SingleFlight[str] = SingleFlight()

        async def compute():
            await asyncio.sleep(0.15)
            return "x"

        leader = asyncio.create_task(sf.run("k", compute, wait_s=5))
        await asyncio.sleep(0.01)
        waiter = asyncio.create_task(sf.run("k", compute, wait_s=5))
        await asyncio.sleep(0.01)
        waiter.cancel()
        assert await leader == ("x", True)

    run(main())


def test_a_waiter_that_waits_too_long_computes_by_itself():
    async def main():
        sf: SingleFlight[str] = SingleFlight()
        gate = asyncio.Event()

        async def stuck():
            await gate.wait()
            return "slow"

        async def quick():
            return "own"

        leader = asyncio.create_task(sf.run("k", stuck, wait_s=5))
        await asyncio.sleep(0.01)
        t0 = time.monotonic()
        assert await asyncio.wait_for(sf.run("k", quick, wait_s=0.1), 5) == ("own", True)
        assert time.monotonic() - t0 < 1
        gate.set()
        assert await leader == ("slow", True)
        assert not sf.running("k")

    run(main())


# --- through the API: the page cache ---------------------------------------------------------------


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False), raise_server_exceptions=False) as c:
        yield c


class SlowListing:
    """Stands in for an expensive page computation: counts calls and how many ran at once."""

    def __init__(self, delay: float = 0.6) -> None:
        self.delay = delay
        self.calls = 0
        self.running = 0
        self.most = 0
        self.fail: BaseException | None = None
        self._mu = threading.Lock()

    def __call__(self, *_a, **_k):
        with self._mu:
            self.calls += 1
            self.running += 1
            self.most = max(self.most, self.running)
            n = self.calls
        try:
            time.sleep(self.delay)
            if self.fail is not None:
                raise self.fail
            return [{"name": f"computed-{n}"}]
        finally:
            with self._mu:
                self.running -= 1


def hammer(client, paths: list[str]):
    start = threading.Barrier(len(paths))
    out: list = [None] * len(paths)

    def one(i: int, p: str) -> None:
        start.wait(5)
        out[i] = client.get(p)

    threads = [threading.Thread(target=one, args=(i, p)) for i, p in enumerate(paths)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


@pytest.fixture
def listing(monkeypatch):
    slow = SlowListing()
    monkeypatch.setattr("nightwatch.journal.anchor.listing", slow)
    return slow


def test_simultaneous_requests_for_an_uncached_page_compute_it_once(client, listing):
    got = hammer(client, ["/anchors"] * 10)
    assert listing.calls == 1, f"one computation for ten requests, not {listing.calls}"
    assert all(r.status_code == 200 for r in got)
    assert len({r.content for r in got}) == 1, "everyone got the same answer"
    assert {r.headers["x-nightwatch-cache"] for r in got} <= {"miss", "joined", "hit"}
    assert sum(r.headers["x-nightwatch-cache"] == "miss" for r in got) == 1
    assert client.get("/anchors").headers["x-nightwatch-cache"] == "hit", "and it is cached as before"
    assert not client.app.state.page_flights.running("/anchors?")


def test_simultaneous_requests_for_an_expired_page_compute_it_once(client, listing, monkeypatch):
    """Expired past the point a stale copy may be shown: every caller has to wait for a recompute."""
    client.get("/anchors")
    assert listing.calls == 1
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_TTL_S", 0.0)
    monkeypatch.setattr("nightwatch.api.app.PAGE_CACHE_STALE_S", 0.0)
    got = hammer(client, ["/anchors"] * 8)
    assert listing.calls == 2, f"one recompute for eight requests, not {listing.calls - 1}"
    assert len({r.content for r in got}) == 1 and b"computed-2" in got[0].content


def test_different_pages_still_compute_side_by_side(client, listing):
    got = hammer(client, ["/anchors?limit=1", "/anchors?limit=2", "/anchors?limit=1", "/anchors?limit=2"])
    assert all(r.status_code == 200 for r in got)
    assert listing.calls == 2 and listing.most == 2, "two keys, two computations, at the same time"


def test_a_failed_computation_answers_every_waiter_and_is_not_cached(client, listing):
    listing.fail = HTTPException(status_code=503, detail="The desk is busy.")
    got = hammer(client, ["/anchors"] * 6)
    assert listing.calls == 1
    assert [r.status_code for r in got] == [503] * 6
    assert all(r.json() == {"detail": "The desk is busy."} for r in got)
    assert "x-nightwatch-cache" not in got[0].headers
    assert all(r.headers["content-type"] == "application/json" for r in got), "the route's own headers, for everyone"
    listing.fail = None
    again = client.get("/anchors")
    assert again.status_code == 200 and again.headers["x-nightwatch-cache"] == "miss", "the failure was not cached"
    assert listing.calls == 2


def test_a_crashing_computation_releases_every_waiter_and_the_next_request_recovers(client, listing):
    listing.fail = RuntimeError("database disk image is malformed")
    got = hammer(client, ["/anchors"] * 6)
    assert listing.calls == 1
    assert [r.status_code for r in got] == [500] * 6
    assert not client.app.state.page_flights.running("/anchors?")
    listing.fail = None
    assert client.get("/anchors").status_code == 200 and listing.calls == 2


def test_uncacheable_requests_are_not_coalesced(client, listing):
    got = hammer(client, ["/anchors?junk=1"] * 3)
    assert all(r.status_code == 200 and r.headers["x-nightwatch-cache"] == "miss" for r in got)
    assert listing.calls == 3, "a request the cache never keeps behaves exactly as before"


def test_the_visitor_id_does_not_split_the_flight(client, listing):
    got = hammer(client, ["/anchors?nw_v=a", "/anchors?nw_v=b", "/anchors?nw_lang=zh", "/anchors"])
    assert listing.calls == 1 and len({r.content for r in got}) == 1
