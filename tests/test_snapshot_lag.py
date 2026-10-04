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
