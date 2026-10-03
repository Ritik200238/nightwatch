"""Every headline number says whether it is live, measured from history, assumed, or AI."""

from nightwatch.decision.ticket import TradeTicket
from nightwatch.pipeline.analyze import analyze
from nightwatch.pipeline.provenance import build, preset_provenance
from nightwatch.stress.scenarios import Side
from tests.test_pipeline import AS_OF, _ctx, seeded_store  # noqa: F401 - fixture


def test_presets_are_history_only_when_they_carry_a_sample():
    gap = {"id": "closed_window_gap_p5", "calibration": {"source": "spot close→open across closed windows", "n": 120}}
    assert preset_provenance(gap)["kind"] == "history" and preset_provenance(gap)["n"] == 120
    drought = {"id": "liquidity_drought", "calibration": {"source": "live order book scaled"}}
    assert preset_provenance(drought)["kind"] == "assumed"
    assert preset_provenance({"id": "replay_covid", "calibration": {"source": "Yahoo daily", "date": "2020-03-16"}})["kind"] == "history"


def test_stop_based_loss_is_assumed_and_analog_loss_is_history():
    base = {"as_of": "2026-01-02T00:00:00+00:00", "gate": {"risk_basis": "distance to stop"}, "analog": {"horizons": {}, "result": {}}}
    assert build(base)["items"]["loss_line"]["kind"] == "assumed"
    base["gate"] = {"risk_basis": "analog 5th-percentile loss"}
    assert build(base)["items"]["loss_line"]["kind"] == "history"


def test_book_age_and_stale_flag():
    p = {"as_of": "2026-01-02T00:01:00+00:00", "execution": {"book_ts": "2026-01-02T00:00:20+00:00", "book_source": "recorded", "exit_quote": {"x": 1}}}
    item = build(p)["items"]["exit_cost"]
    assert item["kind"] == "live" and item["age_s"] == 40 and not item["stale"]
    p["execution"]["book_source"] = "recorded (stale by 9 min)"
    assert build(p)["items"]["exit_cost"]["stale"] is True


def test_a_real_report_carries_provenance(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    t = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0, thesis="t", invalidation="i")
    d = analyze(ctx, t, as_of=AS_OF, record=False).to_dict()
    items = d["provenance"]["items"]
    assert items["analyst"]["kind"] == "ai" and items["size"]["kind"] == "assumed"
    assert items["analog"]["kind"] == "history" and all(v["kind"] in ("history", "assumed") for v in items["stress"].values())
