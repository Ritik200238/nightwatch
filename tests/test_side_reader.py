"""Whole-table scans must not run on the shared connection.

Measured on the box: ``/health`` took 17-40 s every ten minutes (exactly when it recounted its
tables) and analyses stalled for as long as a ``/sources`` recompute (21-26 s) ran, because the
one shared SQLite connection runs one statement at a time. These pages now count on a reader of
their own.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


class NoScans:
    """The shared connection, refusing any whole-table count."""

    def __init__(self, real):
        self._real = real
        self.refused = 0

    def execute(self, sql, *a, **k):
        if "COUNT(" in sql.upper():
            self.refused += 1
            raise AssertionError(f"a whole-table scan ran on the shared connection: {sql[:70]}")
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def test_health_counts_and_sources_scans_stay_off_the_shared_connection(client):
    store = client.app.state.nw.store
    guard = NoScans(store._live)
    store._live = guard
    try:
        h = client.get("/health")
        assert h.status_code == 200 and h.json()["ok"] and h.json()["bars"] > 0
        s = client.get("/sources")
        assert s.status_code == 200 and {r["key"] for r in s.json()} >= {"bitget_bars", "yahoo", "nasdaq"}
    finally:
        store._live = guard._real
    assert guard.refused == 0


def test_the_counts_are_the_tables_real_counts(client):
    store = client.app.state.nw.store
    bars = store._conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    books = store._conn.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0]
    h = client.get("/health").json()
    assert (h["bars"], h["orderbook_snapshots"]) == (bars, books)
    rows = {r["key"]: r for r in client.get("/sources").json()}
    non_yahoo = store._conn.execute("SELECT COUNT(*) FROM bars WHERE venue<>'yahoo'").fetchone()[0]
    assert rows["bitget_bars"]["rows"] == non_yahoo


def test_a_busy_shared_connection_does_not_hold_the_pages_up(client):
    """The shared connection is mid-statement for a long time; /health and /sources still answer."""
    store = client.app.state.nw.store
    gate = threading.Event()

    class Busy(NoScans):
        def execute(self, sql, *a, **k):
            if "FROM bars WHERE ts" in sql:  # a stand-in for a long analysis read
                gate.wait(10)
            return super().execute(sql, *a, **k)

    busy = Busy(store._live)
    store._live = busy
    started = threading.Event()

    def long_read():
        started.set()
        busy.execute("SELECT 1 FROM bars WHERE ts > 0 LIMIT 1")

    t = threading.Thread(target=long_read)
    t.start()
    started.wait(2)
    try:
        t0 = time.monotonic()
        assert client.get("/health").status_code == 200
        assert client.get("/sources").status_code == 200
        assert time.monotonic() - t0 < 5
    finally:
        gate.set()
        t.join(5)
        store._live = busy._real


def test_the_side_reader_is_read_only_and_closed_after_use(client):
    store = client.app.state.nw.store
    with store.side_reader() as c:
        assert c.execute("SELECT COUNT(*) FROM bars").fetchone()[0] > 0
        with pytest.raises(Exception, match="readonly|read-only|attempt to write"):
            c.execute("DELETE FROM bars")
    with pytest.raises(Exception, match="closed"):
        c.execute("SELECT 1")
