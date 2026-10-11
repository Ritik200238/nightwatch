"""Every write a visitor's action makes survives other threads reading the shared connection.

The API shares one SQLite connection between threads. A write on it runs inside whatever read
another thread has open there, and when the recorder has committed since that read began SQLite
refuses the write at once - SQLITE_BUSY_SNAPSHOT, "database is locked" - without waiting. The
journal and the chat's request claim were moved off it (tests/test_journal_write_connection.py,
tests/test_chat_claim_connection.py). These are the rest: marking a trade taken, feedback, a
watch, a tripwire, a plan, the usage counts, and maturing forecasts for the record pages.

They also run as one transaction each now. The checks they make before inserting (one pending
watch per report, one armed tripwire per line, the per-visitor limits) and the inserts themselves
were separate autocommit statements, so two requests at once could both pass the check, and a
plan that armed several tripwires could be left half written.
"""

import sqlite3
import threading
from datetime import timedelta

import pytest

from nightwatch.data.models import Bar, Interval, Venue
from nightwatch.data.store import Store
from nightwatch.journal import plans, tripwires
from nightwatch.journal.journal import Journal
from tests import test_api
from tests.test_api import AS_OF
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client

ME = {"x-nw-client": "writer-test-0001"}
PAYLOAD = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
           "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat()}


def fresh(path) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=10, isolation_level=None)


def recorder_commits(path) -> None:
    rec = fresh(path)
    try:
        rec.execute("CREATE TABLE IF NOT EXISTS recorder_tick (n INTEGER)")
        rec.execute("INSERT INTO recorder_tick VALUES (1)")
    finally:
        rec.close()


def count(path, sql, *args) -> int:
    c = fresh(path)
    try:
        return int(c.execute(sql, args).fetchone()[0])
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _clean(client):
    conn = client.app.state.nw.store._conn
    for t in ("feedback", "verdict_marks", "chat_counts", "watches", "tripwires", "plans"):
        conn.execute(f"DELETE FROM {t}")
    yield


@pytest.fixture
def fid(client) -> int:
    r = client.post("/analyze", json=PAYLOAD, headers=ME)
    assert r.status_code == 200
    return r.json()["forecast_id"]


class OpenRead:
    """Another thread part-way through a read on the shared connection, the recorder having
    committed since it began: the condition in which a shared-connection write is refused."""

    def __init__(self, client) -> None:
        self.store = client.app.state.nw.store

    def __enter__(self):
        recorder_commits(self.store.path)  # the recorder's table exists before the read begins
        self.reading = self.store._conn.execute("SELECT ts FROM bars")
        assert self.reading.fetchone() is not None
        recorder_commits(self.store.path)
        return self

    def __exit__(self, *exc):
        self.reading.fetchall()


def test_the_condition_really_refuses_a_shared_connection_write(client):
    """Guard for the tests below: without this, they would prove nothing."""
    store = client.app.state.nw.store
    with OpenRead(client), pytest.raises(sqlite3.OperationalError, match="locked"):
        store._conn.execute("INSERT INTO recorder_tick VALUES (2)")


def test_marking_a_trade_taken_lands_while_another_read_is_open(client, fid):
    path = client.app.state.nw.store.path
    with OpenRead(client):
        r = client.post(f"/forecasts/{fid}/taken", headers=ME)
    assert r.status_code == 200 and r.json() == {"forecast_id": fid, "taken": True}
    assert count(path, "SELECT taken FROM forecasts WHERE id=?", fid) == 1


def test_feedback_lands_while_another_read_is_open(client, fid):
    path = client.app.state.nw.store.path
    with OpenRead(client):
        r = client.post("/feedback", json={"forecast_id": fid, "useful": True}, headers=ME)
    assert r.status_code == 200
    assert count(path, "SELECT COUNT(*) FROM feedback WHERE forecast_id=?", fid) == 1
    assert client.post("/feedback", json={"forecast_id": fid, "useful": False}, headers=ME).status_code == 409, "still once per report"


def test_a_watch_lands_while_another_read_is_open(client, fid):
    path = client.app.state.nw.store.path
    with OpenRead(client):
        r = client.post("/watch", json={"forecast_id": fid}, headers=ME)
    assert r.status_code == 200 and r.json()["id"]
    assert count(path, "SELECT COUNT(*) FROM watches WHERE forecast_id=?", fid) == 1


def _level(client, fid) -> float:
    s = client.get(f"/tripwire/suggest/{fid}").json()["suggestions"]
    assert s
    return float(s[0]["level"])


def test_a_tripwire_lands_while_another_read_is_open(client, fid):
    path = client.app.state.nw.store.path
    level = _level(client, fid)
    with OpenRead(client):
        r = client.post("/tripwire", json={"forecast_id": fid, "level": level}, headers=ME)
    assert r.status_code == 200 and r.json()["id"]
    assert count(path, "SELECT COUNT(*) FROM tripwires WHERE forecast_id=?", fid) == 1


def test_a_plan_with_its_tripwires_lands_while_another_read_is_open(client, fid):
    path = client.app.state.nw.store.path
    keys = [s["key"] for s in client.get(f"/plan/{fid}", headers=ME).json()["scenarios"]]
    with OpenRead(client):
        r = client.post("/plan", json={"forecast_id": fid, "choices": {keys[0]: "cut_half"}, "arm": True}, headers=ME)
    assert r.status_code == 200, r.text[:200]
    assert count(path, "SELECT COUNT(*) FROM plans WHERE forecast_id=?", fid) == 1
    assert count(path, "SELECT COUNT(*) FROM tripwires WHERE forecast_id=?", fid) == 1


def test_the_verdict_count_lands_while_another_read_is_open(client):
    store = client.app.state.nw.store
    reading = store._conn.execute("SELECT ts FROM bars")
    reading.fetchone()
    recorder_commits(store.path)

    # The read stays open through the analysis's own writes (they have connections of their own)
    # and is still open when the visit is counted.
    try:
        r = client.post("/analyze", json=PAYLOAD, headers=ME)
    finally:
        reading.fetchall()
    assert r.status_code == 200
    fid = r.json()["forecast_id"]
    assert count(store.path, "SELECT COUNT(*) FROM verdict_marks WHERE forecast_id=?", fid) == 1, "the visit was counted"


def test_a_plan_is_saved_whole_or_not_at_all(client, fid, monkeypatch):
    """A plan arms one tripwire per chosen line. A failure part-way must not leave the first
    line saved and the rest missing."""
    path = client.app.state.nw.store.path
    keys = [s["key"] for s in client.get(f"/plan/{fid}", headers=ME).json()["scenarios"]]
    assert len(keys) >= 2
    real = tripwires.create
    calls = {"n": 0}

    def second_one_breaks(conn, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return real(conn, **kw)

    monkeypatch.setattr(plans.tripwires, "create", second_one_breaks)
    with pytest.raises(sqlite3.OperationalError):
        client.post("/plan", json={"forecast_id": fid, "choices": {keys[0]: "cut_half", keys[1]: "exit"}, "arm": True}, headers=ME)
    assert count(path, "SELECT COUNT(*) FROM plans WHERE forecast_id=?", fid) == 0
    assert count(path, "SELECT COUNT(*) FROM tripwires WHERE forecast_id=?", fid) == 0


def test_the_same_tripwire_asked_for_at_once_is_armed_once(client, fid):
    """Five requests (the endpoint's burst) for the same line at the same moment: one tripwire, five answers naming it."""
    path = client.app.state.nw.store.path
    level = _level(client, fid)
    start = threading.Barrier(5)
    ids: list[str] = []
    mu = threading.Lock()

    def ask() -> None:
        start.wait(5)
        r = client.post("/tripwire", json={"forecast_id": fid, "level": level}, headers=ME)
        with mu:
            ids.append(r.json().get("id") if r.status_code == 200 else f"HTTP {r.status_code}")

    threads = [threading.Thread(target=ask) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(set(ids)) == 1 and not ids[0].startswith("HTTP"), ids
    assert count(path, "SELECT COUNT(*) FROM tripwires WHERE forecast_id=? AND status='armed'", fid) == 1


# --- maturing forecasts (the record pages and the recorder both do it) ------------------------------

T0 = AS_OF - timedelta(days=60)


def _store_with_a_due_forecast(tmp_path) -> tuple[Store, Journal]:
    s = Store(tmp_path / "m.sqlite")
    s.upsert_bars([
        Bar(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", interval=Interval.H1, ts=T0 + timedelta(hours=i), open=100.0, high=101.0, low=99.0, close=100.0 + i * 0.1, observed_at=T0)
        for i in range(80)
    ])
    j = Journal(s)
    j.record_forecast(kind="ticket", ticker="TSLA", side="long", notional=1000, as_of=T0 + timedelta(hours=2), bar_ts=T0 + timedelta(hours=1), horizon_h=24,
                      entry_price=100.2, snapshot_hash="h", analog_n=40, analog_scope="same_ticker",
                      quantiles={"p5": -2.0, "p25": -1.0, "p50": 0.0, "p75": 1.0, "p95": 2.0}, es5=None, mc_p5=None, mc_p95=None, verdict="GO",
                      recommended_notional=1000, payload={})
    from nightwatch.journal.postmortem import LessonBook

    LessonBook(j)  # its table exists from start-up on, as the API makes it (AppState)
    return s, j


def test_maturing_lands_while_another_read_is_open(tmp_path):
    from nightwatch.journal.postmortem import mature_and_learn

    s, j = _store_with_a_due_forecast(tmp_path)
    try:
        reading = s._conn.execute("SELECT ts FROM bars")
        reading.fetchone()
        recorder_commits(s.path)
        try:
            matured, lessons = mature_and_learn(j, spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0 + timedelta(hours=60))
        finally:
            reading.fetchall()
        assert matured == 1 and count(s.path, "SELECT COUNT(*) FROM forecast_outcomes") == 1
        # The lesson is written from what the shared connection can see; inside that older read it
        # cannot see the new outcome yet, so the lesson comes on the next pass - late, not lost.
        assert lessons in (0, 1)
        if lessons == 0:
            assert mature_and_learn(j, spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0 + timedelta(hours=60)) == (0, 1)
        assert count(s.path, "SELECT COUNT(*) FROM lessons") == 1
    finally:
        s.close()


def test_maturing_a_forecast_the_recorder_matured_first_is_not_an_error(tmp_path, monkeypatch):
    """The API (for a record page) and the recorder (every 15 minutes) both mature forecasts.
    When the recorder writes the outcome first, the page must not fail on the duplicate."""
    s, j = _store_with_a_due_forecast(tmp_path)
    try:
        real = s.get_bars
        fid = s._conn.execute("SELECT id FROM forecasts").fetchone()[0]

        def recorder_got_there_first(*a, **k):
            other = fresh(s.path)
            other.execute(
                "INSERT INTO forecast_outcomes (forecast_id, matured_at, exit_ts, exit_price, ret_pct) VALUES (?,?,?,?,?)", (fid, 1, 1, 100.0, 0.0)
            )
            other.close()
            return real(*a, **k)

        monkeypatch.setattr(s, "get_bars", recorder_got_there_first)
        assert j.mature(spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0 + timedelta(hours=60)) == 0
        assert count(s.path, "SELECT COUNT(*) FROM forecast_outcomes") == 1
        assert count(s.path, "SELECT exit_price FROM forecast_outcomes") == 100, "the first writer's row is kept, not replaced"
    finally:
        s.close()


def test_an_error_after_sqlite_ended_the_transaction_itself_is_the_error_raised(tmp_path):
    """SQLite rolls a transaction back on its own after some errors (disk full, I/O). The error
    that did it must reach the caller, not "cannot rollback - no transaction is active"."""
    s = Store(tmp_path / "t.sqlite")
    try:
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"), s.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (n INTEGER)")
            conn.execute("ROLLBACK")  # what SQLite does by itself on such an error
            raise sqlite3.OperationalError("disk I/O error")
        with s.transaction() as conn:  # and the store still works afterwards
            conn.execute("CREATE TABLE IF NOT EXISTS t (n INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
        assert count(s.path, "SELECT COUNT(*) FROM t") == 1
    finally:
        s.close()
