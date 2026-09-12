"""What-if sweeps: same gate, same caps, same verdict, different size or stop."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot, Venue
from nightwatch.decision.gate import GatePolicy
from nightwatch.decision.sensitivity import DecisionContext, build_sensitivity, largest_go_notional, sweep_size, sweep_stop, widest_stop_within_risk_budget
from nightwatch.decision.sizing import SizingPolicy
from nightwatch.decision.ticket import TradeTicket
from nightwatch.stress.scenarios import EmpiricalInputs, Side, build_presets

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)
ENTRY = 100.0


def book(depth_each: float = 40.0, levels: int = 40, step_bps: float = 3.0) -> OrderBookSnapshot:
    bids = tuple(OrderBookLevel(price=ENTRY * (1 - step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    asks = tuple(OrderBookLevel(price=ENTRY * (1 + step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    return OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=NOW, observed_at=NOW, bids=bids, asks=asks)


def presets():
    import numpy as np

    rng = np.random.default_rng(1)
    return tuple(build_presets(EmpiricalInputs(
        closed_window_ret_pct=rng.normal(0, 1.5, 300), earnings_gap_pct=rng.normal(0, 5, 8),
        abs_basis_closed_bps=np.abs(rng.normal(20, 10, 500)), rv_24h_now=0.35, horizon_h=48.0, funding_rate_abs_p95=0.0001,
    )))


@pytest.fixture
def dc() -> DecisionContext:
    return DecisionContext(
        entry_price=ENTRY, analog_p5_loss_pct=-3.0, quality_flags=(), regime_label="favorable", risk_multiplier=1.0,
        recent_losing_exits=(), now=NOW, book=book(), spot_taker_fee=0.001, presets=presets(),
        max_exit_notional_within_budget=60_000.0, hedge_cost_bps_of_position=12.0, hedge_residual_p5_loss_pct=-0.4,
        gate_policy=GatePolicy(), sizing_policy=SizingPolicy(),
    )


def ticket(**kw) -> TradeTicket:
    base = dict(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0, entry_price=ENTRY,
                stop_price=99.0, thesis="t", invalidation="i")
    base.update(kw)
    return TradeTicket(**base)


def test_evaluate_matches_a_direct_gate_and_sizing_run(dc):
    """The sweep cannot drift from the headline: both call the same code."""
    t = ticket()
    ev = dc.evaluate(t)
    assert ev.gate.risk_pct_of_equity == pytest.approx(20_000 * 0.01 / 200_000 * 100)  # 1% stop on a 20k position
    assert ev.verdict.verdict.value in ("GO", "REDUCE_TO", "HEDGE", "NO_GO", "REVIEW")
    assert ev.exit_cost_bps is not None and ev.worst_severe_pct is not None
    # Precomputed pieces are used verbatim rather than recomputed.
    reused = dc.evaluate(t, impacts=ev.impacts, exit_cost_bps=999.0, exit_fully_filled=True)
    assert reused.exit_cost_bps == 999.0 and reused.gate.decision.value == "NO_GO"  # 999 bps breaches the exit rule


def test_size_sweep_is_monotone_in_risk_and_covers_the_request(dc):
    t = ticket()
    points = sweep_size(dc, t, n=8)
    assert any(p.notional == t.notional_quote for p in points)
    risks = [p.risk_pct_of_equity for p in points]
    assert risks == sorted(risks)  # bigger position, more risk
    costs = [p.exit_cost_bps for p in points]
    assert costs == sorted(costs)  # bigger exit, worse price
    # Once a size stops being a GO, no larger size is one.
    gos = [p.verdict == "GO" for p in points]
    assert gos == sorted(gos, reverse=True)


def test_largest_go_is_the_boundary(dc):
    t = ticket()
    edge = largest_go_notional(dc, t)
    assert edge is not None
    assert dc.evaluate(replace(t, notional_quote=edge * 0.99)).verdict.verdict.value == "GO"
    assert dc.evaluate(replace(t, notional_quote=edge * 1.05)).verdict.verdict.value != "GO"


def test_no_size_is_a_go_when_a_size_independent_rule_blocks(dc):
    blocked = replace(dc, recent_losing_exits=(NOW,))
    assert largest_go_notional(blocked, ticket()) is None
    rep = build_sensitivity(blocked, ticket())
    assert rep.max_go_notional is None and "revenge_cooldown" in " ".join(rep.notes)


def test_stress_cap_is_solved_not_scaled(dc):
    """The recommended size must actually satisfy the limit it cites."""
    t = ticket(notional_quote=400_000.0, account_equity_quote=200_000.0)
    cap = dc.stress_cap_notional(t)
    budget = 200_000.0 * dc.sizing_policy.max_stress_loss_pct_of_equity / 100.0
    assert cap is not None and cap < t.notional_quote
    assert abs(dc.worst_severe_loss_quote(t, cap)) <= budget * 1.001
    assert abs(dc.worst_severe_loss_quote(t, cap * 1.2)) > budget  # and it is the boundary
    assert dc.stress_cap_notional(ticket(account_equity_quote=None)) is None


def test_stop_sweep_prices_both_sides_and_finds_the_widest_stop(dc):
    t = ticket(notional_quote=100_000.0)  # 1% risk budget binds at a 2% stop
    widest = widest_stop_within_risk_budget(dc, t)
    assert widest == pytest.approx(2.0, abs=0.05)
    longs = sweep_stop(dc, t, n=6)
    assert all(p.stop_price < ENTRY for p in longs)
    assert [p.risk_pct_of_equity for p in longs] == sorted(p.risk_pct_of_equity for p in longs)
    shorts = sweep_stop(dc, ticket(side=Side.SHORT, stop_price=101.0), n=4)
    assert all(p.stop_price > ENTRY for p in shorts)


def test_no_stop_answer_without_equity(dc):
    assert widest_stop_within_risk_budget(dc, ticket(account_equity_quote=None)) is None
    rep = build_sensitivity(dc, ticket(account_equity_quote=None))
    assert rep.stops == [] and rep.sizes


def test_report_says_what_would_have_to_change(dc):
    rep = build_sensitivity(dc, ticket(notional_quote=100_000.0, stop_price=95.0))
    assert rep.requested_notional == 100_000.0
    assert any("stop" in n for n in rep.notes)
