"""The stop-rule comparison: known answers on made-up history, and the empty case."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nightwatch.journal.stop_benchmark import MIN_PER_TICKER, compare


def _rows(seed: int = 3, n: int = 400) -> pd.DataFrame:
    """A calm stock (1% moves) and a wild one (4% moves). A one-in-twenty line drawn for each
    from its own spread is crossed about 5% of the time on both; a flat 3% is not."""
    rng = np.random.default_rng(seed)
    parts = []
    for ticker, sd in (("CALM", 1.0), ("WILD", 4.0)):
        r = rng.normal(0.0, sd, n)
        line = -1.645 * sd
        parts.append(pd.DataFrame({
            "ticker": ticker,
            "as_of": pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC"),
            "r": r, "a5": line, "p5": line, "base": -1.645 * 2.0,
        }))
    return pd.concat(parts, ignore_index=True)


def _arm(out: dict, key: str) -> dict:
    return next(a for a in out["arms"] if a["key"] == key)


def test_the_desk_line_is_even_across_stocks_and_a_flat_stop_is_not():
    out = compare(_rows())
    desk, flat = _arm(out, "desk"), _arm(out, "flat3")
    assert 0.03 < desk["ticker_min"] <= desk["ticker_max"] < 0.08
    assert flat["ticker_min"] < 0.01 and flat["ticker_max"] > 0.2
    assert flat["least_crossed"] == "CALM" and flat["most_crossed"] == "WILD"


def test_the_tuned_flat_stop_matches_the_desk_overall_and_still_spreads_by_stock():
    out = compare(_rows())
    desk, tuned = _arm(out, "desk"), _arm(out, "flat_tuned")
    assert abs(tuned["overall"] - desk["overall"]) < 0.01
    assert tuned["ticker_max"] - tuned["ticker_min"] > desk["ticker_max"] - desk["ticker_min"]
    assert tuned["level_pct"] < 0


def test_counts_and_arms_are_reported():
    out = compare(_rows(n=400))
    assert out["n"] == 800 and out["tickers"] == 2 and out["nights"] == 400
    assert [a["key"] for a in out["arms"]] == ["desk", "stated", "base", "flat2", "flat3", "flat5", "flat_tuned"]


def test_the_base_arm_is_left_out_when_most_rows_lack_it():
    rows = _rows()
    rows.loc[rows.index[: int(len(rows) * 0.6)], "base"] = np.nan
    assert "base" not in [a["key"] for a in compare(rows)["arms"]]


def test_a_stock_with_too_few_forecasts_is_left_out_of_the_by_stock_columns():
    rows = _rows()
    few = rows[rows["ticker"] == "WILD"].head(MIN_PER_TICKER - 1)
    out = compare(pd.concat([rows[rows["ticker"] == "CALM"], few], ignore_index=True))
    assert _arm(out, "flat3")["most_crossed"] == "CALM"  # the thin stock cannot be the extreme


def test_an_empty_history_gives_no_arms_instead_of_failing():
    assert compare(pd.DataFrame())["arms"] == []
