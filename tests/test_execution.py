from datetime import UTC, datetime

from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot, Venue
from nightwatch.execution.exit_cost import cost_curve, max_notional_within, quote_exit, quote_hedge, replay_exit_cost

UTC = UTC
T0 = datetime(2026, 9, 12, tzinfo=UTC)


def book(depth_each: float = 2.0, levels: int = 30, step_bps: float = 4.0) -> OrderBookSnapshot:
    mid = 100.0
    bids = tuple(OrderBookLevel(price=mid * (1 - step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    asks = tuple(OrderBookLevel(price=mid * (1 + step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    return OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="X", ts=T0, observed_at=T0, bids=bids, asks=asks)


def test_quote_exit_costs_increase_with_size_and_include_fee():
    b = book()
    small = quote_exit(b, 100.0, closing_long=True, taker_fee=0.001)
    big = quote_exit(b, 3000.0, closing_long=True, taker_fee=0.001)
    assert small.fully_filled and big.fully_filled
    assert small.fee_bps == 10.0 and small.total_cost_bps == small.walk_cost_bps + 10.0
    assert big.walk_cost_bps > small.walk_cost_bps and big.levels_consumed > small.levels_consumed
    assert small.side == "sell" and quote_exit(b, 100.0, closing_long=False, taker_fee=0.0).side == "buy"


def test_quote_exit_reports_partial_fill():
    q = quote_exit(book(depth_each=0.1, levels=3), 1_000.0, closing_long=True, taker_fee=0.001)
    assert not q.fully_filled and q.levels_consumed == 3


def test_cost_curve_and_max_notional():
    b = book()
    curve = cost_curve(b, closing_long=True, taker_fee=0.001, sizes=(100, 1000, 3000, 100000))
    assert curve["total_cost_bps"].iloc[:3].is_monotonic_increasing
    assert not curve["fully_filled"].iloc[-1]
    cap = max_notional_within(b, closing_long=True, taker_fee=0.001, budget_bps=30.0)
    assert 0 < cap < 6000
    q = quote_exit(b, cap, closing_long=True, taker_fee=0.001)
    assert q.fully_filled and q.total_cost_bps <= 30.0 + 1e-6
    assert max_notional_within(b, closing_long=True, taker_fee=0.001, budget_bps=5.0) == 0.0  # fee alone exceeds budget


def test_replay_exit_cost_over_snapshots():
    snaps = [book(depth_each=2.0), book(depth_each=0.5)]
    df = replay_exit_cost(snaps, 2000.0, closing_long=True, taker_fee=0.001)
    assert len(df) == 2 and df["total_cost_bps"].iloc[1] > df["total_cost_bps"].iloc[0]


def test_hedge_quote_arithmetic():
    h = quote_hedge(position_notional=20_000, hedge_ratio=0.5, horizon_h=48, perp_symbol="TSLAUSDT", perp_fee=0.0006,
                    funding_rate_now=0.0001, funding_rate_abs_p95=0.0005, residual_basis_abs_p95_bps=40.0)
    assert h.hedged_notional == 10_000
    assert abs(h.entry_fee_quote - 6.0) < 1e-9 and abs(h.exit_fee_quote - 6.0) < 1e-9
    assert abs(h.funding_quote - 0.0001 * 6 * 10_000) < 1e-9
    assert abs(h.funding_quote_p95 - 0.0005 * 6 * 10_000) < 1e-9
    assert abs(h.total_cost_quote - (12.0 + 6.0)) < 1e-9
    assert abs(h.residual_basis_quote_p95 - 40.0) < 1e-9
