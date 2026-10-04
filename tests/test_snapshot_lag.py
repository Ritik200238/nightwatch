"""The API reads through one shared autocommit connection. An unfinished cursor on it
pins the read snapshot, and every later query sees the database as it was then. The
health check must notice and say so, so the box restarts the API."""

from __future__ import annotations

import sqlite3

from nightwatch.data.store import Store


def _book(conn: sqlite3.Connection, ts: int) -> None:
    conn.execute(
        "INSERT INTO orderbook_snapshots (venue, symbol, ts, observed_at, levels) VALUES ('spot', 'RNVDAUSDT', ?, ?, '[]')",
        (ts, ts),
    )


def test_a_pinned_cursor_freezes_the_shared_view_and_the_lag_shows_it(tmp_path):
    store = Store(tmp_path / "nw.sqlite")
    _book(store._conn, 1_000)
    _book(store._conn, 2_000)
    assert store.snapshot_lag_seconds() == 0.0

    stuck = store._conn.execute("SELECT ts FROM orderbook_snapshots ORDER BY ts")
    stuck.fetchone()  # one row read, one left: the statement stays open

    writer = sqlite3.connect(store.path, isolation_level=None)
    _book(writer, 2_000 + 900_000)  # the recorder writes 15 minutes later
    writer.close()

    assert store.snapshot_lag_seconds() == 900.0
    stuck.close()
    assert store.snapshot_lag_seconds() == 0.0


def _pin_and_write(store: Store, minutes: int) -> sqlite3.Cursor:
    _book(store._conn, 1_000)
    _book(store._conn, 2_000)
    stuck = store._conn.execute("SELECT ts FROM orderbook_snapshots ORDER BY ts")
    stuck.fetchone()
    writer = sqlite3.connect(store.path, isolation_level=None)
    _book(writer, 2_000 + minutes * 60_000)
    writer.close()
    return stuck


def test_reconnect_gives_every_reader_the_fresh_view(tmp_path):
    from nightwatch.journal.journal import Journal
    from nightwatch.journal.reports import ReportStore

    store = Store(tmp_path / "nw.sqlite")
    journal, reports = Journal(store), ReportStore(store)
    stuck = _pin_and_write(store, 15)
    assert store.snapshot_lag_seconds() == 900.0

    store.reconnect()
    assert store.snapshot_lag_seconds() == 0.0
    # Objects built before the swap read through the new connection too.
    assert journal._conn is store._conn and reports._conn is store._conn
    # The cursor that pinned the old one still finishes its read: nothing is closed under it.
    assert stuck.fetchone() == (2_000,)
    assert store.close_retired(grace_s=0.0) == 1
    store.close()


def test_the_api_watchdog_repairs_a_stuck_snapshot_and_counts_it(tmp_path, monkeypatch):
    from nightwatch.api import app as app_mod

    store = Store(tmp_path / "nw.sqlite")
    state = app_mod.AppState.__new__(app_mod.AppState)  # only what check_snapshot touches
    state.store, state.snapshot_heals = store, 0
    held = _pin_and_write(store, 2)  # kept: a dropped cursor would release the snapshot
    assert state.check_snapshot() is False  # two minutes behind: inside the allowance
    held.close()
    state.store.close()

    store = Store(tmp_path / "nw2.sqlite")
    state.store = store
    held = _pin_and_write(store, 15)
    assert state.check_snapshot() is True
    assert state.snapshot_heals == 1 and store.snapshot_lag_seconds() == 0.0
    assert state.check_snapshot() is False
    held.close()
    store.close()
