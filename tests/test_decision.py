from datetime import datetime, timedelta, timezone

import pytest

from nightwatch.decision.gate import GateDecision, GateInputs, GatePolicy, evaluate_gate
from nightwatch.decision.sizing import SizingInputs, Verdict, decide, recommend_size
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import ET

UTC = timezone.utc
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def ticket(**kw) -> TradeTicket:
    base = dict(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0, entry_price=364.0,
                stop_price=350.0, thesis="post-earnings drift continues", invalidation="close below 350")
    base.update(kw)
    return TradeTicket(**base)


def inputs(**kw) -> GateInputs:
    base = dict(entry_price=364.0, equity=200_000.0, analog_p5_loss_pct=-3.2, quality_flags=(), regime_label="favorable",
                risk_multiplier=1.0, exit_cost_bps=12.0, exit_fully_filled=True, recent_losing_exits=(), now=NOW)
    base.update(kw)
    return GateInputs(**base)


def test_ticket_validation_and_horizons():
    with pytest.raises(ValueError):
        ticket(notional_quote=0)
    with pytest.raises(ValueError):
        ticket(horizon_kind=HorizonKind.HOURS)
    t = ticket()
    sat = datetime(2026, 9, 12, 12, tzinfo=ET)
    assert t.horizon_h(sat) == 45.5  # to Monday 09:30 ET
    assert abs(t.stop_distance_pct(364.0) - 14 / 364 * 100) < 1e-9
    assert t.stop_is_on_correct_side(364.0)
    assert ticket(side=Side.SHORT, stop_price=380.0).stop_is_on_correct_side(364.0)


def test_gate_go_when_everything_stated():
    rep = evaluate_gate(ticket(), inputs())
    assert rep.decision == GateDecision.GO
    assert rep.risk_basis == "distance to stop" and abs(rep.risk_pct_of_equity - (20_000 * 14 / 364) / 200_000 * 100) < 1e-9


def test_gate_review_when_plan_or_equity_missing():
    rep = evaluate_gate(ticket(thesis=""), inputs())
    assert rep.decision == GateDecision.REVIEW_REQUIRED and any("missing thesis" in r for r in rep.reasons)
    rep2 = evaluate_gate(ticket(account_equity_quote=None), inputs(equity=None))
    assert rep2.decision == GateDecision.REVIEW_REQUIRED


def test_gate_no_go_on_wrong_side_stop_oversize_and_revenge():
    assert evaluate_gate(ticket(stop_price=380.0), inputs()).decision == GateDecision.NO_GO
    assert evaluate_gate(ticket(notional_quote=60_000.0), inputs()).decision == GateDecision.NO_GO  # 30% of equity
    rep = evaluate_gate(ticket(), inputs(recent_losing_exits=(NOW - timedelta(hours=5),)))
    assert rep.decision == GateDecision.NO_GO and any("cooldown" in r for r in rep.reasons)


def test_gate_uses_analog_p5_when_no_stop_and_flags_liquidity():
    rep = evaluate_gate(ticket(stop_price=None), inputs())
    assert rep.risk_basis == "analog 5th-percentile loss" and rep.decision == GateDecision.REVIEW_REQUIRED  # no stop -> review
    rep2 = evaluate_gate(ticket(), inputs(exit_fully_filled=False))
    assert rep2.decision == GateDecision.NO_GO
    rep3 = evaluate_gate(ticket(), inputs(quality_flags=("index_price_missing",)))
    assert rep3.decision == GateDecision.REVIEW_REQUIRED


def test_gate_risk_budget_no_go():
    # 20k with a 14/364 stop = 769 risk = 0.38% of 200k -> fine; with 20k equity it is 3.8% -> NO_GO.
    rep = evaluate_gate(ticket(account_equity_quote=20_000.0), inputs(equity=20_000.0), GatePolicy(max_position_pct_of_equity=100.0))
    assert rep.decision == GateDecision.NO_GO and any("risk_budget" in r for r in rep.reasons)


def sizing_inputs(**kw) -> SizingInputs:
    base = dict(entry_price=364.0, equity=200_000.0, stop_distance_pct=3.85, analog_p5_loss_pct=-3.2, risk_multiplier=1.0,
                max_exit_notional_within_budget=150_000.0, worst_severe_stress_pct=-4.0, hedge_cost_bps_of_position=8.0, hedge_residual_p5_loss_pct=-0.6)
    base.update(kw)
    return SizingInputs(**base)


def test_sizing_caps_and_binding():
    t = ticket()
    res = recommend_size(t, sizing_inputs())
    by = {c.name: c.notional for c in res.caps}
    assert abs(by["risk_budget"] - 200_000 * 0.01 / 0.0385) < 1e-6
    assert by["concentration"] == 50_000 and by["exit_liquidity"] == 150_000 and by["regime"] == 20_000
    assert res.binding_cap == "regime" and res.recommended_notional == 20_000


def test_verdict_go_reduce_hedge_no_go_review():
    t = ticket()
    gate = evaluate_gate(t, inputs())
    assert decide(t, gate, recommend_size(t, sizing_inputs())).verdict == Verdict.GO
    # Hostile regime halves size; hedge is cheap and effective -> HEDGE rather than cut.
    hedged = decide(t, gate, recommend_size(t, sizing_inputs(risk_multiplier=0.5)))
    assert hedged.verdict == Verdict.HEDGE and abs(hedged.hedge_ratio - 0.5) < 1e-9
    # Same but hedge too expensive -> REDUCE_TO.
    reduced = decide(t, gate, recommend_size(t, sizing_inputs(risk_multiplier=0.5, hedge_cost_bps_of_position=80.0)))
    assert reduced.verdict == Verdict.REDUCE_TO and reduced.recommended_notional == 10_000
    # Exit liquidity binding never suggests a hedge (you still cannot get out of the spot leg).
    liq = decide(t, gate, recommend_size(t, sizing_inputs(max_exit_notional_within_budget=5_000.0)))
    assert liq.verdict == Verdict.REDUCE_TO and liq.recommended_notional == 5_000
    # Gate failure dominates.
    bad_gate = evaluate_gate(ticket(stop_price=380.0), inputs())
    assert decide(t, bad_gate, recommend_size(t, sizing_inputs())).verdict == Verdict.NO_GO
    review_gate = evaluate_gate(ticket(thesis=""), inputs())
    assert decide(t, review_gate, recommend_size(t, sizing_inputs())).verdict == Verdict.REVIEW
