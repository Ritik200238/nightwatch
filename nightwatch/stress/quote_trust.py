"""How far the token's quote is from the stock's real opening print, by how long before the open.

Overnight and over a weekend there is no stock price to check a token against. The only
honest test is afterwards: take the token's quote at some hour of the night, wait for the
US market to open, and compare it with the real opening print. The alternative anyone can
use for free is "the stock will open where it last closed". The question for a trader at
three in the morning is then whether the token's quote is a better guess at the open than
the last close, and by how much, at that hour.

Measured on every US session in the stored hourly bars, for every token the desk lists:

* the real open is the Yahoo 09:30 bar's open; the last close is the previous session's last
  bar's close (an early close is read as it is);
* the token quote is the Bitget spot hourly bar's open at each whole hour between the 16:00 ET
  close and the open, bucketed by how many hours remain before the open;
* error is the absolute log difference in basis points.

The 95% interval resamples whole nights (a night is one token and one session), because the
hours inside one night share a single opening print and are not independent draws.

The result is a committed file (``quote_trust.json``) written by ``scripts/quote_trust_sweep.py``.
It describes the past sample and never feeds a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
RESULT_PATH = Path(__file__).with_name("quote_trust.json")
BINS = [0, 1, 2, 3, 4, 6, 8, 12, 24, 48, 72]
COARSE = [0, 2, 6, 12, 24, 72]
MIN_ROWS = 200
DRAWS = 300
SEED = 20261008
_CACHE: dict[str, Any] = {}


def observations(yahoo: pd.DataFrame, spot: pd.DataFrame) -> pd.DataFrame:
    """One row per token quote hour before a real open.

    ``yahoo``: symbol ``s``, ts (ms), open ``o``, close ``c`` hourly stock bars.
    ``spot``: ticker ``t``, ts (ms), open ``o`` hourly token bars."""
    y = yahoo.copy()
    y["et"] = pd.to_datetime(y["ts"], unit="ms", utc=True).dt.tz_convert(ET)
    y["d"] = y["et"].dt.date
    rows: list[tuple] = []
    toks = {t: g.drop_duplicates("ts").set_index("ts")["o"] for t, g in spot.groupby("t")}
    for t, g in y.groupby("s"):
        tok = toks.get(t)
        if tok is None or tok.empty:
            continue
        sess = g.sort_values("ts").groupby("d").agg(open=("o", "first"), close=("c", "last"), first=("et", "first"), last=("et", "last"))
        sess = sess[sess["first"].dt.strftime("%H:%M") == "09:30"]
        for i in range(1, len(sess)):
            prev, cur = sess.iloc[i - 1], sess.iloc[i]
            o, c = float(cur["open"]), float(prev["close"])
            if not (o > 0 and c > 0):
                continue
            close_t = (prev["last"] + pd.Timedelta(minutes=30)).replace(minute=0, second=0)
            open_t = cur["first"]
            span = (open_t - close_t).total_seconds() / 3600.0
            if span <= 0 or span > 80:
                continue  # a bar missing in the middle of a stretch, not a normal close-to-open
            naive = abs(np.log(c / o)) * 1e4
            night = f"{t}|{cur.name}"
            k = close_t + pd.Timedelta(hours=1)
            while k < open_t:
                q = tok.get(int(k.tz_convert("UTC").timestamp() * 1000))
                if q is not None and q > 0:
                    rows.append((t, night, (open_t - k).total_seconds() / 3600.0, abs(np.log(q / o)) * 1e4, naive))
                k += pd.Timedelta(hours=1)
    return pd.DataFrame(rows, columns=["t", "night", "hb", "tok", "naive"])


def _ci_median(vals: np.ndarray, nights: np.ndarray, rng: np.random.Generator) -> list[float]:
    ids, inv = np.unique(nights, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(ids))]
    meds = []
    for _ in range(DRAWS):
        pick = rng.integers(0, len(ids), len(ids))
        idx = np.concatenate([members[i] for i in pick])
        meds.append(float(np.median(vals[idx])))
    return [float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))]


def summarize_bins(df: pd.DataFrame, edges: list[float], rng: np.random.Generator, *, with_ci: bool = True) -> list[dict[str, Any]]:
    out = []
    cut = pd.cut(df["hb"], edges, right=True)
    for b, g in df.groupby(cut, observed=True):
        if len(g) < MIN_ROWS:
            continue
        tok, naive = g["tok"].to_numpy(), g["naive"].to_numpy()
        row: dict[str, Any] = {
            "from_h": float(b.left), "to_h": float(b.right), "n": int(len(g)), "nights": int(g["night"].nunique()),
            "token_bps": float(np.median(tok)), "last_close_bps": float(np.median(naive)),
            "token_closer": float(np.mean(tok < naive)),
        }
        if with_ci:
            nights = g["night"].to_numpy()
            row["token_ci"] = _ci_median(tok, nights, rng)
            row["last_close_ci"] = _ci_median(naive, nights, rng)
        out.append(row)
    return out


def summarize(df: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    per = {t: summarize_bins(g, COARSE, rng, with_ci=False) for t, g in df.groupby("t")}
    return {"pooled": summarize_bins(df, BINS, rng), "by_ticker": {t: v for t, v in per.items() if v}, "rows": int(len(df)),
            "nights": int(df["night"].nunique()), "tickers": int(df["t"].nunique())}


def load_result() -> dict[str, Any] | None:
    try:
        key = (str(RESULT_PATH), RESULT_PATH.stat().st_mtime_ns)
        if _CACHE.get("key") != key:
            _CACHE["key"], _CACHE["val"] = key, json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        return _CACHE["val"]
    except (OSError, ValueError):
        return None


def for_ticker(ticker: str, hours_to_open: float | None = None) -> dict[str, Any]:
    res = load_result()
    base: dict[str, Any] = {"ticker": ticker, "available": False}
    if not res:
        return base
    own = (res.get("by_ticker") or {}).get(ticker)
    pooled = res.get("pooled") or []
    out = {**base, "available": bool(pooled), "pooled": pooled, "own": own, "rows": res.get("rows"), "nights": res.get("nights"),
           "tickers": res.get("tickers"), "since": res.get("since"), "until": res.get("until"), "ran_at": res.get("ran_at")}
    if hours_to_open is not None:
        hit = next((r for r in pooled if r["from_h"] < hours_to_open <= r["to_h"]), None)
        out["now"] = hit
    return out
