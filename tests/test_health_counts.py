"""``/health`` reports row counts it never counts on a request.

Measured on the box before this: at every 600 s boundary the caller that found the counts
expired waited 17-22 s for two table scans, and every caller arriving meanwhile ran its own.
Pinned here: callers never wait for a recount once there are counts, only one recount runs at a
time, a failed recount keeps the last good counts, and a restart starts from the saved ones.
"""

import json
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.api.health_counts import HealthCounts
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

T0 = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.m = 1000.0
        self.w = T0

    def mono(self) -> float:
        return self.m

    def wall(self) -> datetime:
        return self.w

    def advance(self, s: float) -> None:
        self.m += s
        self.w += timedelta(seconds=s)


class Counter:
    """A count that can be held open, made to fail, and tells how many ran at once."""

    def __init__(self, bars: int = 1000, books: int = 50) -> None:
        self.value = (bars, books)
        self.calls = 0
        self.running = 0
        self.most_at_once = 0
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.fail: Exception | None = None
        self._mu = threading.Lock()

    def __call__(self) -> tuple[int, int]:
        with self._mu:
            self.calls += 1
            self.running += 1
            self.most_at_once = max(self.most_at_once, self.running)
        self.entered.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(10)
            if self.fail is not None:
                raise self.fail
            return self.value
        finally:
            with self._mu:
                self.running -= 1


def settle(hc: HealthCounts, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not hc.read(first_wait_s=0)["refreshing"]:
            return
        time.sleep(0.01)
    raise AssertionError("the recount never finished")


def make(counter: Counter, clock: Clock, saved=None, **kw) -> HealthCounts:
    return HealthCounts(counter, saved=saved, clock=clock.mono, wall=clock.wall, **kw)


def test_first_read_waits_for_the_first_count_then_reports_it_fresh():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock)
    got = hc.read(first_wait_s=5)
    assert (got["bars"], got["books"], got["state"]) == (1000, 50, "fresh")
    assert got["at"] == T0.isoformat() and got["age_s"] == 0 and got["failures"] == 0


def test_a_count_due_is_served_from_the_last_one_while_one_recount_runs():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock, ttl_s=600)
    hc.read(first_wait_s=5)
    settle(hc)
    clock.advance(601)
    counter.value = (2000, 80)
    counter.gate = threading.Event()
    counter.entered.clear()
    t0 = time.monotonic()
    got = hc.read()
    assert time.monotonic() - t0 < 0.5, "the caller does not wait for the recount"
    assert (got["bars"], got["state"], got["refreshing"]) == (1000, "stale", True)
    assert counter.entered.wait(5)
    counter.gate.set()
    settle(hc)
    got = hc.read()
    assert (got["bars"], got["books"], got["state"]) == (2000, 80, "fresh")


def test_many_callers_at_the_boundary_start_exactly_one_recount():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock)
    hc.read(first_wait_s=5)
    settle(hc)
    clock.advance(601)
    counter.gate = threading.Event()
    start = threading.Barrier(16)
    answers: list[int] = []

    def caller() -> None:
        start.wait(5)
        answers.append(hc.read()["bars"])

    threads = [threading.Thread(target=caller) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    counter.gate.set()
    settle(hc)
    assert answers == [1000] * 16
    assert counter.calls == 2, "the first count and one recount, however many callers"
    assert counter.most_at_once == 1


def test_counts_inside_the_ttl_are_not_recounted():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock)
    hc.read(first_wait_s=5)
    settle(hc)
    for _ in range(5):
        clock.advance(100)
        hc.read()
    assert counter.calls == 1
    clock.advance(101)
    hc.read()
    settle(hc)
    assert counter.calls == 2


def test_a_failed_recount_keeps_the_last_good_counts_and_backs_off_then_recovers():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock, ttl_s=600, retry_s=60)
    hc.read(first_wait_s=5)
    settle(hc)
    clock.advance(601)
    counter.fail = RuntimeError("disk I/O error")
    hc.read()
    settle(hc)
    got = hc.read()
    assert (got["bars"], got["books"], got["state"], got["failures"]) == (1000, 50, "stale", 1)
    assert got["at"] == T0.isoformat(), "the failure did not touch the last good counts"
    calls = counter.calls
    clock.advance(30)
    hc.read()
    assert counter.calls == calls, "no rescan back to back after a failure"
    clock.advance(31)
    counter.fail = None
    counter.value = (3000, 90)
    hc.read()
    settle(hc)
    got = hc.read()
    assert (got["bars"], got["state"], got["failures"]) == (3000, "fresh", 0)


@pytest.mark.parametrize("bad", [ValueError("x"), TypeError("y")])
def test_a_first_count_that_fails_answers_without_counts_instead_of_raising(bad):
    clock, counter = Clock(), Counter()
    counter.fail = bad
    hc = make(counter, clock)
    got = hc.read(first_wait_s=5)
    assert (got["bars"], got["books"], got["state"], got["at"]) == (0, 0, "unavailable", None)


def test_garbage_from_the_count_is_a_failure_not_new_counts():
    clock, counter = Clock(), Counter()
    hc = make(counter, clock)
    hc.read(first_wait_s=5)
    settle(hc)
    clock.advance(601)
    counter.value = (-1, 5)
    hc.read()
    settle(hc)
    assert hc.read()["bars"] == 1000 and hc.failures == 1


def test_a_slow_first_count_returns_after_the_bound_marked_counting():
    clock, counter = Clock(), Counter()
    counter.gate = threading.Event()
    hc = make(counter, clock)
    t0 = time.monotonic()
    got = hc.read(first_wait_s=0.2)
    assert time.monotonic() - t0 < 2
    assert (got["bars"], got["state"], got["refreshing"]) == (0, "counting", True)
    counter.gate.set()
    settle(hc)
    assert hc.read()["bars"] == 1000


def test_a_restart_starts_from_the_saved_counts_and_recounts(tmp_path):
    saved = tmp_path / "health_counts.json"
    clock, counter = Clock(), Counter()
    hc = make(counter, clock, saved=saved)
    hc.read(first_wait_s=5)
    settle(hc)
    assert json.loads(saved.read_text()) == {"bars": 1000, "books": 50, "at": T0.isoformat()}

    clock.advance(3600)  # the next process, an hour on
    counter2 = Counter(4000, 70)
    counter2.gate = threading.Event()
    hc2 = make(counter2, clock, saved=saved)
    t0 = time.monotonic()
    got = hc2.read()
    assert time.monotonic() - t0 < 0.5, "the saved counts answer at once"
    assert (got["bars"], got["state"], got["age_s"]) == (1000, "stale", 3600)
    counter2.gate.set()
    settle(hc2)
    assert hc2.read()["bars"] == 4000 and hc2.read()["state"] == "fresh"


@pytest.mark.parametrize("content", ["not json", '{"bars": 1}', '{"bars": -5, "books": 1, "at": "2026-10-10T20:00:00+00:00"}', '{"bars": 5, "books": 1, "at": "2026-10-10T20:00:00"}'])
def test_a_damaged_saved_file_is_ignored(tmp_path, content):
    saved = tmp_path / "health_counts.json"
    saved.write_text(content)
    clock, counter = Clock(), Counter()
    hc = make(counter, clock, saved=saved)
    assert hc.read(first_wait_s=5)["bars"] == 1000


def test_an_unwritable_save_does_not_fail_the_count(tmp_path):
    saved = tmp_path / "missing-dir" / "health_counts.json"
    clock, counter = Clock(), Counter()
    hc = make(counter, clock, saved=saved)
    assert hc.read(first_wait_s=5)["state"] == "fresh"


# --- through the API -----------------------------------------------------------------------------


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def test_health_keeps_its_contract_and_says_how_old_the_counts_are(client):
    h = client.get("/health").json()
    assert h["ok"] is True and isinstance(h["bars"], int) and h["bars"] > 0 and isinstance(h["orderbook_snapshots"], int)
    assert h["counts"]["state"] == "fresh" and h["counts"]["age_s"] is not None
    assert set(h["counts"]) == {"state", "at", "age_s", "refreshing", "failures"}


def test_health_answers_at_once_while_a_recount_is_stuck(client):
    s = client.app.state.nw
    client.get("/health")
    gate = threading.Event()
    real = s.health_counts._count

    def slow():
        assert gate.wait(10)
        return real()

    s.health_counts._count = slow
    s.health_counts._counted_m -= 601  # due
    try:
        t0 = time.monotonic()
        for _ in range(5):
            h = client.get("/health").json()
            assert h["bars"] > 0 and h["counts"]["state"] == "stale"
        assert time.monotonic() - t0 < 3, "five health checks during a stuck recount, none waited for it"
        assert h["counts"]["refreshing"] is True
    finally:
        gate.set()
    settle(s.health_counts)
    assert client.get("/health").json()["counts"]["state"] == "fresh"


def test_a_broken_database_count_does_not_break_health(client):
    s = client.app.state.nw
    client.get("/health")

    def broken():
        raise RuntimeError("database disk image is malformed")

    s.health_counts._count = broken
    s.health_counts._counted_m -= 601
    client.get("/health")
    settle(s.health_counts)
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["ok"] and h.json()["bars"] > 0 and h.json()["counts"]["failures"] == 1
