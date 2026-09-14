"""Keeping a finished report so it can be looked at again, and linked to.

A verdict is an argument, and an argument you cannot show someone is worth less. The
journal already records what the desk predicted and what happened; this keeps the whole
report that went with it, so a link reopens the exact page: the same analogs, the same
stress table, the same book, the same caps, the same hash of the inputs.

It is deliberately small. Only live tickets are kept, never the thousands of replays,
and only the most recent few hundred of those: this is a demo box with a 38 GB disk, and
a report that nobody has opened in a month is not worth the space. Bodies are stored
compressed because they are mostly repeated JSON keys and compress about five to one.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from typing import Any

from nightwatch.data.store import Store
from nightwatch.time_utils import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    forecast_id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    body BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_created ON reports (created_at);
"""

KEEP = 500


class ReportStore:
    def __init__(self, store: Store):
        self._conn: sqlite3.Connection = store._conn
        self._conn.executescript(SCHEMA)

    def save(self, forecast_id: int, report: dict[str, Any], *, keep: int = KEEP) -> None:
        body = zlib.compress(json.dumps(report, default=str).encode("utf-8"), 6)
        with self._conn:
            self._conn.execute(
                "INSERT INTO reports (forecast_id, created_at, body) VALUES (?,?,?) "
                "ON CONFLICT(forecast_id) DO UPDATE SET created_at=excluded.created_at, body=excluded.body",
                (int(forecast_id), int(utc_now().timestamp() * 1000), body),
            )
            self._conn.execute(
                "DELETE FROM reports WHERE forecast_id NOT IN "
                "(SELECT forecast_id FROM reports ORDER BY created_at DESC LIMIT ?)",
                (int(keep),),
            )

    def get(self, forecast_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT body FROM reports WHERE forecast_id=?", (int(forecast_id),)).fetchone()
        if row is None:
            return None
        return json.loads(zlib.decompress(row[0]).decode("utf-8"))

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0])
