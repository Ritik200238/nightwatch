"""A finished analysis is journaled - forecast, receipt and saved report - whatever other threads are reading.

The journal wrote on the API's one shared SQLite connection. While another thread is part-way
through a read on that connection (a page, a health check, the warm-up) and the recorder has
committed since that read began, SQLite refuses a write on it at once with SQLITE_BUSY_SNAPSHOT
("database is locked") instead of waiting. Every post-analysis write swallows its error ("a
keepsake must never fail an analysis"), so the visitor saw a verdict that was never recorded:
no forecast row, no receipt, no saved report to reopen. The same failure ended streamed chats
before their analysis (tests/test_chat_claim_connection.py).

The forecast and its receipt are also written in one real transaction now. On an autocommit
connection ``with conn:`` opens none, so the two inserts were committed separately and a
failure between them left a forecast with no receipt until the next restart chained it.
"""

import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.journal import receipts
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

TICKET = {
    "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
    "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat(), "record": True,
}


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def fresh(path) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=10, isolation_level=None)


def recorder_commits(path) -> None:
    rec = fresh(path)
    try:
        rec.execute("CREATE TABLE IF NOT EXISTS recorder_tick (n INTEGER)")
        rec.execute("INSERT INTO recorder_tick VALUES (1)")
    finally:
        rec.close()


def persisted(path, forecast_id: int | None) -> dict[str, bool]:
    """What a fresh connection finds for this forecast: the row, its receipt, its saved report."""
    c = fresh(path)
    try:
        fid = int(forecast_id or -1)
        return {
            "forecast": c.execute("SELECT 1 FROM forecasts WHERE id=?", (fid,)).fetchone() is not None,
            "receipt": c.execute("SELECT 1 FROM receipts WHERE forecast_id=?", (fid,)).fetchone() is not None,
            "report": c.execute("SELECT 1 FROM reports WHERE forecast_id=?", (fid,)).fetchone() is not None,
        }
    finally:
        c.close()


def test_an_analysis_is_journaled_while_another_read_is_open_on_the_shared_connection(client):
    store = client.app.state.nw.store
    reading = store._conn.execute("SELECT ts FROM bars")
    assert reading.fetchone() is not None
    recorder_commits(store.path)
    try:
        r = client.post("/analyze", json=TICKET)
    finally:
        reading.fetchall()
    assert r.status_code == 200
    fid = r.json().get("forecast_id")
    assert fid, "the analysis was shown but never journaled"
    assert persisted(store.path, fid) == {"forecast": True, "receipt": True, "report": True}
    assert r.json().get("receipt"), "the report carries its receipt"


def test_under_concurrent_reads_and_recorder_writes_every_analysis_is_persisted(client):
    """Load like the box's: a thread reading the shared connection row by row, the recorder
    committing every few milliseconds, and analyses one after another. Every one of them must
    land, with its receipt and its saved report, and the chain must verify."""
    store = client.app.state.nw.store
    stop = threading.Event()
    errors: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                cur = store._conn.execute("SELECT ts FROM bars")
                while cur.fetchone() is not None and not stop.is_set():
                    time.sleep(0.0005)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"reader: {exc}")

    def recorder() -> None:
        rec = fresh(store.path)
        rec.execute("CREATE TABLE IF NOT EXISTS recorder_tick (n INTEGER)")
        while not stop.is_set():
            try:
                rec.execute("INSERT INTO recorder_tick VALUES (1)")
            except sqlite3.OperationalError as exc:
                errors.append(f"recorder: {exc}")
            time.sleep(0.003)
        rec.close()

    threads = [threading.Thread(target=reader), threading.Thread(target=recorder)]
    for t in threads:
        t.start()
    ids: list[int | None] = []
    try:
        time.sleep(0.05)
        for _ in range(6):
            r = client.post("/analyze", json=TICKET)
            assert r.status_code == 200
            ids.append(r.json().get("forecast_id"))
    finally:
        stop.set()
        for t in threads:
            t.join(10)
    assert not [e for e in errors if "recorder" in e], errors
    assert all(ids), f"analyses shown but not journaled: {ids}"
    assert [persisted(store.path, i) for i in ids] == [{"forecast": True, "receipt": True, "report": True}] * len(ids)
    c = fresh(store.path)
    try:
        v = receipts.verify(c)
    finally:
        c.close()
    assert v["ok"] and v["first_break"] is None


def test_a_forecast_and_its_receipt_commit_together_or_not_at_all(client, monkeypatch):
    store = client.app.state.nw.store
    before = persisted_count(store.path)

    def broken_append(conn, forecast_id):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(receipts, "append", broken_append)
    r = client.post("/analyze", json=TICKET)
    assert r.status_code == 200 and r.json().get("forecast_id") is None
    assert persisted_count(store.path) == before, "no forecast was left behind without its receipt"


def persisted_count(path) -> int:
    c = fresh(path)
    try:
        return int(c.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0])
    finally:
        c.close()

