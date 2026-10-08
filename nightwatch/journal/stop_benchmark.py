"""The one-in-twenty line against the plain stop rules a trader already uses, on the same history.

For every scored long-side forecast the desk stated a loss line and the return that followed
is known. Each rule below draws its own line for the same forecast, and we count how often the
return went past it:

* the desk line in force at the time (the stated p5 after the tail factors fitted only on
  earlier, already-scored forecasts),
* the stated p5 before that correction,
* the same engine without the similar-moment filter (its unconditioned p5), where stored,
* flat stops of 2%, 3% and 5%,
* a flat stop chosen afterwards so its overall rate equals the desk's. That is the best case
  for a flat rule, because it is given the answer for free.

The point is not only how often but how evenly. A one-in-twenty line should be crossed about
one time in twenty on every stock; a flat stop cannot do that, since the same 3% is a rare
event on an index fund and a routine one on a volatile name. So each rule also reports its
rate by stock (lowest, median, highest, over stocks with enough forecasts).

Read-only. It describes the past sample and never feeds a verdict. ``scripts/benchmark_stops.py``
reaches the same question through the public API for anyone who wants to rerun it.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np
import pandas as pd

MIN_PER_TICKER = 30
FLAT_STOPS = (2.0, 3.0, 5.0)


def _rate(r: np.ndarray, line: np.ndarray | float) -> float:
    return float(np.mean(r < line)) if len(r) else float("nan")


def _by_ticker(frame: pd.DataFrame, line_col: str | None, flat: float | None) -> list[tuple[float, str]]:
    out = []
    for ticker, g in frame.groupby("ticker"):
        if len(g) < MIN_PER_TICKER:
            continue
        r = g["r"].to_numpy(float)
        line = g[line_col].to_numpy(float) if line_col else flat
        out.append((_rate(r, line), str(ticker)))
    return sorted(out)


def _arm(name: str, key: str, frame: pd.DataFrame, line_col: str | None = None, flat: float | None = None) -> dict[str, Any] | None:
    if frame.empty:
        return None
    r = frame["r"].to_numpy(float)
    line = frame[line_col].to_numpy(float) if line_col else flat
    spread = _by_ticker(frame, line_col, flat)
    if not spread:
        return None
    return {
        "key": key,
        "rule": name,
        "n": int(len(frame)),
        "overall": _rate(r, line),
        "ticker_min": spread[0][0],
        "ticker_median": float(statistics.median(x[0] for x in spread)),
        "ticker_max": spread[-1][0],
        "least_crossed": spread[0][1],
        "most_crossed": spread[-1][1],
    }


def compare(rows: pd.DataFrame) -> dict[str, Any]:
    """``rows``: one scored long-side forecast per row with ``ticker``, ``as_of``, ``r`` (the
    realised return, %), ``a5`` (the line in force), ``p5`` (the stated line) and optionally
    ``base`` (the unconditioned line)."""
    if rows.empty:
        return {"n": 0, "nights": 0, "tickers": 0, "arms": []}
    rows = rows.dropna(subset=["r", "a5", "p5"]).copy()
    nights = int(pd.to_datetime(rows["as_of"], utc=True).dt.date.nunique())
    arms: list[dict[str, Any] | None] = [
        _arm("Desk line in force at the time", "desk", rows, line_col="a5"),
        _arm("Stated line, before the tail correction", "stated", rows, line_col="p5"),
    ]
    if "base" in rows and rows["base"].notna().mean() >= 0.5:
        arms.append(_arm("Same engine without the similar-moment filter", "base", rows[rows["base"].notna()], line_col="base"))
    for x in FLAT_STOPS:
        arms.append(_arm(f"Flat {x:g}% stop", f"flat{x:g}", rows, flat=-x))
    desk = arms[0]["overall"] if arms[0] else float("nan")
    r = rows["r"].to_numpy(float)
    if np.isfinite(desk):
        # The level that gives the desk's overall rate, found after the fact on the same sample.
        level = min(((abs(_rate(r, m / 100.0) - desk), m / 100.0) for m in range(-3000, 1)), key=lambda t: t[0])[1]
        tuned = _arm(f"Flat {abs(level):.1f}% stop, chosen afterwards to match the desk", "flat_tuned", rows, flat=level)
        if tuned:
            tuned["level_pct"] = round(level, 2)
            arms.append(tuned)
    return {
        "n": int(len(rows)),
        "nights": nights,
        "tickers": int(rows["ticker"].nunique()),
        "min_per_ticker": MIN_PER_TICKER,
        "arms": [a for a in arms if a],
    }
