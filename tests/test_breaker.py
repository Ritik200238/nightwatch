"""The circuit breaker: realised losses on trades the trader said they took."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nightwatch.decision.breaker import BreakerPolicy, BreakerState, evaluate, realised_pnl

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
EQUITY = 100_000.0


def trades(*specs) -> pd.DataFrame:
    """Each spec is (hours_ago, notional, recommended, ret_pct)."""
    rows = []
    for i, (hours, notional, recommended, ret) in enumerate(specs):
        rows.append({
            "id": i, "ticker": "TSLA", "notional": notional, "recommended_notional": recommended,
            "horizon_end": NOW - timedelta(hours=hours), "ret_pct": ret, "taken": 1,
        })
    return pd.DataFrame(rows)


def test_the_recommended_size_is_what_counts_not_the_requested_one():
    row = pd.Series({"notional": 20_000.0, "recommended_notional": 10_000.0, "ret_pct": -5.0})
    assert realised_pnl(row) == pytest.approx(-500.0)
    no_cut = pd.Series({"notional": 20_000.0, "recommended_notional": None, "ret_pct": -5.0})
    assert realised_pnl(no_cut) == pytest.approx(-1000.0)
    assert realised_pnl(pd.Series({"notional": 20_000.0, "ret_pct": None})) is None


def test_an_empty_record_does_not_block_anything():
    rep = evaluate(pd.DataFrame(), equity=EQUITY, now=NOW)
    assert rep.state is BreakerState.NORMAL and "no trades marked as taken yet" in rep.reasons[0]


def test_a_day_inside_the_limit_stays_normal():
    rep = evaluate(trades((2, 20_000, 20_000, -1.0)), equity=EQUITY, now=NOW)  # -200 of a 2,000 limit
    assert rep.state is BreakerState.NORMAL
    day = next(w for w in rep.windows if w.name == "day")
    assert day.realised_quote == pytest.approx(-200.0) and day.used_fraction == pytest.approx(0.1)


def test_breaching_the_daily_limit_halts_new_trades():
    rep = evaluate(trades((3, 40_000, 40_000, -6.0)), equity=EQUITY, now=NOW)  # -2,400 against a 2,000 limit
    assert rep.state is BreakerState.HALTED and rep.blocks_new_trades
    assert "day loss" in rep.reasons[0]


def test_most_of_a_limit_spent_is_a_cooldown_not_a_halt():
    rep = evaluate(trades((3, 40_000, 40_000, -4.0)), equity=EQUITY, now=NOW)  # -1,600 of 2,000 = 80%
    assert rep.state is BreakerState.COOLDOWN and not rep.blocks_new_trades


def test_a_losing_streak_pauses_even_when_the_money_is_small():
    small = trades((30, 1_000, 1_000, -1.0), (20, 1_000, 1_000, -1.0), (10, 1_000, 1_000, -1.0))
    rep = evaluate(small, equity=EQUITY, now=NOW)
    assert rep.losing_streak == 3 and rep.state is BreakerState.COOLDOWN
    # A win at the end resets it.
    rep2 = evaluate(pd.concat([small, trades((1, 1_000, 1_000, +1.0))]), equity=EQUITY, now=NOW)
    assert rep2.losing_streak == 0 and rep2.state is BreakerState.NORMAL


def test_old_losses_roll_out_of_the_window():
    old = trades((200, 40_000, 40_000, -6.0))  # eight days ago: outside the day and week
    rep = evaluate(old, equity=EQUITY, now=NOW)
    day = next(w for w in rep.windows if w.name == "day")
    month = next(w for w in rep.windows if w.name == "month")
    assert day.realised_quote == 0.0 and month.realised_quote == pytest.approx(-2400.0)
    assert rep.state is BreakerState.NORMAL  # -2,400 is inside the 10,000 monthly limit


def test_without_equity_only_the_streak_can_fire():
    losses = trades((30, 1_000, 1_000, -9.0), (20, 1_000, 1_000, -9.0))
    rep = evaluate(losses, equity=None, now=NOW)
    assert rep.state is BreakerState.NORMAL and any("equity not given" in r for r in rep.reasons)
    assert all(w.limit_quote is None for w in rep.windows)


def test_the_policy_is_adjustable():
    strict = BreakerPolicy(daily_loss_pct=0.1)
    rep = evaluate(trades((2, 20_000, 20_000, -1.0)), equity=EQUITY, now=NOW, policy=strict)
    assert rep.state is BreakerState.HALTED
