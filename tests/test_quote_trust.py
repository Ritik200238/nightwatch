"""Token quote against the real open: the pairing of hours, opens and closes must be right."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nightwatch.stress import quote_trust as qt


def world(token_at_open_ratio: float, days: int = 260):
    """Stock closes 100, opens 101 each day; the token quotes 101 * ratio all night."""
    ys, ss = [], []
    for d in pd.bdate_range("2025-03-03", periods=days):
        base = pd.Timestamp(d.date(), tz="America/New_York")
        for h in range(9, 16):  # 09:30 .. 15:30 bars
            t = (base + pd.Timedelta(hours=h, minutes=30)).tz_convert("UTC")
            ys.append(("ABC", int(t.timestamp() * 1000), 101.0 if h == 9 else 100.0, 100.0))
        for h in range(0, 24):
            t = (base + pd.Timedelta(hours=h)).tz_convert("UTC")
            ss.append(("ABC", int(t.timestamp() * 1000), 101.0 * token_at_open_ratio))
    return pd.DataFrame(ys, columns=["s", "ts", "o", "c"]), pd.DataFrame(ss, columns=["t", "ts", "o"])


def test_a_token_quoting_the_real_open_has_zero_error_and_the_last_close_is_off_by_the_gap():
    y, s = world(1.0)
    df = qt.observations(y, s)
    assert len(df) > 1000
    assert df["tok"].max() < 1e-6
    assert abs(df["naive"].median() - np.log(101 / 100) * 1e4) < 1e-6


def test_hours_before_open_run_from_the_half_hour_back_to_the_close_and_never_past_it():
    y, s = world(1.0, days=40)
    df = qt.observations(y, s)
    assert df["hb"].min() == 0.5 and df["hb"].max() <= 80


def test_a_token_that_is_off_is_scored_by_how_far_off_and_loses_to_the_last_close_when_further():
    y, s = world(1.05)  # 5% above the real open: 488 bps, worse than the 99.5 bps last-close error
    r = qt.summarize(qt.observations(y, s))
    near = r["pooled"][0]
    assert 480 < near["token_bps"] < 495 and near["token_closer"] == 0.0 and near["last_close_bps"] < 100


def test_bins_with_too_few_rows_are_not_reported():
    y, s = world(1.0, days=3)
    assert qt.summarize(qt.observations(y, s))["pooled"] == []
