"""A chat's request-id claim must not fail because another thread is mid-read on the shared connection.

What happened on the box (11 Oct, the smoke run after deploying 5616caf): two "5x TSLA overnight"
chats, two minutes apart, got a 200 event stream from the API and then no report. The backend
kept no timing line for them (a request is logged only when it took the analysis lock or ran
3 s), the journal has no forecast for them, and the browser never fell back to plain /chat.
That is the shape of a stream that ended at once with an error event, before the analysis.

The cause this pins: every streamed chat first writes its request-id claim, and it wrote it on
the API's one shared SQLite connection. When another thread is part-way through a read on that
connection (the page computations and the analyses read it for seconds) and the recorder has
committed since that read began, SQLite refuses the write at once - SQLITE_BUSY_SNAPSHOT,
"database is locked" - without waiting for the busy timeout, because waiting cannot help. The
claim now has a connection of its own.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.journal import idempotency as idem
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

TRADE = {"messages": [{"role": "user", "content": "long 40000 TSLA overnight, account 50k"}]}


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def recorder_commits(path) -> None:
    """What the recorder does every minute: a write committed from its own connection."""
    rec = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        rec.execute("CREATE TABLE IF NOT EXISTS recorder_tick (n INTEGER)")
        rec.execute("INSERT INTO recorder_tick VALUES (1)")
    finally:
        rec.close()


def test_sqlite_refuses_a_write_inside_a_stale_read_at_once():
    """The mechanism, on its own: no busy wait, an immediate 'database is locked'."""
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "t.sqlite"
    shared = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    shared.execute("PRAGMA journal_mode=WAL")
    shared.execute("CREATE TABLE big (x)")
    shared.executemany("INSERT INTO big VALUES (?)", [(i,) for i in range(100)])
    reading = shared.execute("SELECT x FROM big")
    reading.fetchone()
    recorder_commits(path)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        shared.execute("INSERT INTO big VALUES (-1)")
    reading.fetchall()
    shared.close()


@pytest.fixture
def open_read_on_the_shared_connection(client, monkeypatch):
    """Another thread is part-way through a long read on the shared connection, and the
    recorder has committed since it began, at the moment the chat writes its claim. The read
    finishes right after the claim, so the rest of the turn runs as it would on the box."""
    store = client.app.state.nw.store
    reading = store._conn.execute("SELECT ts FROM bars")
    assert reading.fetchone() is not None
    recorder_commits(store.path)
    real = idem.claim

    def claim_during_the_read(conn, rid, **kw):
        try:
            return real(conn, rid, **kw)
        finally:
            reading.fetchall()

    monkeypatch.setattr(idem, "claim", claim_during_the_read)
    yield
    reading.fetchall()


def test_a_streamed_chat_is_answered_while_another_read_is_open(client, open_read_on_the_shared_connection):
    r = client.post("/chat/stream", json={**TRADE, "request_id": "send-snapshot-0001"})
    assert r.status_code == 200
    assert "event: error" not in r.text, f"the claim failed on the shared connection: {r.text[-300:]}"
    assert "event: done" in r.text and '"forecast_id"' in r.text


def test_a_plain_chat_is_answered_while_another_read_is_open(client, open_read_on_the_shared_connection):
    r = client.post("/chat", json={**TRADE, "request_id": "send-snapshot-0002"})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["report"]["forecast_id"] > 0


class NoClaims:
    """The shared connection, refusing any statement on the request-id table."""

    def __init__(self, real):
        self._real = real
        self.refused = 0

    def execute(self, sql, *a, **k):
        if "chat_requests" in sql:
            self.refused += 1
            raise AssertionError(f"request-id bookkeeping ran on the shared connection: {sql[:60]}")
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


def test_claim_finish_and_replay_never_touch_the_shared_connection(client):
    store = client.app.state.nw.store
    guard = NoClaims(store._live)
    store._live = guard
    try:
        first = client.post("/chat", json={**TRADE, "request_id": "send-snapshot-0003"})
        again = client.post("/chat", json={**TRADE, "request_id": "send-snapshot-0003"})
    finally:
        store._live = guard._real
    assert guard.refused == 0
    assert first.status_code == again.status_code == 200
    assert again.json().get("replayed") is True
    assert again.json()["report"]["forecast_id"] == first.json()["report"]["forecast_id"]
