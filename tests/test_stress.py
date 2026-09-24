from datetime import UTC, datetime

import numpy as np
import pandas as pd

from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot, Venue
from nightwatch.stress.montecarlo import block_bootstrap_paths, hourly_log_returns, reverse_stress, simulate
from nightwatch.stress.scenarios import (
    EmpiricalInputs,
    Position,
    Scenario,
    Severity,
    Side,
    apply_scenario,
    build_presets,
    closed_window_returns,
    earnings_gaps,
    impacts_table,
    sensitivity,
)

UTC = UTC
T0 = datetime(2026, 9, 12, tzinfo=UTC)


def book(depth_each: float = 1.0, levels: int = 20, step_bps: float = 5.0) -> OrderBookSnapshot:
    mid = 100.0
    bids = tuple(OrderBookLevel(price=mid * (1 - step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    asks = tuple(OrderBookLevel(price=mid * (1 + step_bps / 1e4 * (i + 0.5)), size=depth_each) for i in range(levels))
    return OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=T0, observed_at=T0, bids=bids, asks=asks)


def test_apply_scenario_long_adverse_move_and_exit_cost():
    pos = Position("TSLA", Side.LONG, notional_quote=500.0, entry_price=100.0)
    sc = Scenario(id="x", name="x", severity=Severity.SEVERE, horizon_h=48, price_move_pct=-5.0)
    imp = apply_scenario(pos, sc, book=book(), taker_fee=0.001)
    assert abs(imp.mtm_pnl_quote - (-25.0)) < 1e-9
    assert imp.exit_fully_filled and imp.exit_cost_quote > 0.5  # fee 0.1% of 500 = 0.5 plus walk cost
    assert imp.total_pnl_quote < -25.0 and imp.total_pct_of_notional < -5.0
    assert imp.breaches["max_loss"] and not imp.breaches["cannot_fully_exit"]


def test_short_position_profits_from_drop_and_hedge_offsets():
    pos = Position("TSLA", Side.SHORT, notional_quote=1000.0, entry_price=100.0)
    sc = Scenario(id="x", name="x", severity=Severity.MILD, horizon_h=24, price_move_pct=-5.0)
    imp = apply_scenario(pos, sc, book=book(depth_each=50), taker_fee=0.0)
    assert imp.mtm_pnl_quote == 50.0 and imp.total_pnl_quote > 40.0
    hedged = Position("TSLA", Side.LONG, notional_quote=1000.0, entry_price=100.0, hedge_ratio=1.0)
    imp_h = apply_scenario(hedged, sc, book=book(depth_each=50), taker_fee=0.0)
    assert abs(imp_h.mtm_pnl_quote + imp_h.hedge_pnl_quote) < 1e-9  # fully hedged underlying move


def test_thin_book_cannot_fully_exit_and_basis_shock_hurts():
    pos = Position("TSLA", Side.LONG, notional_quote=5000.0, entry_price=100.0)
    sc = Scenario(id="x", name="x", severity=Severity.EXTREME, horizon_h=48, depth_multiplier=0.1, basis_shock_bps=80)
    imp = apply_scenario(pos, sc, book=book(depth_each=1.0), taker_fee=0.001)
    assert not imp.exit_fully_filled and imp.breaches["cannot_fully_exit"]
    assert imp.basis_pnl_quote == -40.0


def test_sensitivity_sweep_monotone():
    pos = Position("TSLA", Side.LONG, notional_quote=500.0, entry_price=100.0)
    base = Scenario(id="b", name="b", severity=Severity.MILD, horizon_h=24)
    df = sensitivity(pos, base, "price_move_pct", [-1, -3, -5, -10], book=book(), taker_fee=0.001)
    assert list(df["price_move_pct"]) == [-1, -3, -5, -10]
    assert df["total_pct"].is_monotonic_decreasing


def test_closed_window_returns_and_earnings_gaps():
    idx = pd.date_range(datetime(2026, 9, 9, 13, tzinfo=UTC), periods=60, freq="1h", tz="UTC")
    f = pd.DataFrame(index=idx)
    f["spot_close"] = 100.0
    f["session"] = "night"
    # Regular hours 14:00-20:00 UTC each day; set closes so close->open across the night is +1%.
    for day in range(3):
        reg = (idx >= idx[0] + pd.Timedelta(hours=1 + 24 * day)) & (idx < idx[0] + pd.Timedelta(hours=7 + 24 * day))
        f.loc[reg, "session"] = "regular"
        f.loc[reg, "spot_close"] = 100.0 * (1.01**day)
    r = closed_window_returns(f)
    assert len(r) == 2 and np.allclose(r, 1.0)
    from nightwatch.data.models import EarningsEvent
    from nightwatch.time_utils import ET

    # Sessions Mon..Thu 2026-08-03..06, bars indexed at 13:30 UTC like Yahoo.
    idx = pd.date_range(datetime(2026, 8, 3, 13, 30, tzinfo=UTC), periods=4, freq="D", tz="UTC")
    daily = pd.DataFrame({"open": [100, 95, 96, 90], "close": [100, 94, 96, 98]}, index=idx)
    amc = EarningsEvent(ticker="X", report_date=datetime(2026, 8, 4, tzinfo=ET).astimezone(UTC), timing="amc", source="t", observed_at=T0)
    bmo = EarningsEvent(ticker="X", report_date=datetime(2026, 8, 6, tzinfo=ET).astimezone(UTC), timing="bmo", source="t", observed_at=T0)
    g = earnings_gaps(daily, [amc, bmo])
    # amc on Tue: Wed open 96 vs Tue close 94 = +2.13%; bmo on Thu: Thu open 90 vs Wed close 96 = -6.25%
    assert np.allclose(g, [(96 / 94 - 1) * 100, (90 / 96 - 1) * 100])


def test_presets_calibrated_and_documented():
    rng = np.random.default_rng(0)
    inp = EmpiricalInputs(
        closed_window_ret_pct=rng.normal(0, 2, 200), earnings_gap_pct=np.array([-8, 5, -3, 12, -6]),
        abs_basis_closed_bps=np.abs(rng.normal(0, 25, 500)), rv_24h_now=0.5, horizon_h=60, funding_rate_abs_p95=0.0005,
    )
    presets = build_presets(inp)
    ids = {p.id for p in presets}
    assert {"closed_window_gap_p5", "earnings_gap_worst", "vol_spike_x2", "basis_blowout_p99", "liquidity_drought", "exchange_halt_24h", "funding_spike"} <= ids
    worst = next(p for p in presets if p.id == "earnings_gap_worst")
    assert worst.price_move_pct == -8.0 and worst.calibration["n"] == 5
    for p in presets:
        assert p.calibration.get("source") and p.probability_note
    pos = Position("TSLA", Side.LONG, notional_quote=2000.0, entry_price=100.0)
    table = impacts_table([apply_scenario(pos, p, book=book(depth_each=5), taker_fee=0.001) for p in presets], presets)
    assert len(table) == len(presets) and table["total_pct"].notna().all()


def test_presets_skip_when_too_few_observations():
    inp = EmpiricalInputs(closed_window_ret_pct=np.array([1.0, -1.0]), earnings_gap_pct=np.array([]), abs_basis_closed_bps=np.array([]), rv_24h_now=0.0, horizon_h=24)
    presets = build_presets(inp)
    assert {p.id for p in presets} == {"liquidity_drought"}


def test_block_bootstrap_shapes_and_simulation():
    rng = np.random.default_rng(1)
    rets = rng.normal(0, 0.002, 2000)
    paths = block_bootstrap_paths(rets, 48, n_paths=100, block_h=6, seed=3)
    assert paths.shape == (100, 48)
    mc = simulate(1.0, rets, 48, n_paths=2000, seed=3)
    assert mc.p5 < mc.p50 < mc.p95 and mc.expected_shortfall_5_pct <= mc.p5
    assert mc.drawdown_p5 <= 0.0 and 0.0 <= mc.prob_loss_gt[2.0] <= 1.0
    # A short position's terminal distribution is the mirror image.
    mc_s = simulate(-1.0, rets, 48, n_paths=2000, seed=3)
    assert abs(mc_s.p50 + mc.p50) < 0.5


def test_hourly_log_returns_filters():
    idx = pd.date_range(T0, periods=10, freq="1h", tz="UTC")
    f = pd.DataFrame({"spot_close": np.linspace(100, 109, 10), "spot_filled": [False] * 8 + [True, True], "is_closed": [True] * 5 + [False] * 5}, index=idx)
    assert len(hourly_log_returns(f, closed_only=False)) == 7
    assert len(hourly_log_returns(f, closed_only=True)) == 4


def test_reverse_stress_finds_breakeven_move():
    pos = Position("TSLA", Side.LONG, notional_quote=500.0, entry_price=100.0)
    move = reverse_stress(pos, book=book(depth_each=50), taker_fee=0.001, target_loss_pct=5.0, horizon_h=48)
    assert move is not None and -5.0 < move < -4.5  # slightly less than 5% because exit costs add to the loss
    imp = apply_scenario(pos, Scenario(id="v", name="v", severity=Severity.MILD, horizon_h=48, price_move_pct=move), book=book(depth_each=50), taker_fee=0.001)
    assert abs(imp.total_pct_of_notional + 5.0) < 0.05


def test_the_monte_carlo_does_not_ship_its_paths():
    """Ten thousand raw path values were 186 KB of a 320 KB response, on every analysis,
    for a chart that draws forty bars."""
    import json

    from nightwatch.stress.montecarlo import HISTOGRAM_BINS

    rng = np.random.default_rng(5)
    mc = simulate(1.0, rng.normal(0, 0.01, 4000), 24, n_paths=2000, seed=3)
    d = mc.to_dict()
    assert "terminal_ret_pct" not in d and "worst_drawdown_pct" not in d
    hist = d["terminal_hist"]
    assert len(hist["counts"]) == HISTOGRAM_BINS and len(hist["edges"]) == HISTOGRAM_BINS + 1
    assert sum(hist["counts"]) == len(mc.terminal_ret_pct)
    assert d["p5"] == mc.p5 and d["drawdown_p5"] == mc.drawdown_p5
    assert len(json.dumps(d)) < 4000


def test_earnings_presets_only_when_a_report_can_hit_the_hold():
    """An earnings gap a month away was being quoted as the worst case, and as the case
    against, on nights with no report anywhere near them."""
    import numpy as np

    from nightwatch.stress.scenarios import EmpiricalInputs, build_presets, earnings_in_window

    def inp(to, since, h=12.0):  # noqa: ANN001, ANN202
        return EmpiricalInputs(closed_window_ret_pct=np.array([]), earnings_gap_pct=np.array([-9.0, -3.0, 2.0, 4.0, -1.0]),
                               abs_basis_closed_bps=np.array([]), rv_24h_now=0.0, horizon_h=h,
                               hours_to_earnings=to, hours_since_earnings=since)

    ids = lambda i: {p.id for p in build_presets(i)}  # noqa: E731
    assert "earnings_gap_worst" not in ids(inp(720.0, 720.0)), "a month away"
    assert "earnings_gap_worst" in ids(inp(10.0, 720.0)), "due inside the hold"
    assert "earnings_gap_worst" in ids(inp(30.0, 720.0)), "an after-close report priced at the next open, within a day"
    assert "earnings_gap_worst" in ids(inp(720.0, 8.0)), "out last night, and the market has not opened on it"
    assert earnings_in_window(inp(None, None)), "an unknown date cannot rule it out"
    assert "earnings_gap_worst" in ids(inp(80.0, 720.0, h=102.0)), "a weekend hold that spans the report"
