"""One answer per send: a retried chat request must return the first run's answer, never run again.

The duplicate this closes: the stream is cut while its turn is still queued for the analysis
lock; the client asks plain /chat with the same message; the first turn is still running on the
server (nothing cancels it) and journals its analysis, and the retry journals a second one.
"""

import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from nightwatch.journal import idempotency as idem
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "idem.sqlite"
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.executescript(idem.SCHEMA)
    yield conn, path
    conn.close()


def other_connection(path):
    """A second connection to the same file: what a second process would be."""
    return sqlite3.connect(path, check_same_thread=False, timeout=10)


RID = "req-1234567890"


def test_the_first_claim_runs_and_a_second_waits_then_replays(db):
    conn, _ = db
    assert idem.claim(conn, RID).owner is True
    second = idem.claim(conn, RID)
    assert second.owner is False and second.running is True and second.result is None
    idem.finish(conn, RID, {"reply": "hello", "report": {"forecast_id": 7}})
    third = idem.claim(conn, RID)
    assert third.owner is False and third.result == {"reply": "hello", "report": {"forecast_id": 7}}


def test_a_failed_run_releases_the_claim_for_the_retry(db):
    conn, _ = db
    assert idem.claim(conn, RID).owner
    idem.abandon(conn, RID)
    assert idem.claim(conn, RID).owner, "an error is not an answer: the retry gets to run"


def test_a_finished_answer_is_not_abandoned_by_a_late_failure(db):
    conn, _ = db
    idem.claim(conn, RID)
    idem.finish(conn, RID, {"reply": "x"})
    idem.abandon(conn, RID)
    assert idem.claim(conn, RID).result == {"reply": "x"}


def test_a_claim_whose_owner_is_gone_is_taken_over_exactly_once(db):
    conn, path = db
    t0 = 1_000_000_000_000
    assert idem.claim(conn, RID, now_ms=t0).owner
    later = t0 + int((idem.STALE_PENDING_S + 1) * 1000)
    wins = []
    other = other_connection(path)
    for c in (conn, other):
        wins.append(idem.claim(c, RID, now_ms=later).owner)
    other.close()
    assert wins == [True, False]


def test_answers_expire_after_an_hour(db):
    conn, _ = db
    t0 = 1_000_000_000_000
    idem.claim(conn, RID, now_ms=t0)
    idem.finish(conn, RID, {"reply": "x"})
    soon = idem.claim(conn, RID, now_ms=t0 + 60_000)
    assert soon.result == {"reply": "x"}
    much_later = t0 + int((idem.KEEP_S + 5) * 1000)
    assert idem.claim(conn, RID, now_ms=much_later).owner, "an hour on, the id is free again"


def test_startup_clears_claims_of_a_process_that_no_longer_exists(db):
    conn, _ = db
    idem.claim(conn, RID)
    idem.claim(conn, "req-done-123456")
    idem.finish(conn, "req-done-123456", {"reply": "kept"})
    assert idem.clear_pending(conn) == 1
    assert idem.claim(conn, RID).owner
    assert idem.claim(conn, "req-done-123456").result == {"reply": "kept"}


def test_many_threads_with_their_own_connections_produce_exactly_one_owner(db):
    _, path = db
    owners: list[bool] = []
    start = threading.Barrier(12)
    mu = threading.Lock()

    def attempt() -> None:
        c = other_connection(path)
        try:
            start.wait(5)
            got = idem.claim(c, RID)
            with mu:
                owners.append(got.owner)
        finally:
            c.close()

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(owners) == [False] * 11 + [True]


def test_a_retry_waits_for_the_running_first_request_and_gets_its_answer(db):
    conn, path = db
    assert idem.claim(conn, RID).owner

    def first_finishes() -> None:
        time.sleep(0.4)
        c = other_connection(path)
        idem.finish(c, RID, {"reply": "the one answer"})
        c.close()

    threading.Thread(target=first_finishes).start()
    waiter = other_connection(path)
    t0 = time.monotonic()
    got = idem.wait(waiter, RID, timeout_s=5, poll_s=0.05)
    waiter.close()
    assert got.result == {"reply": "the one answer"}
    assert 0.3 <= time.monotonic() - t0 < 4


def test_a_retry_that_waits_on_a_run_that_fails_runs_it_itself(db):
    conn, path = db
    idem.claim(conn, RID)

    def first_fails() -> None:
        time.sleep(0.3)
        c = other_connection(path)
        idem.abandon(c, RID)
        c.close()

    threading.Thread(target=first_fails).start()
    waiter = other_connection(path)
    got = idem.wait(waiter, RID, timeout_s=5, poll_s=0.05)
    waiter.close()
    assert got.owner is True


def test_waiting_gives_up_and_says_it_is_still_running(db):
    conn, path = db
    idem.claim(conn, RID)
    waiter = other_connection(path)
    got = idem.wait(waiter, RID, timeout_s=0.3, poll_s=0.05)
    waiter.close()
    assert got.owner is False and got.result is None and got.running is True


def test_ids_are_restricted_to_what_a_browser_makes():
    assert idem.valid("0f9e8c1a-3b2d-4e5f-8a7b-1c2d3e4f5a6b")
    assert idem.valid("kx9f2a8b1c")
    for bad in (None, "", "short", "has space in it 1234", "x" * 65, "semi;colon-12345", "../../etc/passwd"):
        assert not idem.valid(bad)


# --- through the API --------------------------------------------------------------------------------


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def journal_rows(client) -> int:
    conn = client.app.state.nw.store._conn
    return int(conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0])


TRADE = {"messages": [{"role": "user", "content": "long 40000 TSLA overnight, account 50k"}]}


def test_the_same_request_id_analyses_and_journals_once(client):
    rid = "send-aaaaaaaa1111"
    before = journal_rows(client)
    first = client.post("/chat", json={**TRADE, "request_id": rid}).json()
    mid = journal_rows(client)
    second = client.post("/chat", json={**TRADE, "request_id": rid}).json()
    after = journal_rows(client)
    assert mid == before + 1, "the first send is analysed and journalled"
    assert after == mid, "the retry is not"
    assert second.get("replayed") is True
    assert second["report"]["forecast_id"] == first["report"]["forecast_id"]
    assert second["reply"] == first["reply"]


def test_the_stream_and_the_plain_retry_share_one_run(client):
    rid = "send-bbbbbbbb2222"
    before = journal_rows(client)
    r = client.post("/chat/stream", json={**TRADE, "request_id": rid})
    assert r.status_code == 200 and "event: done" in r.text
    retry = client.post("/chat", json={**TRADE, "request_id": rid}).json()
    assert journal_rows(client) == before + 1
    assert retry.get("replayed") is True and retry["report"]["ticket"]["ticker"] == "TSLA"


def test_without_an_id_nothing_changes(client):
    before = journal_rows(client)
    a = client.post("/chat", json=TRADE).json()
    b = client.post("/chat", json=TRADE).json()
    assert journal_rows(client) == before + 2
    assert "replayed" not in a and "replayed" not in b


def test_a_different_id_is_a_different_send(client):
    before = journal_rows(client)
    client.post("/chat", json={**TRADE, "request_id": "send-cccccccc3333"})
    client.post("/chat", json={**TRADE, "request_id": "send-dddddddd4444"})
    assert journal_rows(client) == before + 2


def test_a_malformed_id_is_ignored_not_trusted(client):
    before = journal_rows(client)
    client.post("/chat", json={**TRADE, "request_id": "bad id; drop table"})
    client.post("/chat", json={**TRADE, "request_id": "bad id; drop table"})
    assert journal_rows(client) == before + 2


def test_a_retry_while_the_first_is_still_running_waits_and_returns_its_answer(client, monkeypatch):
    """The cut-stream case: the first request holds the id and is mid-analysis (queued for the
    lock) when the retry arrives. The retry must wait for it, not analyse a second time."""
    rid = "send-eeeeeeee5555"
    state = client.app.state.nw
    before = journal_rows(client)
    gate = threading.Event()
    answers: dict[str, dict] = {}

    state.lock.__enter__()  # the first request is queued behind a long holder
    released = False
    try:
        def first() -> None:
            answers["first"] = client.post("/chat", json={**TRADE, "request_id": rid}).json()

        t = threading.Thread(target=first)
        t.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and state.lock.wanted < 2:  # holder + the first request
            time.sleep(0.02)
        assert state.lock.wanted >= 2

        def retry() -> None:
            gate.set()
            answers["retry"] = client.post("/chat", json={**TRADE, "request_id": rid}).json()

        r = threading.Thread(target=retry)
        r.start()
        gate.wait(2)
        time.sleep(0.4)  # the retry is now waiting on the claim, not on the lock
        waiting_on_lock = state.lock.wanted
    finally:
        state.lock.__exit__(None, None, None)
        released = True
    assert released
    t.join(60)
    r.join(60)
    assert waiting_on_lock == 2, "the retry waited for the first run instead of queueing a second analysis"
    assert journal_rows(client) == before + 1
    assert answers["retry"].get("replayed") is True
    assert answers["retry"]["report"]["forecast_id"] == answers["first"]["report"]["forecast_id"]


def test_a_retry_that_cannot_get_the_first_answer_in_time_says_so_without_a_second_analysis(client, monkeypatch):
    """409, never 503: the proxy turns 502/503/504 into a saved example of a different trade."""
    rid = "send-ffffffff6666"
    conn = client.app.state.nw.store._conn
    assert idem.claim(conn, rid).owner  # a first run that is still going
    real_wait = idem.wait
    monkeypatch.setattr(idem, "wait", lambda c, r, **k: real_wait(c, r, timeout_s=0.3, poll_s=0.05))
    before = journal_rows(client)
    r = client.post("/chat", json={**TRADE, "request_id": rid})
    assert r.status_code == 409
    assert "still being answered" in r.json()["detail"]
    assert journal_rows(client) == before


def test_a_failed_first_run_does_not_poison_the_retry(client, monkeypatch):
    rid = "send-gggggggg7777"
    before = journal_rows(client)
    bad = client.post("/chat", json={"messages": [{"role": "user", "content": "how often does TSLA fall 5% over a weekend"}], "request_id": rid})
    # whatever that was (answer or error), a different message under the same id must still run
    ok = client.post("/chat", json={**TRADE, "request_id": "send-hhhhhhhh8888"})
    assert ok.status_code == 200
    conn = client.app.state.nw.store._conn
    if bad.status_code != 200:
        assert idem.claim(conn, rid).owner, "an error released the claim"
    assert journal_rows(client) >= before + 1
