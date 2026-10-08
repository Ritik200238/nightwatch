"""How much a token follows the Nasdaq token while the US market is open, and while it is shut.

A tokenized stock trades all week. While the US market is open it is held to the real stock
by arbitrage and moves with the index. When the market is shut nobody can arbitrage it, so
how much it still moves with the market is a measurement, not an assumption: it might keep
following (the index token and the stock token trade the same crypto-venue flow) or it
might drift on its own. A position sized with the open-hours beta is wrong by exactly the
difference.

Measured as the slope of the token's hourly log return on the QQQ token's hourly log
return, separately for hours the US regular session is open and hours it is not. The
interval comes from resampling whole calendar days (hours in one day are not independent
draws), and the difference between the two slopes is resampled together so it is a paired
comparison.

Two controls travel with it:

* TQQQ and SQQQ are three-times and minus-three-times funds on the same index. Their slope
  should sit near +3 and -3 in both regimes if the method is sound. If it did not, the
  difference found for ordinary stocks would be a property of the method, not the stock.
* QQQ against itself is exactly 1 in both, by construction, and is left out of the table.

The result is a committed file (``session_beta.json``) written by
``scripts/session_beta_sweep.py`` from the hourly bars the desk already stores. It
describes the past sample and never feeds a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RESULT_PATH = Path(__file__).with_name("session_beta.json")
PROXY = "QQQ"
CONTROLS = ("TQQQ", "SQQQ")
MIN_HOURS = 300  # fewer hours in a regime and the slope is not reported
DRAWS = 400
SEED = 20261008
_CACHE: dict[str, Any] = {}


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    vx = float(np.var(x))
    return float(np.cov(x, y, bias=True)[0, 1] / vx) if vx > 0 else float("nan")


def _paired(frame: pd.DataFrame) -> dict[str, Any] | None:
    """``frame`` has ``x`` (proxy return), ``y`` (token return), ``closed`` (bool), ``day``."""
    op, cl = frame[~frame["closed"]], frame[frame["closed"]]
    if len(op) < MIN_HOURS or len(cl) < MIN_HOURS:
        return None
    b_open = _slope(op["x"].to_numpy(), op["y"].to_numpy())
    b_closed = _slope(cl["x"].to_numpy(), cl["y"].to_numpy())
    if not (np.isfinite(b_open) and np.isfinite(b_closed)):
        return None

    days = frame["day"].unique()
    groups = {d: g for d, g in frame.groupby("day")}
    rng = np.random.default_rng(SEED)
    bo, bc = [], []
    for _ in range(DRAWS):
        pick = rng.choice(len(days), size=len(days), replace=True)
        s = pd.concat([groups[days[i]] for i in pick], ignore_index=True)
        o, c = s[~s["closed"]], s[s["closed"]]
        if len(o) < 50 or len(c) < 50:
            continue
        bo.append(_slope(o["x"].to_numpy(), o["y"].to_numpy()))
        bc.append(_slope(c["x"].to_numpy(), c["y"].to_numpy()))
    bo, bc = np.array(bo), np.array(bc)
    ok = np.isfinite(bo) & np.isfinite(bc)
    bo, bc = bo[ok], bc[ok]
    if len(bo) < 50:
        return None

    def ci(v: np.ndarray) -> list[float]:
        return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]

    return {
        "open": {"beta": b_open, "ci": ci(bo), "n": int(len(op)), "corr": float(np.corrcoef(op["x"], op["y"])[0, 1])},
        "closed": {"beta": b_closed, "ci": ci(bc), "n": int(len(cl)), "corr": float(np.corrcoef(cl["x"], cl["y"])[0, 1])},
        "diff": {"est": b_closed - b_open, "ci": ci(bc - bo)},
    }


def summarize(closes: dict[str, pd.Series], closed_flag: pd.Series, proxy: str = PROXY) -> dict[str, Any]:
    """Per token: slope on the proxy while open and while shut, with intervals.

    ``closes`` maps ticker to hourly close indexed by bar start (UTC); ``closed_flag`` is a
    bool series on the same kind of index, True where the US regular session is not open."""
    if proxy not in closes:
        raise ValueError(f"no hourly bars for the proxy {proxy}")
    out: dict[str, Any] = {}
    px = np.log(closes[proxy].where(closes[proxy] > 0)).diff()
    for t, c in closes.items():
        if t == proxy:
            continue
        ry = np.log(c.where(c > 0)).diff()
        f = pd.DataFrame({"x": px, "y": ry}).join(closed_flag.rename("closed"), how="inner").dropna()
        # Only one-hour steps: a gap in either series makes the "hourly" return a multi-hour one.
        idx = f.index.to_series().diff() == pd.Timedelta(hours=1)
        f = f[idx.to_numpy()]
        if f.empty:
            continue
        f = f.assign(day=f.index.normalize())
        r = _paired(f)
        if r is not None:
            out[t] = r
    return out


def load_result() -> dict[str, Any] | None:
    try:
        key = (str(RESULT_PATH), RESULT_PATH.stat().st_mtime_ns)
        if _CACHE.get("key") != key:
            _CACHE["key"], _CACHE["val"] = key, json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        return _CACHE["val"]
    except (OSError, ValueError):
        return None


def for_ticker(ticker: str) -> dict[str, Any]:
    res = load_result()
    base: dict[str, Any] = {"ticker": ticker, "available": False}
    if not res:
        return base
    if ticker == res.get("proxy"):
        return {**base, "reason": "this is the market proxy itself"}
    t = (res.get("tickers") or {}).get(ticker)
    if not t:
        return {**base, "reason": "too few hourly bars in one of the two regimes for this ticker", "ran_at": res.get("ran_at")}
    d = t["diff"]
    distinct = not (d["ci"][0] <= 0 <= d["ci"][1])
    return {
        **base, "available": True, "proxy": res.get("proxy"), "open": t["open"], "closed": t["closed"], "diff": d,
        "distinguishable": distinct, "controls": {c: res["tickers"].get(c) for c in CONTROLS if c in res.get("tickers", {})},
        "since": res.get("since"), "until": res.get("until"), "ran_at": res.get("ran_at"),
    }
