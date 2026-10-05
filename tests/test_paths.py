"""Drawing the retrieved scenarios.

The chart is only worth having if the lines are the real windows and the stop count is
the number a real stop would have produced. Both are easy to get subtly wrong in ways
nobody notices on a picture, so they are pinned here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nightwatch.analog import paths as mod

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class FakeMatch:
    ts: datetime
    ticker: str
    distance: float = 1.0
    distance_percentile: float = 50.0


def frame(closes: list[float], *, lows: list[float] | None = None, highs: list[float] | None = None, start: datetime = T0) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(hours=i) for i in range(len(closes))])
    return pd.DataFrame(
        {
            "spot_close": closes,
            "spot_low": lows if lows is not None else closes,
            "spot_high": highs if highs is not None else closes,
        },
        index=idx,
    )


def test_a_path_is_the_move_from_its_own_entry():
    f = frame([100.0, 101.0, 99.0, 102.0, 103.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=4)
    assert out is not None and len(out.paths) == 1
    v = out.paths[0].values
    assert v[0] == 0.0  # entry is always the zero point
    assert len(v) == len(out.hours) == 5
    assert v[1] == pytest.approx(1.0) and v[2] == pytest.approx(-1.0) and v[-1] == pytest.approx(3.0)


def test_each_analog_is_measured_from_its_own_entry_not_a_shared_one():
    """Two moments at different price levels with the same shape must draw the same."""
    f = frame([100.0, 102.0, 50.0, 51.0])
    out = mod.build([FakeMatch(T0, "X"), FakeMatch(T0 + timedelta(hours=2), "X")], {"X": f}, horizon_h=1)
    assert out is not None and len(out.paths) == 2
    assert out.paths[0].values == out.paths[1].values  # +2% both


def test_a_window_running_past_the_data_is_dropped_and_counted():
    """Drawing it short would read as a flat ending, which is a lie about the outcome."""
    f = frame([100.0, 101.0, 102.0])
    out = mod.build([FakeMatch(T0, "X"), FakeMatch(T0 + timedelta(hours=2), "X")], {"X": f}, horizon_h=2)
    assert out is not None
    assert len(out.paths) == 1 and out.n_dropped == 1


def test_an_analog_from_a_token_we_have_no_frame_for_is_dropped():
    f = frame([100.0, 101.0, 102.0])
    out = mod.build([FakeMatch(T0, "X"), FakeMatch(T0, "GONE")], {"X": f}, horizon_h=2)
    assert out is not None and len(out.paths) == 1 and out.n_dropped == 1


def test_the_stop_is_judged_on_the_low_not_on_the_drawn_line():
    """The path is closes. A stop is filled against the low, so a window that dips and
    recovers inside an hour counts - drawing it and counting it are different jobs."""
    # Closes never fall below -1%; the low on the second bar reaches -6%.
    f = frame([100.0, 99.0, 99.5, 100.5], lows=[100.0, 94.0, 99.0, 100.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=3, side="long", stop_price=95.0, entry_price=100.0)
    assert out is not None
    assert out.stop_pct is not None and abs(out.stop_pct - (-5.0)) < 1e-9
    assert out.stopped == 1
    assert out.paths[0].stopped_at_h == 1.0
    assert min(out.paths[0].values) > -5.0  # the drawn line alone would have missed it


def test_a_window_that_never_reaches_the_stop_reports_nothing():
    f = frame([100.0, 99.0, 99.5, 100.5], lows=[100.0, 98.0, 99.0, 100.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=3, side="long", stop_price=95.0, entry_price=100.0)
    assert out is not None and out.stopped == 0 and out.paths[0].stopped_at_h is None


def test_a_short_is_stopped_by_the_high_above_its_entry():
    f = frame([100.0, 101.0, 100.5], highs=[100.0, 106.0, 101.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=2, side="short", stop_price=105.0, entry_price=100.0)
    assert out is not None
    assert out.stop_pct is not None and out.stop_pct > 0  # a short's stop sits above entry
    assert out.stopped == 1 and out.paths[0].stopped_at_h == 1.0


def test_no_stop_means_no_line_and_no_count():
    f = frame([100.0, 99.0, 98.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=2)
    assert out is not None and out.stop_pct is None and out.stopped == 0
    assert all(p.stopped_at_h is None for p in out.paths)


def test_the_fan_is_the_percentiles_of_the_paths_it_is_drawn_over():
    rng = np.random.default_rng(0)
    closes = [100.0]
    for _ in range(200):
        closes.append(closes[-1] * float(np.exp(rng.normal(0, 0.01))))
    f = frame(closes)
    matches = [FakeMatch(T0 + timedelta(hours=i), "X") for i in range(0, 150, 5)]
    out = mod.build(matches, {"X": f}, horizon_h=6)
    assert out is not None and len(out.paths) > 20
    stacked = np.vstack([p.values for p in out.paths])
    for i in range(len(out.hours)):
        assert abs(out.fan["p5"][i] - float(np.percentile(stacked[:, i], 5))) < 1e-9
        assert out.fan["p5"][i] <= out.fan["p25"][i] <= out.fan["p50"][i] <= out.fan["p75"][i] <= out.fan["p95"][i]
    # Every path starts at zero, so the fan has to be pinched shut at entry and open later.
    assert out.fan["p95"][0] == out.fan["p5"][0] == 0.0
    assert out.fan["p95"][-1] > out.fan["p5"][-1]


def test_a_long_horizon_is_drawn_with_a_bounded_number_of_points():
    """Forty paths at hourly resolution over a long weekend is a lot of JSON for a
    picture; the grid is capped and shared so the axis stays comparable."""
    f = frame([100.0 + i * 0.1 for i in range(200)])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=120)
    assert out is not None
    assert len(out.hours) == mod.GRID_POINTS
    assert out.hours[0] == 0.0 and out.hours[-1] == 120.0
    assert len(out.paths[0].values) == mod.GRID_POINTS


def test_nothing_drawable_returns_nothing_rather_than_an_empty_chart():
    assert mod.build([], {}, horizon_h=4) is None
    f = frame([100.0, 101.0])
    assert mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=0) is None
    assert mod.build([FakeMatch(T0 + timedelta(hours=50), "X")], {"X": f}, horizon_h=4) is None


def test_the_serialised_form_is_small_enough_to_ship_in_a_report():
    rng = np.random.default_rng(3)
    closes = [100.0]
    for _ in range(400):
        closes.append(closes[-1] * float(np.exp(rng.normal(0, 0.01))))
    f = frame(closes)
    matches = [FakeMatch(T0 + timedelta(hours=i * 8), "X", distance=float(i)) for i in range(40)]
    out = mod.build(matches, {"X": f}, horizon_h=60)
    assert out is not None and len(out.paths) == 40
    import json

    body = json.dumps(out.to_dict())
    assert len(body) < 30_000, f"{len(body)} bytes of paths is too much of a report"
    # Values are rounded on the way out; a path of full-precision floats is twice the size.
    assert all(len(str(v).split(".")[-1]) <= 3 for v in out.to_dict()["paths"][0]["values"])


def test_paths_are_ranked_against_each_other_not_against_all_of_history():
    """The engine's distance_percentile is against every candidate hour searched, so
    all forty retrieved analogs land in its bottom fraction and look identical. The
    chart colours the near half against the far half, which needs a rank within the
    drawn set - getting this wrong paints every line the same colour."""
    f = frame([100.0 + i * 0.1 for i in range(60)])
    # Every match reports the same near-zero global percentile, as the engine's would.
    matches = [FakeMatch(T0 + timedelta(hours=i * 5), "X", distance=float(10 - i), distance_percentile=0.2) for i in range(8)]
    out = mod.build(matches, {"X": f}, horizon_h=4)
    assert out is not None and len(out.paths) == 8

    ranks = [p.rank for p in out.paths]
    assert min(ranks) == 0.0 and max(ranks) == 1.0
    assert len(set(ranks)) == 8, "every path needs its own rank, or the split is arbitrary"
    # The closest match by distance must be rank 0, the furthest rank 1.
    closest = min(out.paths, key=lambda p: p.distance)
    furthest = max(out.paths, key=lambda p: p.distance)
    assert closest.rank == 0.0 and furthest.rank == 1.0
    # And the split the chart draws has to actually split.
    assert 0 < sum(1 for p in out.paths if p.rank < 0.5) < len(out.paths)
    # The global percentile is left alone; it means something else and is still reported.
    assert all(p.distance_percentile == 0.2 for p in out.paths)


def test_a_single_path_is_ranked_without_dividing_by_zero():
    f = frame([100.0, 101.0, 102.0])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=2)
    assert out is not None and out.paths[0].rank == 0.0


def test_worst_adverse_is_the_low_for_a_long_and_the_high_for_a_short():
    f = frame([100.0, 99.0, 101.0, 100.0], lows=[100.0, 94.0, 99.0, 100.0], highs=[100.0, 100.0, 108.0, 100.0])
    long_ = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=3, side="long")
    short = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=3, side="short")
    assert long_ is not None and short is not None
    assert long_.paths[0].worst_adverse_pct == pytest.approx(6.0)
    assert short.paths[0].worst_adverse_pct == pytest.approx(8.0)
    assert long_.paths[0].to_dict()["worst_adverse_pct"] == 6.0


def test_a_window_that_only_moves_in_favour_has_zero_worst_adverse_not_a_negative():
    f = frame([100.0, 101.0, 102.0], lows=[100.0, 100.5, 101.5])
    out = mod.build([FakeMatch(T0, "X")], {"X": f}, horizon_h=2, side="long")
    assert out is not None and out.paths[0].worst_adverse_pct == 0.0


@pytest.mark.parametrize("side", ["long", "short"])
def test_worst_adverse_agrees_exactly_with_the_liquidated_count(side):
    """One set of paths must answer "liquidated at distance d" for every d, and for the
    ticket's own d it must be the very count the report already prints."""
    rng = np.random.default_rng(7)
    n_bars, n_matches = 60, 25
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n_bars)))
    lows = closes * (1 - rng.uniform(0, 0.02, n_bars))
    highs = closes * (1 + rng.uniform(0, 0.02, n_bars))
    f = frame(list(closes), lows=list(lows), highs=list(highs))
    matches = [FakeMatch(T0 + timedelta(hours=i), "X") for i in range(n_matches)]
    for d in (0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 15.0):
        entry = 100.0
        liq = entry * (1 - d / 100) if side == "long" else entry * (1 + d / 100)
        out = mod.build(matches, {"X": f}, horizon_h=12, side=side, entry_price=entry, liquidation_price=liq)
        assert out is not None and len(out.paths) == n_matches
        by_paths = sum(1 for p in out.paths if p.worst_adverse_pct is not None and p.worst_adverse_pct >= d)
        assert by_paths == out.liquidated, (side, d)


def test_a_stop_on_the_wrong_side_is_not_counted_as_hit():
    """A long with its stop above entry was "hit" by every path from the first bar: 80 of 80."""
    import pandas as pd

    from nightwatch.analog import paths as p

    idx = pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC")
    frame = pd.DataFrame({"spot_close": 100.0, "spot_low": 99.0, "spot_high": 101.0}, index=idx)

    class M:
        ticker, distance, distance_percentile = "TSLA", 0.1, 0.1
        ts = idx[0].to_pydatetime()

    wrong = p.build([M()], {"TSLA": frame}, horizon_h=6, side="long", stop_price=120.0, entry_price=100.0)
    assert wrong is not None and wrong.stop_pct is None and wrong.stopped == 0
    right = p.build([M()], {"TSLA": frame}, horizon_h=6, side="long", stop_price=99.5, entry_price=100.0)
    assert right.stop_pct == pytest.approx(-0.5) and right.stopped == 1
    short_wrong = p.build([M()], {"TSLA": frame}, horizon_h=6, side="short", stop_price=80.0, entry_price=100.0)
    assert short_wrong.stop_pct is None
