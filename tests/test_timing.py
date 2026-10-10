"""Where a request's time goes: the lock wait, the hold and the rest, as one log line.

Pinned so the line can be trusted when it is the only evidence of a slow answer: it must say
how long the request queued and behind whom, how long it held the lock, and it must not carry
anything the visitor typed.
"""

import logging
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api import timing
from nightwatch.api.app import create_app
from nightwatch.api.locking import DeskBusy, RequestFirstLock
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


class Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.out.append(record.getMessage())


@pytest.fixture
def lines():
    h = Lines()
    timing._ensure_handler()
    timing.logger.addHandler(h)
    yield h.out
    timing.logger.removeHandler(h)


def fields(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def test_a_request_that_queued_reports_the_wait_and_who_it_waited_for():
    lock = RequestFirstLock()
    holder_in = threading.Event()
    holder_clock = timing.RequestTiming("POST", "/chat/stream")

    def holder() -> None:
        with timing.attached(holder_clock), lock:
            holder_in.set()
            time.sleep(0.3)

    th = threading.Thread(target=holder)
    th.start()
    assert holder_in.wait(2)
    waiter = timing.RequestTiming("POST", "/analyze")
    with timing.attached(waiter):
        with lock:
            time.sleep(0.05)
    th.join(2)

    assert waiter.locks == 1
    assert 0.2 <= waiter.wait_s < 1.0, "it queued for most of the holder's 0.3 s"
    assert 0.04 <= waiter.hold_s < 0.5, "its own work is the hold, not the queue"
    assert waiter.queued_ahead == 1
    assert waiter.holder.startswith("POST /chat/stream for ")
    # The holder was first in line: no wait, and a hold of about 0.3 s.
    assert holder_clock.wait_s < 0.1 and 0.25 <= holder_clock.hold_s < 1.0
    assert holder_clock.queued_ahead == 0 and holder_clock.holder == ""


def test_the_warm_up_is_named_when_a_request_waits_behind_it():
    lock = RequestFirstLock()
    in_step = threading.Event()

    def warm() -> None:
        with lock.background():
            in_step.set()
            time.sleep(0.2)

    th = threading.Thread(target=warm, name="warm-frames")
    th.start()
    assert in_step.wait(2)
    clock = timing.RequestTiming("POST", "/chat")
    with timing.attached(clock), lock:
        pass
    th.join(2)
    assert clock.holder.startswith("warm-frames for ")
    assert clock.wait_s >= 0.1


def test_giving_up_is_recorded_and_still_raises():
    lock = RequestFirstLock()
    held = threading.Event()
    done = threading.Event()

    def holder() -> None:
        with lock:
            held.set()
            done.wait(2)

    th = threading.Thread(target=holder)
    th.start()
    assert held.wait(2)
    clock = timing.RequestTiming("GET", "/misses")
    with timing.attached(clock):
        with pytest.raises(DeskBusy), lock.request(0.1):
            pass
    done.set()
    th.join(2)
    assert clock.gave_up == 1 and clock.locks == 1
    assert 0.05 <= clock.wait_s < 1.0
    assert lock.wanted == 0
    assert "gave_up=1" in clock.line(503, "ok")


def test_the_lock_works_the_same_with_no_request_and_a_broken_clock():
    lock = RequestFirstLock()
    with lock:  # no request on this thread
        pass
    with lock.request(1):
        pass

    class Broken(timing.RequestTiming):
        def lock_taken(self, *a, **k):
            raise RuntimeError("clock broke")

        def lock_released(self, *a, **k):
            raise RuntimeError("clock broke")

    with timing.attached(Broken("GET", "/x")), lock:
        pass
    assert lock.wanted == 0
    with lock.background(max_wait_s=0.5):
        pass


def test_the_line_has_the_pieces_and_nothing_else():
    clock = timing.RequestTiming("POST", "/chat/stream")
    clock.started = 100.0
    clock.marks = [("work_start", 0.004), ("chat_turn", 0.021)]
    clock.lock_taken(asked=100.5, got=141.5, ahead=2, holder="POST /chat", holder_for_s=7.0)
    clock.lock_released(got=141.5, released=144.9)
    f = fields(clock.line(200, "ok", ended=145.3))
    assert f["method"] == "POST" and f["path"] == "/chat/stream" and f["status"] == "200" and f["outcome"] == "ok"
    assert f["total_ms"] == "45300"
    assert f["to_lock_ms"] == "500"
    assert f["lock_wait_ms"] == "41000"
    assert f["lock_hold_ms"] == "3400"
    assert f["after_lock_ms"] == "400"
    assert f["locks"] == "1" and f["queued_ahead"] == "2"
    assert f["holder"] == "POST /chat for 7000ms"
    assert f["marks"] == "work_start:4,chat_turn:21"


def test_a_request_that_never_asked_for_the_lock_has_no_lock_fields():
    clock = timing.RequestTiming("GET", "/health")
    out = clock.line(200, "ok")
    assert "lock_wait_ms" not in out and "to_lock_ms" not in out
    assert not clock.worth_logging(0.01)
    assert clock.worth_logging(timing.SLOW_REQUEST_S + 0.1)
    assert not timing.RequestTiming("OPTIONS", "/chat").worth_logging(10)


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def timing_lines(lines: list[str], path: str) -> list[dict[str, str]]:
    return [fields(x) for x in lines if x.startswith("nw_timing") and f"path={path} " in x]


def test_analyze_logs_one_line_with_the_lock_and_no_visitor_data(client, lines):
    payload = {
        "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
        "thesis": "my private reason for this trade", "invalidation": "private invalidation", "as_of": AS_OF.isoformat(), "record": False,
    }
    r = client.post("/analyze?nw_v=visitor-abc123&nw_lang=en", json=payload)
    assert r.status_code == 200
    got = timing_lines(lines, "/analyze")
    assert len(got) == 1
    f = got[0]
    assert f["status"] == "200" and f["locks"] == "1" and f["queued_ahead"] == "0"
    assert int(f["lock_hold_ms"]) > 0 and int(f["total_ms"]) >= int(f["lock_hold_ms"])
    text = "\n".join(lines)
    for private in ("visitor-abc123", "nw_v", "private reason", "private invalidation", "TSLA", "20000", "testclient"):
        assert private not in text, f"{private!r} must never reach the timing line"


def test_a_stream_reports_its_worker_start_and_the_lock(client, lines):
    r = client.post("/chat/stream", json={"messages": [{"role": "user", "content": "long 40000 TSLA overnight, account 50k"}]})
    assert r.status_code == 200 and "event: done" in r.text
    got = timing_lines(lines, "/chat/stream")
    assert len(got) == 1
    f = got[0]
    assert f["outcome"] == "ok" and int(f["locks"]) >= 1
    assert f["marks"].split(",")[0].startswith("work_start:")
    assert int(f["to_lock_ms"]) <= int(f["total_ms"])
    assert "long 40000" not in "\n".join(lines)


def test_the_model_path_marks_where_the_turn_began(client):
    """With a language provider the turn goes through llm.chat_turn; its first act is a mark,
    so the time between the worker starting and the turn beginning is its own number."""
    from nightwatch.api import llm

    class Stub:
        name, model, narrates = "stub", "stub-1", False

    clock = timing.RequestTiming("POST", "/chat/stream")
    state = client.app.state.nw
    msgs = [{"role": "user", "content": "long 40000 TSLA overnight, account 50k"}]
    with timing.attached(clock):
        out = llm.chat_turn(state, msgs, account_equity=50000.0, provider=Stub())
    assert out["parsed_by"] == "rules" and out["report"] is not None
    assert [n for n, _ in clock.marks][0] == "chat_turn"
    assert clock.locks >= 1 and clock.hold_s > 0


def test_a_fast_health_check_is_not_logged_and_the_switch_turns_it_all_off(client, lines, monkeypatch):
    assert client.get("/health").status_code == 200  # the first one counts every table
    lines.clear()
    t0 = time.monotonic()
    assert client.get("/health").status_code == 200
    assert time.monotonic() - t0 < timing.SLOW_REQUEST_S, "the second health check is cached and quick"
    assert not [x for x in lines if "path=/health" in x]
    monkeypatch.setenv("NIGHTWATCH_TIMING", "0")
    n = len(lines)
    r = client.post("/chat/stream", json={"messages": [{"role": "user", "content": "thanks"}]})
    assert r.status_code == 200
    assert len(lines) == n


def test_timing_endpoint_serves_the_recent_requests_and_the_lock(client, lines):
    client.post("/analyze?nw_v=visitor-xyz", json={
        "ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
        "thesis": "t", "invalidation": "i", "as_of": AS_OF.isoformat(), "record": False,
    })
    body = client.get("/timing?limit=5").json()
    assert body["enabled"] is True and body["started_at"]
    assert body["lock"] == {"wanted": 0, "holder": "", "held_ms": 0}
    assert 1 <= len(body["requests"]) <= 5
    newest = body["requests"][0]
    assert newest["path"] == "/analyze" and newest["method"] == "POST" and newest["status"] == 200
    assert newest["locks"] == 1 and newest["lock_hold_ms"] > 0 and newest["at"].endswith("+00:00")
    assert "visitor-xyz" not in str(body) and "nw_v" not in str(body)
    # newest first, and the limit is a limit
    assert client.get("/timing?limit=1").json()["requests"][0] == newest
