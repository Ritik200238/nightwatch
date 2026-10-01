"""The stress-test agent: a scripted model drives the real tools; the cap, the number
check and the verdict rule hold whatever the model says."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwatch.api import agent
from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_analyst import REPORT
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

DONE = {"final": {"summary": "done", "findings": [], "verdict_restated": ""}}


class Script:
    """A provider that replies from a list, recording what it was asked."""

    model = "fake"

    def __init__(self, replies):  # noqa: ANN001
        self.replies = list(replies)
        self.users: list[str] = []

    def write(self, *, system, user, max_tokens=1500):  # noqa: ANN001, ANN201
        self.users.append(user)
        r = self.replies.pop(0) if self.replies else DONE
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


class FakeState:
    lock = threading.Lock()
    ctx = None


def _call(tool, args=None):  # noqa: ANN001, ANN202
    return {"thought": "check it", "tool": tool, "args": args or {}}


def _run(replies, report=REPORT, **kw):  # noqa: ANN001, ANN003, ANN202
    run = agent.Run()
    agent.run_agent(Script(replies), FakeState(), report, run, **kw)
    return run


def test_the_tools_run_in_order_and_each_step_is_recorded(monkeypatch):
    monkeypatch.setitem(agent.TOOLS, "explain", lambda s, r, a: "Worst case is 2,147 USDT.")
    monkeypatch.setitem(agent.TOOLS, "safest_ways", lambda s, r, a: "Half the size: GO at 10,000 USDT.")
    prov = Script([_call("explain", {"kind": "worst"}), _call("safest_ways"),
                   {"final": {"summary": "Worst case is 2,147 USDT [explain].", "findings": ["Half size is 10,000 USDT [safest ways]."], "verdict_restated": ""}}])
    run = agent.Run()
    agent.run_agent(prov, FakeState(), REPORT, run)
    assert run.status == "done"
    assert [s["tool"] for s in run.steps] == ["explain", "safest_ways"]
    assert [s["n"] for s in run.steps] == [1, 2]
    assert set(run.steps[0]) == {"n", "thought", "tool", "args", "result_summary", "seconds"}
    assert "2,147" in run.steps[0]["result_summary"]
    assert run.final["summary"] == "Worst case is 2,147 USDT [explain]."
    assert run.final["findings"] == ["Half size is 10,000 USDT [safest ways]."]
    # The first result was fed back before the second call was chosen.
    assert "2,147" in prov.users[1]


def test_the_cap_is_enforced_and_the_model_is_told_to_finish(monkeypatch):
    monkeypatch.setitem(agent.TOOLS, "explain", lambda s, r, a: "ok")
    prov = Script([_call("explain", {"kind": "why"})] * 8)
    run = agent.Run()
    agent.run_agent(prov, FakeState(), REPORT, run)
    assert len(run.steps) == agent.MAX_CALLS
    assert run.status == "failed"  # kept calling tools after the cap
    assert "No more tool calls" in prov.users[agent.MAX_CALLS]


def test_a_model_that_finishes_when_told_is_done_at_the_cap(monkeypatch):
    monkeypatch.setitem(agent.TOOLS, "explain", lambda s, r, a: "ok")
    run = _run([_call("explain", {"kind": "why"})] * 5 + [DONE])
    assert run.status == "done" and len(run.steps) == 5


def test_a_number_the_tools_never_gave_is_stripped():
    run = _run([{"final": {"summary": "Fine overall.", "findings": ["It will lose 99% [history].", "A bad night is -4.6% [history]."],
                           "verdict_restated": ""}}])
    assert run.status == "done"
    assert run.final["findings"] == ["A bad night is -4.6% [history]."]
    assert run.removed == 1


def test_a_number_from_a_tool_result_needs_its_tag(monkeypatch):
    monkeypatch.setitem(agent.TOOLS, "explain", lambda s, r, a: "Loss is 7,777 USDT.")
    run = _run([_call("explain", {"kind": "worst"}),
                {"final": {"summary": "x", "findings": ["Loss is 7,777 USDT [explain].", "Loss is 7,777 USDT."], "verdict_restated": ""}}])
    assert run.final["findings"] == ["Loss is 7,777 USDT [explain]."]


def test_the_model_cannot_change_the_verdict():
    run = _run([{"final": {"summary": "s", "findings": [], "verdict_restated": "The verdict is NO_GO at 0 USDT."}}])
    assert "NO_GO" not in run.final["verdict_restated"]
    assert "GO" in run.final["verdict_restated"] and "20,000" in run.final["verdict_restated"]  # the report's own


def test_an_unknown_tool_or_bad_args_become_a_result_not_a_crash():
    run = _run([_call("delete_everything"), _call("rerun", {"leverage": "lots"}), DONE])
    assert run.status == "done"
    assert run.steps[0]["result_summary"].startswith("unknown tool")
    assert "no valid change" in run.steps[1]["result_summary"]


def test_a_failure_keeps_the_steps_so_far(monkeypatch):
    monkeypatch.setitem(agent.TOOLS, "explain", lambda s, r, a: "ok")
    run = _run([_call("explain", {"kind": "why"}), RuntimeError("gateway down")])
    assert run.status == "failed" and len(run.steps) == 1 and "gateway down" in run.error


def test_two_unusable_replies_fail_the_run():
    run = _run(["not json at all", "still not json"])
    assert run.status == "failed" and run.steps == []


def test_the_time_budget_forces_a_wrap_up():
    prov = Script([DONE])
    run = agent.Run()
    agent.run_agent(prov, FakeState(), REPORT, run, budget_s=-1)
    assert run.status == "done" and run.steps == [] and "No more tool calls" in prov.users[0]


def test_chinese_restates_the_verdict_in_chinese():
    run = agent.Run(lang="zh")
    agent.run_agent(Script([{"final": {"summary": "好", "findings": [], "verdict_restated": ""}}]), FakeState(), REPORT, run)
    assert run.final["verdict_restated"].startswith("本台的结论不变")


# --------------------------------------------------------- real engine, over HTTP


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def test_the_endpoints_run_the_real_tools_and_steps_appear_as_they_finish(client, monkeypatch):
    body = client.post("/analyze", json={"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000,
                                          "stop_price": 300, "as_of": AS_OF.isoformat()}).json()
    fid = body["forecast_id"]
    prov = Script([_call("rerun", {"notional_quote": 10000}), _call("safest_ways"), _call("explain", {"kind": "why"}),
                   {"final": {"summary": "Checked three ways.", "findings": [], "verdict_restated": "x"}}])
    monkeypatch.setattr("nightwatch.api.providers.select", lambda *a, **k: prov)
    assert client.get(f"/agent/{fid}").json()["status"] == "none"
    assert "job" in client.post(f"/agent/{fid}").json()
    got = {}
    for _ in range(100):
        got = client.get(f"/agent/{fid}").json()
        if got["status"] != "running":
            break
        time.sleep(0.2)
    assert got["status"] == "done", got
    assert [s["tool"] for s in got["steps"]] == ["rerun", "safest_ways", "explain"]
    assert "10,000 USDT" in got["steps"][0]["result_summary"] and "verdict" in got["steps"][0]["result_summary"]
    assert client.post("/agent/99999").status_code == 404


def test_a_rerun_that_changes_nothing_is_refused_before_it_costs_a_run():
    import pytest as _pytest

    from nightwatch.api import agent as agent_mod

    report = {"ticket": {"ticker": "TSLA", "side": "long", "notional_quote": 20000.0, "horizon_kind": "next_open", "horizon_hours": None},
              "as_of": "2026-09-12T14:00:00+00:00"}
    with _pytest.raises(ValueError, match="as it already stands"):
        agent_mod.tool_rerun(None, report, {"horizon_kind": "next_open"})


def test_hours_on_a_next_open_hold_are_still_the_same_trade():
    import pytest as _pytest

    from nightwatch.api import agent as agent_mod

    report = {"ticket": {"ticker": "TSLA", "side": "long", "notional_quote": 20000.0, "horizon_kind": "next_open", "horizon_hours": None}}
    with _pytest.raises(ValueError, match="as it already stands"):
        agent_mod.tool_rerun(None, report, {"horizon_kind": "next_open", "horizon_hours": 6})


def test_through_the_weekend_on_a_weekend_ticket_is_the_same_trade():
    import pytest as _pytest

    from nightwatch.api import agent as agent_mod

    report = {"ticket": {"ticker": "TSLA", "side": "long", "notional_quote": 20000.0, "horizon_kind": "hours", "horizon_hours": 98.5,
                         "extra": {"horizon_label": "through the weekend, to the next open after it"}}}
    with _pytest.raises(ValueError, match="as it already stands"):
        agent_mod.tool_rerun(None, report, {"horizon_kind": "through_weekend"})
