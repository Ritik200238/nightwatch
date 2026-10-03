"""The plan made in advance: price-level math (long and short), save/load, arming, the alert text."""

from datetime import timedelta

import pytest

from nightwatch.journal import plans, tripwires
from nightwatch.time_utils import to_epoch_ms, utc_now
from tests import test_api
from tests.test_api import AS_OF
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture the client fixture depends on

client = test_api.client

PAYLOAD = {"ticker": "TSLA", "side": "long", "notional_quote": 20000, "account_equity_quote": 200000, "stop_price": 300,
           "thesis": "t", "invalidation": "wrong if it closes below 290", "as_of": AS_OF.isoformat()}
ME = {"x-nw-client": "abcdefgh12345678"}


@pytest.fixture(autouse=True)
def _clean(client):
    conn = client.app.state.nw.store._conn
    with conn:
        conn.execute("DELETE FROM tripwires")
        conn.execute("DELETE FROM plans")
    yield


def _report(side="long", ref=100.0, **over):
    r = {
        "ticket": {"ticker": "TSLA", "side": side, "notional_quote": 10000, "entry_price": ref, "stop_price": None},
        "receipt": "abc123",
        "stress": {"presets": [
            {"id": "closed_window_gap_p5", "price_move_pct": -3.8 if side == "long" else 4.1},
            {"id": "closed_window_gap_p1", "price_move_pct": -7.0 if side == "long" else 8.0},
        ]},
        "failure_modes": [
            {"key": "liquidation", "title": "Liquidated", "likelihood": "3 of 40", "chance": 0.07, "loss_quote": -1000, "loss_pct": -10, "source": "x"},
            {"key": "gap_worst", "title": "A severe gap", "likelihood": "1% worse", "chance": 0.01, "loss_quote": -700, "loss_pct": -7, "source": "x"},
            {"key": "gap_bad", "title": "A bad gap", "likelihood": "5% worse", "chance": 0.05, "loss_quote": -380, "loss_pct": -3.8, "source": "x"},
            {"key": "drift", "title": "Drift", "likelihood": "60%", "chance": 0.6, "loss_quote": -100, "loss_pct": -1, "source": "x"},
        ],
        "leverage": {"liquidation_price": 90.0 if side == "long" else 110.0},
        "analog": {"horizons": {"1d": {"loss_p5_pct": -6.0, "cohort": {"n": 80}}}}, "primary_horizon": "1d",
        "execution": {"hedge_quote": {"hedged_notional": 10000, "perp_symbol": "TSLAUSDT", "total_cost_quote": 12.5}},
    }
    r.update(over)
    return r


def test_price_levels_long():
    sc = {s["key"]: s for s in plans.scenarios(_report("long"))}
    assert sc["gap_bad"]["price"] == pytest.approx(96.2) and sc["gap_bad"]["direction"] == "below"
    assert sc["liquidation"]["price"] == 90.0 and sc["gap_worst"]["price"] == pytest.approx(93.0)
    assert "drift" not in sc  # no price, so no tripwire
    assert plans.p5_price(100, -6.0, "long") == pytest.approx(94.0)


def test_price_levels_short_are_above():
    sc = {s["key"]: s for s in plans.scenarios(_report("short"))}
    assert sc["gap_bad"]["price"] == pytest.approx(104.1) and sc["gap_bad"]["direction"] == "above"
    assert sc["liquidation"]["direction"] == "above"
    assert plans.p5_price(100, -6.0, "short") == pytest.approx(106.0)
    assert all(s["price"] > 100 for s in sc.values())


def test_p5_fills_a_free_slot_and_two_names_for_one_line_are_one():
    r = _report()
    r["failure_modes"] = r["failure_modes"][:2]
    assert [s["key"] for s in plans.scenarios(r)] == ["liquidation", "gap_worst", "p5"]
    assert len(plans.scenarios(_report())) <= plans.MAX_SCENARIOS
    r2 = _report()
    r2["failure_modes"] = r2["failure_modes"][:2]
    r2["analog"]["horizons"]["1d"]["loss_p5_pct"] = -7.0  # the same price as the severe gap
    assert "p5" not in [s["key"] for s in plans.scenarios(r2)]


def test_hedge_only_when_the_report_has_a_quote_and_sizes():
    sc = plans.scenarios(_report())[0]
    assert sc["actions"]["cut_half"]["size_quote"] == 5000 and sc["actions"]["exit"]["size_quote"] == 10000
    assert sc["actions"]["hedge"]["perp_symbol"] == "TSLAUSDT"
    assert "hedge" not in plans.scenarios(_report(execution={}))[0]["actions"]


def test_reminder_text_en_and_zh():
    assert plans.reminder("cut_half", "about 5,000 USDT") == "You decided in advance: cut half (about 5,000 USDT)."
    assert plans.reminder("hold", None) == "You decided in advance: hold."
    assert plans.reminder("exit", None, "zh") == "你事先决定：全部离场。"


def _fid(client, **over) -> int:
    r = client.post("/analyze", json={**PAYLOAD, **over}, headers=ME)
    assert r.status_code == 200
    return r.json()["forecast_id"]


def test_save_load_and_arm_through_the_api(client):
    fid = _fid(client)
    got = client.get(f"/plan/{fid}", headers=ME).json()
    assert got["scenarios"] and all("chosen" not in s for s in got["scenarios"])
    keys = [s["key"] for s in got["scenarios"]]
    r = client.post("/plan", json={"forecast_id": fid, "choices": {keys[0]: "cut_half"}, "arm": True}, headers=ME)
    assert r.status_code == 200, r.text
    first = r.json()["scenarios"][0]
    assert first["chosen"]["action"] == "cut_half" and first["chosen"]["tripwire_status"] == "armed" and first["chosen"]["saved_at"]
    tw = client.get(f"/tripwire/{first['chosen']['tripwire_id']}").json()
    assert tw["level"] == pytest.approx(first["price"]) and tw["plan"]["action"] == "cut_half"
    # Another visitor sees the scenarios but not my choice.
    other = client.get(f"/plan/{fid}", headers={"x-nw-client": "someoneelse123456"}).json()
    assert all("chosen" not in s for s in other["scenarios"])
    # Changing my mind replaces the choice and reuses the armed line.
    r2 = client.post("/plan", json={"forecast_id": fid, "choices": {keys[0]: "exit"}, "arm": True}, headers=ME).json()
    assert r2["scenarios"][0]["chosen"]["action"] == "exit" and r2["scenarios"][0]["chosen"]["tripwire_id"] == first["chosen"]["tripwire_id"]


def test_save_without_arming_and_validation(client):
    fid = _fid(client)
    k = client.get(f"/plan/{fid}").json()["scenarios"][0]["key"]
    r = client.post("/plan", json={"forecast_id": fid, "choices": {k: "hold"}, "arm": False}, headers=ME).json()
    assert r["scenarios"][0]["chosen"]["tripwire_id"] is None
    assert client.get(f"/tripwire/report/{fid}", headers=ME).json()["tripwires"] == []
    assert client.post("/plan", json={"forecast_id": fid, "choices": {k: "yolo"}}, headers=ME).status_code == 422
    assert client.post("/plan", json={"forecast_id": fid, "choices": {"nope": "hold"}}, headers=ME).status_code == 422
    assert client.post("/plan", json={"forecast_id": fid, "choices": {}}, headers=ME).status_code == 422
    assert client.post("/plan", json={"forecast_id": 424242, "choices": {k: "hold"}}, headers=ME).status_code == 404
    assert client.get("/plan/424242").status_code == 404


def test_the_alert_says_what_you_decided(client, monkeypatch):
    fid = _fid(client)
    s0 = client.get(f"/plan/{fid}").json()["scenarios"][0]
    client.post("/plan", json={"forecast_id": fid, "choices": {s0["key"]: "cut_half"}}, headers=ME)
    sent = {}

    class R:
        status_code = 200

    from nightwatch.journal import watches

    monkeypatch.setattr(watches, "check_webhook", lambda u: u)
    monkeypatch.setattr("httpx.post", lambda url, json, **kw: sent.update(body=json) or R())
    conn = client.app.state.nw.store._conn
    with conn:
        conn.execute("UPDATE tripwires SET webhook='https://hooks.example.com/h'")
    lo, hi = (s0["price"] * 0.5, s0["price"] * 0.6) if s0["direction"] == "below" else (s0["price"] * 1.4, s0["price"] * 1.5)
    bar = (to_epoch_ms(utc_now() + timedelta(minutes=1)), lo, hi)
    s = client.app.state.nw
    assert tripwires.run_armed(s.store._conn, lambda t, since: [bar], lambda rep: rep, s.reports.get) >= 1
    assert sent["body"]["reminder"].startswith("You decided in advance: cut half")
    assert sent["body"]["plan"]["action"] == "cut_half"
    mine = client.get(f"/tripwire/report/{fid}", headers=ME).json()["tripwires"]
    assert mine[0]["status"] == "fired" and mine[0]["plan"]["reminder"].startswith("You decided in advance")
