from types import SimpleNamespace

import pandas as pd

from nightwatch.analog.outcomes import weekend_history
from nightwatch.api.intake import weekend_line
from nightwatch.time_utils import Session


def _frame(weekend_moves: list[float]) -> pd.DataFrame:
    """Hourly bars: a regular Friday close, a closed weekend, then a regular Monday price
    that moved by the given percent, once per weekend."""
    rows, price, ts = [], 100.0, pd.Timestamp("2025-11-07 20:00", tz="UTC")  # a Friday
    for move in weekend_moves:
        rows.append((ts, price, Session.REGULAR.value))
        for h in range(1, 66):
            rows.append((ts + pd.Timedelta(hours=h), price, Session.WEEKEND.value))
        price *= 1 + move / 100
        rows.append((ts + pd.Timedelta(hours=66), price, Session.REGULAR.value))
        ts += pd.Timedelta(days=7)
    f = pd.DataFrame(rows, columns=["ts", "spot_close", "session"]).set_index("ts")
    return f


def test_weekend_history_reads_friday_close_to_monday_price_for_each_side():
    moves = [-8.0] + [1.0] * 19 + [-2.0] * 20
    long_ = weekend_history(_frame(moves), "long")
    assert long_["n"] == 40 and abs(long_["worst_pct"] + 8.0) < 1e-9 and long_["p5_pct"] < -1.9
    short = weekend_history(_frame(moves), "short")
    assert abs(short["worst_pct"] + 1.0) < 1e-9  # a rising weekend is the short's loss


def test_too_few_weekends_says_nothing():
    assert weekend_history(_frame([1.0] * 5), "long") is None


def test_the_line_says_which_weekend_and_marks_the_history_raw():
    """On a Tuesday, "over the weekend" held from now is six days; a judge read 152h as a
    clock bug. The reply says what was measured and what past weekends did."""
    report = SimpleNamespace(
        ticket=SimpleNamespace(ticker="TSLA"),
        weekend_only={"n": 46, "p5_pct": -4.2, "worst_pct": -9.1, "today": "Tuesday", "hold_from_now_h": 152.0},
    )
    en = weekend_line(report, "en")
    assert "today is Tuesday" in en and "6.3 days" in en and "46 weekends" in en and "4.2%" in en and "not calibrated" in en
    zh = weekend_line(report, "zh")
    assert "周二" in zh and "46 个周末" in zh and "4.2%" in zh and "未经校准" in zh
    assert weekend_line(SimpleNamespace(weekend_only=None), "en") is None


def test_a_holiday_closure_that_does_not_start_on_friday_is_not_a_weekend():
    f = _frame([-1.0] * 12)
    extra = _frame([-20.0]).copy()
    extra.index = extra.index + pd.Timedelta(days=7 * 12 - 2)  # the same shape, starting on a Wednesday
    both = pd.concat([f, extra]).sort_index()
    assert weekend_history(both, "long")["worst_pct"] > -2.0
