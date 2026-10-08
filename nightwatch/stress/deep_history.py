"""The long record: what each stock did over every daily bar Yahoo holds, back to 1999.

Nightwatch's analog search runs on hourly bars, which start on 1 Jan 2025. That is the
right grain for "what happens in the next 60 hours", and a short memory for rare events:
a 2025-2026 sample cannot hold the 2008 weekends or the 2020 gap. This module is the
other half. It does not forecast anything and never touches a verdict: it measures, from
the daily bars the stock itself has printed since listing, how big its moves over the
same kinds of window have been, and where the desk's one-in-twenty line sits inside
that record.

What is measured (daily bars, split-adjusted by the provider)
-------------------------------------------------------------
* ``overnight_gap``  open of a bar over the previous close, when the previous session was
                     one or two calendar days earlier (an ordinary night).
* ``weekend_gap``    the same, when the previous session was three
                     or more calendar days earlier (a weekend, or a holiday weekend). This is the move a tokenized stock trades through
                     while its stock is closed.
* ``weekend_close``  close of the first bar when the previous session was three or more days earlier, over the
                     close before it: the weekend plus the Monday session.
* ``one_day``        close over the previous close.
* ``five_day``       close over the close five bars earlier (overlapping windows).

Decisions fixed before looking
------------------------------
* Simple returns in percent. A position loses on the side it is on, so every window is
  kept whole and the side picks which tail is the "bad" one: the lower tail for a long,
  the upper tail for a short.
* The record is *unconditional*. It does not know that earnings are tonight or that
  volatility is low. The desk's line is conditional on today's setup, so a calm night's
  line can sit well inside the unconditional record without being wrong; the comparison
  is context for the reader, not a test of the forecast, and is worded that way.
* "Share beyond the line" is read off a stored grid of percentiles by straight-line
  interpolation. It is an estimate, labelled as one. The exact worst moves are stored
  with their dates so the extreme end can be checked against the bars.
* Nothing is dropped for being large. Bars with a non-positive price are dropped, and so
  are the few places where the provider's series is not one company's price path (below).
  That is all.

Where the provider's prices are not one continuous price path
-------------------------------------------------------------
The provider adjusts for splits but not for spin-offs, so the day a company hands a
division to its shareholders shows up as a fall that no holder suffered, and a ticker
reused after a merger carries the old company's history. Those cases are listed in
``SERIES_FIXES`` with the reason, applied identically to every window, and written into
the committed file so a reader sees exactly what was left out. Large moves that are real
(Morgan Stanley +87% on 13 Oct 2008, Apple -52% on 29 Sep 2000) are kept. This list was
found by reading the largest moves in the sweep; a spin-off whose fall was small is not in
it and sits in the record as an ordinary down day, which can only make the tail look
slightly heavier than it was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RESULT_PATH = Path(__file__).with_name("deep_history.json")

# Percentile grid kept per window. Dense in both tails, where the question lives.
GRID = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0, 25.0, 50.0,
        75.0, 85.0, 90.0, 92.0, 93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 98.5, 99.0, 99.5, 99.75, 100.0)

WINDOWS: dict[str, dict[str, Any]] = {
    "overnight_gap": {"hours": 17.0, "en": "Overnight gap", "zh": "隔夜跳空",
                      "def_en": "open over the previous close when the previous session was one or two days earlier",
                      "def_zh": "停市一两天后，开盘价相对前一收盘价的涨跌"},
    "weekend_gap": {"hours": 65.0, "en": "Weekend gap", "zh": "周末跳空",
                    "def_en": "open over the previous close when the previous session was three or more days earlier",
                    "def_zh": "停市三天及以上（周末或长假）后，开盘价相对前一收盘价的涨跌"},
    "one_day": {"hours": 24.0, "en": "One day", "zh": "一天",
                "def_en": "close over the previous close", "def_zh": "收盘价相对前一收盘价"},
    "weekend_close": {"hours": 72.0, "en": "Weekend plus Monday", "zh": "周末加周一",
                      "def_en": "close of the first session when the previous session was three or more days earlier, over the close before it",
                      "def_zh": "停市三天及以上之后第一个交易日的收盘价，相对停市前的收盘价"},
    "five_day": {"hours": 120.0, "en": "Five sessions", "zh": "五个交易日",
                 "def_en": "close over the close five sessions earlier (windows overlap)",
                 "def_zh": "收盘价相对五个交易日前的收盘价（窗口相互重叠）"},
}
# Places the provider's series is not one company's continuous price path.
#   since   drop every bar before this date (a ticker reused after a merger)
#   breaks  sessions whose move from the previous close is not a price move (a spin-off)
SERIES_FIXES: dict[str, dict[str, Any]] = {
    "MO": {"breaks": ["2008-03-31"], "why": "Philip Morris International was spun off to Altria holders on 28 Mar 2008; the provider shows it as a 70% fall."},
    "MDLZ": {"breaks": ["2012-10-02"], "why": "Kraft Foods Group was spun off on 1 Oct 2012; the provider shows it as a 34% fall."},
    "TMUS": {"since": "2013-05-02", "why": "The TMUS ticker belonged to MetroPCS until the 1 May 2013 merger; earlier bars are a different company."},
}

# Windows that stand in for a hold of a given length, nearest first wins.
HOLD_WINDOWS = ("one_day", "weekend_close", "five_day")
MIN_N = 60  # fewer observations than this and a one-in-twenty line is not read


def window_returns(daily: pd.DataFrame, fixes: dict[str, Any] | None = None) -> dict[str, pd.Series]:
    """Percent returns per window, each indexed by the date of the bar that ended it.

    ``daily`` needs ``ts`` (bar open, UTC), ``open`` and ``close``; one row per session.
    ``fixes`` is one entry of ``SERIES_FIXES``.
    """
    d = daily[(daily["open"] > 0) & (daily["close"] > 0)].copy()
    d["day"] = pd.to_datetime(d["ts"], utc=True).dt.tz_localize(None).dt.normalize()
    d = d.drop_duplicates("day").sort_values("day").set_index("day")
    fixes = fixes or {}
    if fixes.get("since"):
        d = d[d.index >= pd.Timestamp(fixes["since"])]
    if len(d) < 2:
        return {k: pd.Series(dtype=float) for k in WINDOWS}
    prev_close = d["close"].shift(1)
    shut_days = (d.index.to_series().diff().dt.days - 1).clip(lower=0)  # calendar days with no session
    gap = (d["open"] / prev_close - 1.0) * 100.0
    close_ret = (d["close"] / prev_close - 1.0) * 100.0
    long_shut = shut_days >= 2  # Friday close to Monday open is two shut days (Sat, Sun)
    out = {
        "overnight_gap": gap[(~long_shut) & prev_close.notna()],
        "weekend_gap": gap[long_shut & prev_close.notna()],
        "one_day": close_ret.dropna(),
        "weekend_close": close_ret[long_shut & prev_close.notna()],
        "five_day": ((d["close"] / d["close"].shift(5) - 1.0) * 100.0).dropna(),
    }
    out = {k: v.astype(float) for k, v in out.items()}
    for b in fixes.get("breaks", []):
        day = pd.Timestamp(b)
        if day not in d.index:
            continue
        pos = d.index.get_loc(day)
        for k, v in out.items():
            # A one-session window ends on the break; a five-session window spans it for the next five sessions.
            reach = d.index[pos : pos + (5 if k == "five_day" else 1)]
            out[k] = v[~v.index.isin(reach)]
    return out


def summarize(r: pd.Series, *, recent_years: int = 3) -> dict[str, Any] | None:
    """The stored shape of one window: counts, the percentile grid, the worst and best moves."""
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return None
    vals = r.to_numpy()
    cut = r.index.max() - pd.DateOffset(years=recent_years)
    recent = r[r.index > cut].to_numpy()
    order = r.sort_values()
    def ev(s: pd.Series) -> list[dict[str, Any]]:
        return [{"date": i.strftime("%Y-%m-%d"), "pct": round(float(v), 2)} for i, v in s.items()]
    return {
        "n": int(vals.size),
        "mean": round(float(vals.mean()), 3),
        "q": [round(float(x), 3) for x in np.percentile(vals, GRID)],
        "worst": ev(order.head(5)),
        "best": ev(order.tail(5).iloc[::-1]),
        "recent": {"years": recent_years, "n": int(recent.size),
                   "p5": round(float(np.percentile(recent, 5)), 3) if recent.size >= MIN_N else None,
                   "p95": round(float(np.percentile(recent, 95)), 3) if recent.size >= MIN_N else None},
    }


def summarize_ticker(daily: pd.DataFrame, fixes: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Everything stored for one stock, or None if it has too few bars to say anything."""
    wins = window_returns(daily, fixes)
    body = {k: s for k, v in wins.items() if (s := summarize(v)) is not None and s["n"] >= MIN_N}
    if not body:
        return None
    days = pd.to_datetime(daily["ts"], utc=True)
    if fixes and fixes.get("since"):
        days = days[days >= pd.Timestamp(fixes["since"], tz="UTC")]
    out = {"first": days.min().strftime("%Y-%m-%d"), "last": days.max().strftime("%Y-%m-%d"),
           "sessions": int(len(days)), "windows": body}
    if fixes:
        out["adjusted"] = {k: v for k, v in fixes.items()}
    return out


def pool(per_ticker: dict[str, dict[str, Any]], raw: dict[str, dict[str, pd.Series]], skip: set[str]) -> dict[str, Any]:
    """The same summary over every stock's moves at once (leveraged funds excluded)."""
    out: dict[str, Any] = {}
    for name in WINDOWS:
        parts = [raw[t][name] for t in per_ticker if t not in skip and t in raw and name in raw[t] and len(raw[t][name])]
        if not parts:
            continue
        s = summarize(pd.concat(parts).sort_index())
        if s:
            s["tickers"] = int(len(parts))
            out[name] = s
    return out


def share_beyond(window: dict[str, Any], line_pct: float, side: str) -> float | None:
    """Fraction of the record that went past ``line_pct`` against a position on ``side``.

    ``line_pct`` is a move of the stock in percent: negative for the line a long loses
    on, positive for the line a short loses on. Linear interpolation on the stored grid.
    """
    q = np.asarray(window["q"], dtype=float)
    g = np.asarray(GRID, dtype=float) / 100.0
    if q.size != g.size:
        return None
    # np.interp needs a non-decreasing x; flat stretches of identical quantiles are fine.
    below = float(np.interp(line_pct, q, g, left=0.0, right=1.0))  # P(move <= line)
    if side == "short":
        return round(max(0.0, 1.0 - below), 4)
    return round(min(1.0, below), 4)


def adverse(window: dict[str, Any], side: str) -> dict[str, Any]:
    """The bad tail for a position on ``side``: the lower tail for a long, the upper for a short."""
    q = dict(zip(GRID, window["q"], strict=True))
    if side == "short":
        return {"p5": q[95.0], "p1": q[99.0], "worst": q[100.0], "worst_events": window["best"][:3], "recent_p5": (window.get("recent") or {}).get("p95")}
    return {"p5": q[5.0], "p1": q[1.0], "worst": q[0.0], "worst_events": window["worst"][:3], "recent_p5": (window.get("recent") or {}).get("p5")}


def pick_window(horizon_h: float | None) -> str:
    """Which hold-length window stands in for the report's horizon: the nearest in hours."""
    if not horizon_h or horizon_h <= 0:
        return "one_day"
    return min(HOLD_WINDOWS, key=lambda k: abs(WINDOWS[k]["hours"] - horizon_h))


_CACHE: dict[str, Any] = {}


def load_result() -> dict[str, Any] | None:
    """The committed result of ``scripts/deep_history_sweep.py``, or None if there is none.

    It is a measurement made on a given day from the provider's bars, not something the
    server recomputes; it carries its own ``ran_at`` so a stale one shows as stale. The
    file is read once per change of file, not once per request."""
    try:
        key = (str(RESULT_PATH), RESULT_PATH.stat().st_mtime_ns)
        if _CACHE.get("key") != key:
            _CACHE["key"], _CACHE["val"] = key, json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        return _CACHE["val"]
    except (OSError, ValueError):
        return None


def for_ticker(ticker: str, *, side: str = "long", horizon_h: float | None = None, line_pct: float | None = None) -> dict[str, Any]:
    """What the long record says for one stock and side, optionally against the desk's line.

    ``line_pct`` is the desk's one-in-twenty line as the *stock's* move in percent (the
    lower line for a long, the upper line for a short)."""
    res = load_result()
    base: dict[str, Any] = {"ticker": ticker, "side": side, "available": False}
    if not res:
        return base
    t = (res.get("tickers") or {}).get(ticker)
    if not t:
        return {**base, "reason": "no daily history for this ticker in the committed measurement", "ran_at": res.get("ran_at")}
    chosen = pick_window(horizon_h)
    windows: dict[str, Any] = {}
    for name, w in t["windows"].items():
        a = adverse(w, side)
        row = {"n": w["n"], **a, "label": WINDOWS[name]["en"], "label_zh": WINDOWS[name]["zh"]}
        windows[name] = row
    out = {**base, "available": True, "first": t["first"], "last": t["last"], "sessions": t["sessions"], "windows": windows, "adjusted": t.get("adjusted"),
           "chosen": chosen if chosen in windows else None, "ran_at": res.get("ran_at"),
           "pooled": _pooled_line(res, chosen, side), "source": res.get("source")}
    w = t["windows"].get(chosen)
    if w is not None and line_pct is not None:
        out["line_pct"] = line_pct
        out["share_beyond"] = share_beyond(w, line_pct, side)
    return out


def _pooled_line(res: dict[str, Any], window: str, side: str) -> dict[str, Any] | None:
    p = (res.get("pooled") or {}).get(window)
    if not p:
        return None
    a = adverse(p, side)
    return {"n": p["n"], "tickers": p.get("tickers"), "p5": a["p5"], "p1": a["p1"], "worst": a["worst"]}
