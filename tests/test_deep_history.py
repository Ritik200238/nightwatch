"""The long record, on daily bars whose answer is known."""

import json

import numpy as np
import pandas as pd

from nightwatch.stress import deep_history as dh


def frame(days, opens, closes):
    return pd.DataFrame({"ts": pd.to_datetime(days, utc=True), "open": opens, "close": closes})


def test_a_weekend_gap_is_split_from_an_overnight_gap_and_measured_against_the_last_close():
    # Thu, Fri, Mon, Tue. Friday closes 100; Monday opens 90 (-10%) and closes 99; Tuesday opens 100.98 (+2% on 99).
    d = frame(["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"], [100, 100, 90, 100.98], [100, 100, 99, 101])
    w = dh.window_returns(d)
    assert list(w["weekend_gap"].round(6)) == [-10.0]
    assert list(w["overnight_gap"].round(6)) == [0.0, 2.0]  # Thu->Fri flat, Mon->Tue +2%
    assert list(w["weekend_close"].round(6)) == [-1.0]  # Fri 100 -> Mon close 99
    assert w["one_day"].shape[0] == 3
    assert w["five_day"].empty  # only four sessions


def test_a_holiday_weekend_counts_as_a_weekend():
    # Friday then Tuesday (Monday holiday): four calendar days apart.
    d = frame(["2024-05-24", "2024-05-28"], [100, 95], [100, 96])
    w = dh.window_returns(d)
    assert list(w["weekend_gap"].round(6)) == [-5.0]
    assert w["overnight_gap"].empty


def test_a_midweek_holiday_is_an_ordinary_night():
    d = frame(["2024-07-03", "2024-07-05"], [100, 98], [100, 99])  # Thursday 4 July shut
    w = dh.window_returns(d)
    assert w["weekend_gap"].empty
    assert list(w["overnight_gap"].round(6)) == [-2.0]


def test_bars_with_a_non_positive_price_are_dropped_and_nothing_else_is():
    d = frame(["2024-01-02", "2024-01-03", "2024-01-04"], [100, 0, 50], [100, 100, 50])
    assert dh.window_returns(d)["one_day"].shape[0] == 1  # the zero-open bar is dropped, leaving one move: 100 -> 50


def uniform_window(lo=-10.0, hi=10.0, n=4000):
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    return dh.summarize(pd.Series(np.linspace(lo, hi, n), index=idx))


def test_share_beyond_reads_the_right_tail_for_each_side():
    w = uniform_window()
    assert abs(dh.share_beyond(w, -9.0, "long") - 0.05) < 0.01  # a long loses below -9
    assert abs(dh.share_beyond(w, +9.0, "short") - 0.05) < 0.01  # a short loses above +9
    assert dh.share_beyond(w, -20.0, "long") == 0.0
    assert dh.share_beyond(w, +20.0, "long") == 1.0
    assert dh.share_beyond(w, -20.0, "short") == 1.0


def test_share_beyond_grows_as_the_line_moves_in():
    w = uniform_window()
    shares = [dh.share_beyond(w, x, "long") for x in (-9.5, -8, -5, -1)]
    assert shares == sorted(shares)


def test_adverse_tail_is_the_lower_for_a_long_and_the_upper_for_a_short_and_keeps_the_dated_extremes():
    w = uniform_window()
    lo, hi = dh.adverse(w, "long"), dh.adverse(w, "short")
    assert lo["p5"] < 0 < hi["p5"]
    assert lo["worst"] == -10.0 and hi["worst"] == 10.0
    assert lo["worst_events"][0]["pct"] == -10.0 and hi["worst_events"][0]["pct"] == 10.0
    assert len(lo["worst_events"][0]["date"]) == 10


def test_the_window_nearest_the_hold_is_chosen():
    assert dh.pick_window(24) == "one_day"
    assert dh.pick_window(60) == "weekend_close"
    assert dh.pick_window(110) == "five_day"
    assert dh.pick_window(None) == "one_day"


def test_a_thin_history_says_nothing_rather_than_a_number():
    idx = pd.date_range("2024-01-02", periods=30, freq="B")
    d = pd.DataFrame({"ts": idx.tz_localize("UTC"), "open": np.linspace(100, 110, 30), "close": np.linspace(100, 110, 30)})
    assert dh.summarize_ticker(d) is None


def test_for_ticker_answers_from_the_committed_file_and_is_honest_when_it_has_nothing(tmp_path, monkeypatch):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2005-01-03", periods=3000)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, idx.size)))
    d = pd.DataFrame({"ts": idx.tz_localize("UTC"), "open": px * (1 + rng.normal(0, 0.004, idx.size)), "close": px})
    s = dh.summarize_ticker(d)
    p = tmp_path / "deep.json"
    p.write_text(json.dumps({"ran_at": "2026-10-08T00:00:00+00:00", "source": "test", "tickers": {"ABC": s}, "pooled": {}}))
    monkeypatch.setattr(dh, "RESULT_PATH", p)

    out = dh.for_ticker("ABC", side="long", horizon_h=60, line_pct=-3.0)
    assert out["available"] and out["chosen"] == "weekend_close" and 0.0 < out["share_beyond"] < 1.0
    assert out["sessions"] == 3000 and out["first"] == "2005-01-03"
    assert set(out["windows"]) >= {"one_day", "weekend_gap", "overnight_gap"}
    assert dh.for_ticker("ZZZ")["available"] is False
    monkeypatch.setattr(dh, "RESULT_PATH", tmp_path / "missing.json")
    assert dh.for_ticker("ABC")["available"] is False


def test_a_spin_off_day_and_a_reused_ticker_are_left_out_of_every_window_and_nothing_else():
    idx = pd.bdate_range("2024-01-02", periods=20)
    px = np.full(idx.size, 100.0)
    px[10:] = 60.0  # a 40% "fall" on the 11th session that no holder suffered
    d = pd.DataFrame({"ts": idx.tz_localize("UTC"), "open": px, "close": px})
    raw = dh.window_returns(d)
    assert raw["one_day"].min() == -40.0 and raw["five_day"].lt(-39).sum() == 5
    fixed = dh.window_returns(d, {"breaks": [str(idx[10].date())]})
    assert fixed["one_day"].min() == 0.0 and fixed["five_day"].min() == 0.0  # every window that crossed it is gone
    assert len(fixed["one_day"]) == len(raw["one_day"]) - 1 and len(fixed["five_day"]) == len(raw["five_day"]) - 5
    since = dh.window_returns(d, {"since": str(idx[12].date())})
    assert since["one_day"].index.min() > idx[12] and since["one_day"].min() == 0.0
