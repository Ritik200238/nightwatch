"""What the tokens do while the US cash market is shut, measured.

Two rival products open with a claim about this. One says 56% of an rToken's movement
happens in closed hours; the other says Monday lands closer to Friday's close than to the
weekend. Both are easy to say and neither shows the arithmetic. Nightwatch holds the bars
to test them, so this module asks, and answers from the stored data.

Questions, written down before the sweep was run
------------------------------------------------
Q1. Of a token's price movement, what share happens while the US market is shut, and is
    that more than the closed hours' share of the clock? 80% of the week is closed, so
    "most of the movement is in closed hours" is true of any asset that moves at a steady
    rate. The question that means something is movement *per hour*: does a closed hour
    carry more, the same, or less than an open one?
Q2. Is the token's weekend move informative? Friday 16:00 ET to Monday 09:00 ET the token
    moves by W. The real stock then opens with a gap G from Friday's close. Does W
    predict G in direction and size, and how much of W does the stock's open keep (and
    its close by Monday evening) against how much does it reverse? Scored out of sample
    against predicting no gap at all.
Q3. How thin is the order book when the market is shut (spread and depth at 25 bps),
    against the same token in the US session?

Decisions fixed before looking
------------------------------
* Windows: *open* is 09:00-16:00 ET on a trading day (13:00 on early closes), *closed*
  is everything between two open windows. The open window starts at 09:00, not 09:30,
  because the stored bars are hourly and a bar cannot be cut at half past; the 30
  minutes before the cash open therefore count as "open", which can only make the closed
  share look smaller.
* Movement is measured on window returns (price at the end over price at the start) as
  squared log returns, a variance share. Variance adds across windows of different
  lengths; absolute returns do not (a 65-hour weekend is not 65 one-hour moves), so a
  share of "summed absolute moves" would depend on how the clock is cut, and is not used.
  A window return needs no hourly bar in between, so a quiet token that skips hours is not
  scored as having moved when it next trades. A token's price at a boundary is the last
  bar that had closed by then; its age is recorded.
* Primary population for Q1: every window with a price at both ends. Sensitivities: drop
  windows whose boundary price is more than 3 hours old; drop windows that touch an
  earnings date (an earnings gap is a closed-hours move by construction).
* Primary population for Q2: weekends (last close to next open, any length) where the
  token had traded within 3 hours of both ends. Overnights are run the same way as a
  comparison. A "big" weekend is |W| >= 1%.
* Uncertainty: block bootstrap over calendar weeks, all tokens resampled together,
  blocks of 4 weeks (2,000 draws, percentile 95%). Tokens share the market's weekends,
  so resampling tokens would pretend 24 tokens were 24 independent weekends.
* No p-values and no verdict is entered in the multiple-testing family: this measures,
  it does not add a twelfth test.

Limits that cannot be removed by cleverness
-------------------------------------------
* The history is about 20 months (Jan 2025 on), so a few hundred weekends in total and
  fewer per token. Order-book snapshots exist only since mid September 2026: three
  weekends. Q3 is a description of those weeks, not an estimate of a long-run average.
* The token's last price may be old when the market is shut; that is data too, and
  the age is reported, but a stale boundary price makes W noisy and biases the slope
  toward zero (errors in variables). A slope below 1 is partly that.
* Weekend moves and Monday gaps share the market factor, so W predicting G is partly
  "the market moved". The cross-sectional version (each weekend's mean removed) asks
  whether a token's *own* weekend move carries information.
* An earnings or news shock arriving in a window drives both W and G. It is left in,
  because it is real, and shown with and without.
"""

from __future__ import annotations

import math
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.time_utils import (
    EARLY_CLOSE,
    ET,
    REGULAR_CLOSE,
    UTC,
    is_early_close,
    is_trading_day,
)

KEY = "closed_hours"
TITLE = "What happens to a token while the US market is shut?"

QUESTIONS = (
    "Of a token's movement, how much happens while the US market is shut, and is a closed hour busier or quieter than an open one?",
    "Does the token's Friday-to-Monday move predict the stock's Monday open gap, and how much of it does Monday keep or reverse?",
    "How thin is the token's order book while the market is shut, against the US session?",
)

OPEN_START = time(9, 0)  # see "Decisions fixed before looking"
STALE_H = 3.0
BIG_MOVE = 0.01
BLOCK_WEEKS = 4
BOOT_DRAWS = 2000
MIN_TRAIN_OBS = 60  # pooled weekends needed before the out-of-sample slope is used
MIN_TOKENS_TO_DEMEAN = 6
MIN_WINDOWS_PER_TOKEN = 30
KINDS = ("open", "overnight", "weekend", "holiday")
CLOSED_KINDS = KINDS[1:]
HOUR = timedelta(hours=1)


@contextmanager
def _quiet() -> Iterator[None]:
    """Empty cells (a token with no closed windows yet) are NaN by design, not a warning."""
    with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield


def _ns(idx: pd.DatetimeIndex | pd.Series) -> np.ndarray:
    """Epoch nanoseconds whatever resolution pandas chose for the index."""
    i = pd.DatetimeIndex(idx)
    return i.as_unit("ns").asi8


# ----------------------------------------------------------------------------- windows


def session_windows(first: date, last: date) -> pd.DataFrame:
    """Open windows and the closed windows between them, for trading days in [first, last].

    A closed window runs from one regular close to the next open window's start. It is a
    ``weekend`` if it contains a Saturday, a ``holiday`` if it contains a weekday market
    holiday, an ``overnight`` otherwise. ``week`` is the ISO week of the window's start so
    a Friday close and the weekend after it belong to the same week."""
    days: list[date] = []
    d = first - timedelta(days=10)
    while d <= last + timedelta(days=1):
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    rows: list[dict[str, Any]] = []
    prev: date | None = None
    for d in days:
        close_t = EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE
        open_s = datetime.combine(d, OPEN_START, tzinfo=ET).astimezone(UTC)
        close_s = datetime.combine(d, close_t, tzinfo=ET).astimezone(UTC)
        if prev is not None:
            prev_close_t = EARLY_CLOSE if is_early_close(prev) else REGULAR_CLOSE
            c0 = datetime.combine(prev, prev_close_t, tzinfo=ET).astimezone(UTC)
            between = [prev + timedelta(days=k) for k in range(1, (d - prev).days)]
            if any(b.weekday() == 5 for b in between):
                kind = "weekend"
            elif between:
                kind = "holiday"
            else:
                kind = "overnight"
            rows.append({"kind": kind, "start": c0, "end": open_s, "d0": prev, "d1": d})
        rows.append({"kind": "open", "start": open_s, "end": close_s, "d0": d, "d1": d})
        prev = d
    w = pd.DataFrame(rows)
    w["start"] = pd.to_datetime(w["start"], utc=True)
    w["end"] = pd.to_datetime(w["end"], utc=True)
    w["hours"] = (w["end"] - w["start"]).dt.total_seconds() / 3600.0
    iso = [d.isocalendar() for d in w["d0"]]
    w["week"] = [i[0] * 100 + i[1] for i in iso]
    keep = (w["start"].dt.date >= first - timedelta(days=1)) & (w["end"].dt.date <= last + timedelta(days=1))
    return w[keep].reset_index(drop=True)


def price_at(close: pd.Series, times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """The last close that had happened by each time, and how old it is in hours.

    ``close`` is indexed by the bar's *open* time and holds hourly bars, so a bar is known
    from open + 1h. NaN where nothing had happened yet."""
    if close.empty:
        return np.full(len(times), np.nan), np.full(len(times), np.nan)
    known = _ns(close.index + HOUR)
    t = _ns(times)
    idx = np.searchsorted(known, t, side="right") - 1
    ok = idx >= 0
    px = np.where(ok, close.to_numpy(dtype=float)[np.clip(idx, 0, None)], np.nan)
    age = np.where(ok, (t - known[np.clip(idx, 0, None)]) / 3.6e12, np.nan)
    return px, age


def window_returns(close: pd.Series, wins: pd.DataFrame) -> pd.DataFrame:
    """One row per window: the log return of the token across it and the age of both ends."""
    p0, a0 = price_at(close, pd.DatetimeIndex(wins["start"]))
    p1, a1 = price_at(close, pd.DatetimeIndex(wins["end"]))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(p1 / p0)
    out = wins.copy()
    out["p0"], out["p1"], out["r"] = p0, p1, r
    out["age0"], out["age1"] = a0, a1
    out["fresh"] = (a0 <= STALE_H) & (a1 <= STALE_H)
    return out[np.isfinite(out["r"])].reset_index(drop=True)


def flag_earnings(win: pd.DataFrame, earnings: set[date]) -> pd.DataFrame:
    """A window touches earnings if the report date is the day it starts or ends on."""
    out = win.copy()
    out["earn"] = [(a in earnings) or (b in earnings) for a, b in zip(out["d0"], out["d1"], strict=True)]
    return out


# ----------------------------------------------------------------------------- bootstrap


def block_counts(n_weeks: int, draws: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """How many times each week is drawn, in each of ``draws`` circular block resamples."""
    block = max(1, min(block, n_weeks))
    n_blocks = math.ceil(n_weeks / block)
    starts = rng.integers(0, n_weeks, size=(draws, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n_weeks
    idx = idx.reshape(draws, -1)[:, :n_weeks]
    out = np.zeros((draws, n_weeks))
    rows = np.repeat(np.arange(draws), idx.shape[1])
    np.add.at(out, (rows, idx.ravel()), 1.0)
    return out


def bootstrap(sufficient: np.ndarray, stat: Callable[[np.ndarray], dict[str, np.ndarray]], *, draws: int = BOOT_DRAWS, block: int = BLOCK_WEEKS, seed: int = 20260903) -> dict[str, dict[str, float]]:
    """Point estimate and 95% interval of every statistic ``stat`` returns.

    ``sufficient`` is shaped (weeks, ...) and holds per-week sums; every statistic is a
    function of the summed array, so a resample is one tensor product."""
    n_weeks = sufficient.shape[0]
    point = stat(sufficient.sum(axis=0))
    if n_weeks < 4:
        return {k: {"est": _f(v), "lo": math.nan, "hi": math.nan} for k, v in point.items()}
    counts = block_counts(n_weeks, draws, block, np.random.default_rng(seed))
    sums = np.tensordot(counts, sufficient, axes=(1, 0))
    dist = stat(sums)
    out: dict[str, dict[str, float]] = {}
    for k, v in point.items():
        d = dist[k][np.isfinite(dist[k])]
        lo, hi = (np.percentile(d, 2.5), np.percentile(d, 97.5)) if len(d) > draws * 0.5 else (math.nan, math.nan)
        out[k] = {"est": _f(v), "lo": _f(lo), "hi": _f(hi)}
    return out


def _f(x: Any) -> float:  # noqa: ANN401
    return float(np.asarray(x).reshape(-1)[0]) if np.size(x) else math.nan


# ----------------------------------------------------------------------------- Q1: movement


def movement_rows(per_token: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Long table of windows across tokens (``window_returns`` + ``flag_earnings`` output)."""
    frames = []
    for t, w in per_token.items():
        if w.empty:
            continue
        x = w[["kind", "week", "hours", "r", "fresh", "earn"]].copy()
        x["ticker"] = t
        frames.append(x)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["kind", "week", "hours", "r", "fresh", "earn", "ticker"])


def _tensor(rows: pd.DataFrame, weeks: list[int], tickers: list[str]) -> np.ndarray:
    """Per week, token and window kind: sum r^2, sum |r|, hours, windows."""
    s = np.zeros((len(weeks), len(tickers), len(KINDS), 4))
    if rows.empty:
        return s
    wi = rows["week"].map({w: i for i, w in enumerate(weeks)}).to_numpy()
    ti = rows["ticker"].map({t: i for i, t in enumerate(tickers)}).to_numpy()
    ki = rows["kind"].map({k: i for i, k in enumerate(KINDS)}).to_numpy()
    r = rows["r"].to_numpy(dtype=float)
    for j, vals in enumerate((r * r, np.abs(r), rows["hours"].to_numpy(dtype=float), np.ones(len(rows)))):
        np.add.at(s[..., j], (wi, ti, ki), vals)
    return s


def _geo(x: np.ndarray) -> np.ndarray:
    """Geometric mean over the last axis, ignoring tokens with no value."""
    with np.errstate(divide="ignore", invalid="ignore"):
        lg = np.where(np.isfinite(x) & (x > 0), np.log(x), np.nan)
        return np.exp(np.nanmean(lg, axis=-1))


def movement_stats(sums: np.ndarray) -> dict[str, np.ndarray]:
    """Statistics of Q1 from summed tensors shaped (..., tokens, kinds, 4)."""
    with _quiet():
        v, h, n = sums[..., 0], sums[..., 2], sums[..., 3]
        vo, vc = v[..., 0], v[..., 1:].sum(-1)
        ho, hc = h[..., 0], h[..., 1:].sum(-1)
        enough = (n.sum(-1) >= MIN_WINDOWS_PER_TOKEN) & (vo > 0) & (vc > 0)
        mask = lambda x: np.where(enough, x, np.nan)  # noqa: E731
        var_share = mask(vc / (vc + vo))
        time_share = np.where(enough, hc / (hc + ho), np.nan)
        out = {
            "var_share": np.nanmean(var_share, axis=-1),
            "var_share_median": np.nanmedian(var_share, axis=-1),
            "time_share": np.nanmean(time_share, axis=-1),
            "per_hour_var_ratio": _geo(mask((vc / hc) / (vo / ho))),
            "tokens": enough.sum(-1).astype(float),
        }
        vt = v.sum(-1)
        for i, k in enumerate(KINDS):
            out[f"var_share_{k}"] = np.nanmean(mask(v[..., i] / vt), axis=-1)
            if k != "open":
                out[f"per_hour_var_ratio_{k}"] = _geo(mask((v[..., i] / h[..., i]) / (vo / ho)))
        return out


def movement(rows: pd.DataFrame, *, only_fresh: bool = False, drop_earnings: bool = False) -> dict[str, Any]:
    """Q1 over a (possibly filtered) set of windows."""
    x = rows
    if only_fresh:
        x = x[x["fresh"]]
    if drop_earnings:
        x = x[~x["earn"]]
    if x.empty:
        return {"n_windows": 0, "stats": {}, "per_token": []}
    weeks = sorted(x["week"].unique())
    tickers = sorted(x["ticker"].unique())
    s = _tensor(x, weeks, tickers)
    stats = bootstrap(s, movement_stats)
    # per token, on the same bootstrap resamples as everything else
    per_token: list[dict[str, Any]] = []
    for i, t in enumerate(tickers):
        one = bootstrap(s[:, i : i + 1], movement_stats)
        sums = s[:, i].sum(0)
        per_token.append({
            "ticker": t,
            "n_windows": int(sums[:, 3].sum()),
            "n_closed": int(sums[1:, 3].sum()),
            "var_share": one["var_share"],
            "time_share": one["time_share"]["est"],
            "per_hour_var_ratio": one["per_hour_var_ratio"],
        })
    return {"n_windows": int(len(x)), "n_weeks": len(weeks), "stats": stats, "per_token": per_token}


# ----------------------------------------------------------------------------- Q2: weekends


def stock_days(daily: pd.DataFrame) -> pd.DataFrame:
    """Date-indexed open and close of the real stock, complete sessions only.

    The newest stored daily bar is usually a live partial one stamped at an odd second;
    a complete bar is stamped on the session's open."""
    if daily.empty:
        return pd.DataFrame(columns=["open", "close"])
    idx = daily.index
    ok = (idx.second == 0) & (idx.minute == 30) & np.isin(idx.hour, (13, 14))
    d = daily[ok]
    out = pd.DataFrame({"open": d["open"].to_numpy(dtype=float), "close": d["close"].to_numpy(dtype=float)}, index=[t.tz_convert(ET).date() for t in d.index])
    return out[~out.index.duplicated(keep="last")]


def gap_table(win: pd.DataFrame, stock: pd.DataFrame, ticker: str, kind: str) -> pd.DataFrame:
    """For each closed window of ``kind``: token move W, stock open gap G, stock move to
    the next close M. Windows missing a stock bar at either end are dropped."""
    w = win[win["kind"] == kind]
    rows = []
    for r in w.itertuples():
        if r.d0 not in stock.index or r.d1 not in stock.index:
            continue
        c0, o1, c1 = stock.at[r.d0, "close"], stock.at[r.d1, "open"], stock.at[r.d1, "close"]
        if min(c0, o1, c1) <= 0:
            continue
        rows.append({"ticker": ticker, "week": r.week, "d0": r.d0, "W": r.r, "G": math.log(o1 / c0), "M": math.log(c1 / c0),
                     "fresh": bool(r.fresh), "earn": bool(getattr(r, "earn", False)), "hours": r.hours})
    return pd.DataFrame(rows, columns=["ticker", "week", "d0", "W", "G", "M", "fresh", "earn", "hours"])


def _demean_by_date(t: pd.DataFrame) -> pd.DataFrame:
    """Remove each weekend's cross-token mean, so what is left is a token's own move."""
    t = t.copy()
    cnt = t.groupby("d0")["W"].transform("size")
    for c in ("W", "G"):
        t[c + "t"] = np.where(cnt >= MIN_TOKENS_TO_DEMEAN, t[c] - t.groupby("d0")[c].transform("mean"), np.nan)
    return t


_COLS = ("n", "W", "G", "M", "WW", "GG", "MM", "WG", "WM", "n_up", "G_up", "M_up", "n_dn", "G_dn", "M_dn", "n_big", "hit_big",
         "Wt_Gt", "Wt_Wt", "e2", "G2_oos", "n_oos")
_IX = {c: i for i, c in enumerate(_COLS)}


def _weekly(t: pd.DataFrame, weeks: list[int]) -> np.ndarray:
    """Per-week sums for every Q2 statistic, including the out-of-sample errors."""
    s = np.zeros((len(weeks), len(_COLS)))
    wk = {w: i for i, w in enumerate(weeks)}
    W, G, M = t["W"].to_numpy(), t["G"].to_numpy(), t["M"].to_numpy()
    wi = t["week"].map(wk).to_numpy()
    up, dn = W > 0, W < 0
    big = np.abs(W) >= BIG_MOVE
    ok = np.isfinite(t["Wt"].to_numpy()) & np.isfinite(t["Gt"].to_numpy())
    Wt, Gt = np.nan_to_num(t["Wt"].to_numpy()), np.nan_to_num(t["Gt"].to_numpy())
    cols = {
        "n": np.ones(len(t)), "W": W, "G": G, "M": M, "WW": W * W, "GG": G * G, "MM": M * M, "WG": W * G, "WM": W * M,
        "n_up": up * 1.0, "G_up": G * up, "M_up": M * up, "n_dn": dn * 1.0, "G_dn": G * dn, "M_dn": M * dn,
        "n_big": big * 1.0, "hit_big": (big & (np.sign(W) == np.sign(G))) * 1.0,
        "Wt_Gt": Wt * Gt * ok, "Wt_Wt": Wt * Wt * ok,
    }
    for c, v in cols.items():
        np.add.at(s[:, _IX[c]], wi, v)
    # Out-of-sample: the slope of G on W fitted only on weekends in strictly earlier weeks.
    wg, ww = s[:, _IX["WG"]], s[:, _IX["WW"]]
    n_cum = np.concatenate([[0.0], np.cumsum(s[:, _IX["n"]])[:-1]])
    beta = np.concatenate([[0.0], np.cumsum(wg)[:-1]]) / np.where(np.concatenate([[0.0], np.cumsum(ww)[:-1]]) > 0, np.concatenate([[0.0], np.cumsum(ww)[:-1]]), np.nan)
    pred = beta[wi] * W
    live = (n_cum[wi] >= MIN_TRAIN_OBS) & np.isfinite(pred)
    np.add.at(s[:, _IX["e2"]], wi, np.where(live, (G - pred) ** 2, 0.0))
    np.add.at(s[:, _IX["G2_oos"]], wi, np.where(live, G * G, 0.0))
    np.add.at(s[:, _IX["n_oos"]], wi, live * 1.0)
    return s


def weekend_stats(sums: np.ndarray) -> dict[str, np.ndarray]:
    with _quiet():
        c = {k: sums[..., i] for k, i in _IX.items()}
        n = c["n"]
        cov_wg = c["WG"] / n - (c["W"] / n) * (c["G"] / n)
        var_w = c["WW"] / n - (c["W"] / n) ** 2
        var_g = c["GG"] / n - (c["G"] / n) ** 2
        cov_wm = c["WM"] / n - (c["W"] / n) * (c["M"] / n)
        var_m = c["MM"] / n - (c["M"] / n) ** 2
        return {
            "n": n,
            "slope_open": c["WG"] / c["WW"],
            "slope_close": c["WM"] / c["WW"],
            "slope_own_open": c["Wt_Gt"] / c["Wt_Wt"],
            "corr_open": cov_wg / np.sqrt(var_w * var_g),
            "corr_close": cov_wm / np.sqrt(var_w * var_m),
            "gap_after_up_minus_down": c["G_up"] / c["n_up"] - c["G_dn"] / c["n_dn"],
            "hit_rate_big": c["hit_big"] / c["n_big"],
            "n_big": c["n_big"],
            "oos_skill": 1.0 - c["e2"] / c["G2_oos"],
            "n_oos": c["n_oos"],
        }


def weekend_block(table: pd.DataFrame, *, only_fresh: bool = True, drop_earnings: bool = False) -> dict[str, Any]:
    """Q2 over a gap table: estimates, intervals, and the per-token slopes."""
    x = table
    if only_fresh:
        x = x[x["fresh"]]
    if drop_earnings:
        x = x[~x["earn"]]
    if len(x) < 12:
        return {"n": int(len(x)), "stats": {}, "note": "too few"}
    x = _demean_by_date(x)
    weeks = sorted(x["week"].unique())
    s = _weekly(x, weeks)
    stats = bootstrap(s, weekend_stats)
    per_token = []
    for t, g in x.groupby("ticker"):
        if len(g) >= 20 and (g["W"] ** 2).sum() > 0:
            wk_t = sorted(g["week"].unique())
            ci = bootstrap(_weekly(g, wk_t), _slopes)
            per_token.append({"ticker": t, "n": int(len(g)), "slope_open": ci["slope_open"]["est"], "slope_close": ci["slope_close"]["est"],
                              "slope_open_ci": [ci["slope_open"]["lo"], ci["slope_open"]["hi"]]})
    return {
        "n": int(len(x)), "n_weeks": len(weeks), "tokens": int(x["ticker"].nunique()),
        "mean_abs_move_pct": float(100 * np.mean(np.abs(x["W"]))), "mean_abs_gap_pct": float(100 * np.mean(np.abs(x["G"]))),
        "stats": stats, "per_token": per_token,
        "tokens_with_positive_slope": int(sum(1 for p in per_token if p["slope_open"] > 0)),
        "tokens_scored": len(per_token),
    }


def _slopes(sums: np.ndarray) -> dict[str, np.ndarray]:
    with _quiet():
        return {"slope_open": sums[..., _IX["WG"]] / sums[..., _IX["WW"]], "slope_close": sums[..., _IX["WM"]] / sums[..., _IX["WW"]]}


def judge_weekend(block: dict[str, Any]) -> str:
    """yes / no / unclear for 'is the token's weekend move informative about the open?'.

    Yes needs all three to clear zero at once: the slope, the up-versus-down gap
    difference, and the out-of-sample skill. No needs the slope's interval to include zero
    and the skill to be no better than predicting nothing. Anything else is unclear."""
    st = block.get("stats") or {}
    try:
        slope, spread, skill = st["slope_open"], st["gap_after_up_minus_down"], st["oos_skill"]
    except KeyError:
        return "unclear"
    if not all(math.isfinite(v["lo"]) for v in (slope, spread, skill)):
        return "unclear"
    if slope["lo"] > 0 and spread["lo"] > 0 and skill["lo"] > 0:
        return "yes"
    if slope["lo"] <= 0 <= slope["hi"] and skill["hi"] <= 0.01:
        return "no"
    return "unclear"


# ----------------------------------------------------------------------------- Q3: books


_BOOK_COLS = ("n", "n_sp", "log_sp", "n_dp", "log_dp", "n_zero")
_LIQ_CLASSES = ("open", "overnight", "weekend", "holiday")


def classify_times(ts_ms: np.ndarray, wins: pd.DataFrame) -> np.ndarray:
    """Window kind of each timestamp (ms), or '' if outside the windows' span."""
    starts = _ns(wins["start"]) // 1_000_000
    ends = _ns(wins["end"]) // 1_000_000
    i = np.searchsorted(starts, ts_ms, side="right") - 1
    kinds = wins["kind"].to_numpy()
    ok = (i >= 0) & (ts_ms < ends[np.clip(i, 0, None)])
    return np.where(ok, kinds[np.clip(i, 0, None)], "")


def book_cells(books: dict[str, pd.DataFrame], wins: pd.DataFrame) -> tuple[np.ndarray, list[str], list[date]]:
    """Per ET day, token and window class: counts and sums of log spread and log depth.

    Medians cannot be summed across days, so the interval is on geometric means, which
    can. A zero-depth side (nothing resting at 25 bps) is counted separately."""
    tickers = sorted(books)
    all_days: set[date] = set()
    prepared = {}
    for t, df in books.items():
        if df.empty:
            continue
        ts = df["ts"].to_numpy(dtype="int64")
        kind = classify_times(ts, wins)
        day = pd.to_datetime(ts, unit="ms", utc=True).tz_convert(ET).date
        prepared[t] = (kind, np.asarray(day), df["spread_bps"].to_numpy(dtype=float), df["depth"].to_numpy(dtype=float))
        all_days.update(set(day))
    days = sorted(all_days)
    di = {d: i for i, d in enumerate(days)}
    out = np.zeros((len(days), len(tickers), len(_LIQ_CLASSES), len(_BOOK_COLS)))
    for ti, t in enumerate(tickers):
        if t not in prepared:
            continue
        kind, day, sp, dp = prepared[t]
        for ci, c in enumerate(_LIQ_CLASSES):
            m = kind == c
            if not m.any():
                continue
            d_i = np.array([di[d] for d in day[m]])
            sp_ok, dp_ok = np.isfinite(sp[m]) & (sp[m] > 0), np.isfinite(dp[m]) & (dp[m] > 0)
            np.add.at(out[:, ti, ci, 0], d_i, 1.0)
            np.add.at(out[:, ti, ci, 1], d_i, sp_ok * 1.0)
            np.add.at(out[:, ti, ci, 2], d_i, np.where(sp_ok, np.log(np.where(sp_ok, sp[m], 1.0)), 0.0))
            np.add.at(out[:, ti, ci, 3], d_i, dp_ok * 1.0)
            np.add.at(out[:, ti, ci, 4], d_i, np.where(dp_ok, np.log(np.where(dp_ok, dp[m], 1.0)), 0.0))
            np.add.at(out[:, ti, ci, 5], d_i, (np.isfinite(dp[m]) & (dp[m] <= 0)) * 1.0)
    return out, tickers, days


def book_stats(sums: np.ndarray) -> dict[str, np.ndarray]:
    """Closed over open, per token then the median across tokens: spread (>1 is wider),
    depth (<1 is thinner) and the share of snapshots with no resting depth."""
    with _quiet():
        n, nsp, lsp, ndp, ldp, nz = (sums[..., i] for i in range(6))
        gsp, gdp = lsp / nsp, ldp / ndp  # (..., tokens, classes)
        out: dict[str, np.ndarray] = {}
        for ci, c in enumerate(_LIQ_CLASSES):
            if c == "open":
                continue
            ok = (nsp[..., ci] >= 60) & (nsp[..., 0] >= 60)
            out[f"spread_ratio_{c}"] = np.nanmedian(np.where(ok, np.exp(gsp[..., ci] - gsp[..., 0]), np.nan), axis=-1)
            okd = (ndp[..., ci] >= 60) & (ndp[..., 0] >= 60)
            out[f"depth_ratio_{c}"] = np.nanmedian(np.where(okd, np.exp(gdp[..., ci] - gdp[..., 0]), np.nan), axis=-1)
            out[f"empty_share_{c}"] = np.nanmean(np.where(n[..., ci] >= 60, nz[..., ci] / n[..., ci], np.nan), axis=-1)
        out["empty_share_open"] = np.nanmean(np.where(n[..., 0] >= 60, nz[..., 0] / n[..., 0], np.nan), axis=-1)
        return out


def liquidity(books: dict[str, pd.DataFrame], wins: pd.DataFrame) -> dict[str, Any]:
    cells, tickers, days = book_cells(books, wins)
    if not len(days):
        return {"n_snapshots": 0, "stats": {}, "note": "no order-book snapshots"}
    # Each ET day is a unit; with a few weeks of archive that is a few dozen units, and the
    # weekend classes rest on a handful of them. The interval is wide for that reason.
    stats = bootstrap(cells, book_stats, block=1)
    tot = cells.sum(axis=0)
    per_token = []
    for ti, t in enumerate(tickers):
        row: dict[str, Any] = {"ticker": t, "n_open": int(tot[ti, 0, 0])}
        gs = tot[ti, :, 2] / np.where(tot[ti, :, 1] > 0, tot[ti, :, 1], np.nan)
        gd = tot[ti, :, 4] / np.where(tot[ti, :, 3] > 0, tot[ti, :, 3], np.nan)
        for ci, c in enumerate(_LIQ_CLASSES):
            if c == "open":
                row["spread_open_bps"], row["depth_open"] = float(np.exp(gs[0])), float(np.exp(gd[0]))
            elif tot[ti, ci, 0] >= 60:
                row[f"n_{c}"] = int(tot[ti, ci, 0])
                row[f"spread_ratio_{c}"] = float(np.exp(gs[ci] - gs[0]))
                row[f"depth_ratio_{c}"] = float(np.exp(gd[ci] - gd[0]))
        per_token.append(row)
    weekend_days = sorted({d for d, c in zip(days, cells[:, :, _LIQ_CLASSES.index("weekend"), 0].sum(axis=1), strict=True) if c > 0})
    return {
        "n_snapshots": int(tot[:, :, 0].sum()),
        "n_days": len(days), "first_day": str(days[0]), "last_day": str(days[-1]),
        "n_weekend_days": len(weekend_days), "tokens": len(tickers),
        "stats": stats, "per_token": per_token,
    }


# ----------------------------------------------------------------------------- the study


@dataclass(frozen=True)
class Inputs:
    """Everything the study reads, already loaded. Nothing here touches a database."""

    spot_close: dict[str, pd.Series]  # ticker -> hourly close, index = bar open time (UTC)
    daily: dict[str, pd.DataFrame]  # ticker -> real stock daily bars (open/close)
    earnings: dict[str, set[date]]  # ticker -> ET dates of earnings reports
    books: dict[str, pd.DataFrame]  # ticker -> ts (ms), spread_bps, depth


def run(inp: Inputs, *, first: date | None = None, last: date | None = None) -> dict[str, Any]:
    starts = [s.index.min() for s in inp.spot_close.values() if len(s)]
    ends = [s.index.max() for s in inp.spot_close.values() if len(s)]
    if not starts:
        return {"key": KEY, "ok": False, "note": "no token bars"}
    first = first or min(starts).date()
    last = last or max(ends).date()
    wins = session_windows(first, last)

    per_token: dict[str, pd.DataFrame] = {}
    gaps_weekend, gaps_night = [], []
    for t, close in sorted(inp.spot_close.items()):
        w = flag_earnings(window_returns(close, wins), inp.earnings.get(t, set()))
        per_token[t] = w
        stock = stock_days(inp.daily.get(t, pd.DataFrame()))
        if len(stock):
            gaps_weekend.append(gap_table(w, stock, t, "weekend"))
            gaps_night.append(gap_table(w, stock, t, "overnight"))
    rows = movement_rows(per_token)
    wk = pd.concat(gaps_weekend, ignore_index=True) if gaps_weekend else pd.DataFrame()
    nt = pd.concat(gaps_night, ignore_index=True) if gaps_night else pd.DataFrame()

    primary = movement(rows)
    result: dict[str, Any] = {
        "key": KEY, "ok": True, "title": TITLE, "questions": list(QUESTIONS),
        "ran_at": datetime.now(tz=UTC).isoformat(),
        "settings": {"open_window_et": "09:00-16:00", "stale_hours": STALE_H, "big_move": BIG_MOVE, "block_weeks": BLOCK_WEEKS, "bootstrap_draws": BOOT_DRAWS},
        "data": {
            "tokens": len(per_token), "first_day": str(first), "last_day": str(last),
            "windows": int(len(rows)), "closed_windows": int((rows["kind"] != "open").sum()),
            "stale_boundary_share": float(1 - rows["fresh"].mean()) if len(rows) else math.nan,
            "stale_boundary_share_closed": float(1 - rows.loc[rows["kind"] != "open", "fresh"].mean()) if len(rows) else math.nan,
        },
        "movement": {
            "primary": primary,
            "fresh_only": movement(rows, only_fresh=True),
            "no_earnings": movement(rows, drop_earnings=True),
        },
    }
    if len(wk):
        result["weekend"] = {
            "primary": weekend_block(wk),
            "all_weekends": weekend_block(wk, only_fresh=False),
            "no_earnings": weekend_block(wk, drop_earnings=True),
            "dropped_stale": int((~wk["fresh"]).sum()),
        }
        result["weekend"]["verdict"] = judge_weekend(result["weekend"]["primary"])
    if len(nt):
        result["overnight"] = {"primary": weekend_block(nt), "no_earnings": weekend_block(nt, drop_earnings=True)}
    result["liquidity"] = liquidity(inp.books, wins) if inp.books else {"n_snapshots": 0, "stats": {}}
    result["per_token"] = token_lines(result)
    return result


def token_lines(result: dict[str, Any]) -> dict[str, dict[str, float]]:
    """The two numbers the report quotes for one token, from this result and nothing else."""
    out: dict[str, dict[str, float]] = {}
    for p in (result.get("movement", {}).get("primary", {}) or {}).get("per_token", []):
        out[p["ticker"]] = {
            "closed_share_pct": round(100 * p["var_share"]["est"], 1),
            "closed_share_lo": round(100 * p["var_share"]["lo"], 1) if math.isfinite(p["var_share"]["lo"]) else None,
            "closed_share_hi": round(100 * p["var_share"]["hi"], 1) if math.isfinite(p["var_share"]["hi"]) else None,
            "time_share_pct": round(100 * p["time_share"], 1),
            "n_windows": p["n_windows"],
        }
    wk = (result.get("weekend", {}) or {}).get("primary", {})
    for p in wk.get("per_token", []) or []:
        if p["ticker"] in out:
            lo, hi = p.get("slope_open_ci") or (math.nan, math.nan)
            out[p["ticker"]].update({"weekend_slope_open": round(p["slope_open"], 3), "weekend_slope_close": round(p["slope_close"], 3), "n_weekends": p["n"],
                                     "weekend_slope_lo": round(lo, 3) if math.isfinite(lo) else None, "weekend_slope_hi": round(hi, 3) if math.isfinite(hi) else None})
    return out


def report_line(result: dict[str, Any], ticker: str) -> str | None:
    """One honest sentence for a token's report, or None if the numbers are not there.

    The weekend half is quoted only for a token with enough weekends; the slope is not
    a probability and the sentence says what it is."""
    p = (result.get("per_token") or {}).get(ticker)
    if not p:
        return None
    s = (f"This token made {p['closed_share_pct']:.0f}% of its price movement (by variance) while the US market was shut, "
         f"which is {p['time_share_pct']:.0f}% of the clock (n={p['n_windows']} windows)")
    if p.get("weekend_slope_open") is not None:
        s += f"; across {p['n_weekends']} weekends, Monday's stock open kept {100 * p['weekend_slope_open']:.0f}% of the token's weekend move on average"
    return s + "."
