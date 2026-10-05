"""What the listed options market implies for the length of this hold.

Context beside the desk's own history, and a floor under the size. The report puts two
numbers side by side: how far the options market says the stock may move over the hold
(a one-standard-deviation move), and how bad one night in twenty has been for this
position in the desk's own history. When they disagree sharply that is worth a person's
attention. The size takes the more cautious of the two: the implied move is also a severe
stress preset (``options_implied_move``), so when it exceeds every severe move in the
token's own history the stress limit is sized on it, and the report says so
(``attach_sizing``). When it is milder it changes nothing: never less cautious than the
history alone.

Method (written so it can be audited)
-------------------------------------
1. The hold is ``[as_of, as_of + hold_h]``. Take the nearest listed expiry whose close
   (16:00 US Eastern on its date) is at or after the hold's end: the first option that
   still lives through the whole hold.
2. At that expiry take the at-the-money strike (nearest the underlying's last price with a
   real two-sided quote on both the call and the put) and its implied volatility, the
   mean of the call's and the put's. Cboe quotes IV annualised on calendar time, as
   Black-Scholes does, so the expiry's total variance is ``IV^2 x calendar_days / 365``,
   with the days counted from the *quote's* own time (the anchor), not from now: out of
   session the feed is the last session's, and on a Monday morning a Friday-close IV
   still carries the weekend in its time to expiry.
3. Variance does not accrue on weekends or exchange holidays. Spread the expiry's total
   variance evenly over its *trading time* from the anchor to the expiry (each US trading
   day counts for the fraction of its 24 clock hours that lies inside the window; closed
   days count for nothing) and take the share that falls inside the hold::

       sigma_hold = IV * sqrt( calendar_days/365 * hold_trading_days / expiry_trading_days )

   That is the one-standard-deviation move for the hold, shown as "about +/- X%".
4. As a cross-check the same expiry's ATM straddle (call mid + put mid) / spot is the
   market's expected absolute move to expiry, about 0.8 sigma; scaled the same way to the
   hold and divided by 0.798 it gives a second one-sigma figure. Both are kept in the
   result (``straddle_move_pct``); the headline is the IV one because a straddle mid on a
   stale or wide quote is noisier than the IV Cboe computes. Checked on live quotes on
   2026-10-05 (TSLA and NVDA, holds of 4.5 h, 24 h and 72 h): the two figures agree within 4%.
   Counting the expiry's time from now instead of from the quote's time had them 25-150% apart.

What this is not: a forecast of direction, and not tail risk. A one-sigma options move and
the desk's 1-in-20 loss (about 1.65 sigma if returns were normal, and they are not) are
different yardsticks; the line states both without claiming either is right.

Quotes are Cboe's delayed feed. Out of session they are the last session's, and the block
carries the quote's own timestamp so the report can say so.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nightwatch.data.cboe import AtmQuote, OptionsChain
from nightwatch.time_utils import is_trading_day

_ET = ZoneInfo("America/New_York")
_CLOSE = time(16, 0)
_SQRT_2_OVER_PI = math.sqrt(2.0 / math.pi)  # E|Z| for a standard normal


def trading_days(start: datetime, end: datetime) -> float:
    """Trading time in [start, end], in days: each US trading day counts for the share of
    its 24 clock hours that lies in the window (US Eastern calendar days), closed days
    for nothing."""
    s, e = start.astimezone(_ET), end.astimezone(_ET)
    if e <= s:
        return 0.0
    total, d = 0.0, s.date()
    while d <= e.date():
        if is_trading_day(d):
            day_start = datetime.combine(d, time(0), tzinfo=_ET)
            lo, hi = max(s, day_start), min(e, day_start + timedelta(days=1))
            if hi > lo:
                total += (hi - lo).total_seconds() / 86_400.0
        d += timedelta(days=1)
    return total


def _expiry_close(d: date) -> datetime:
    return datetime.combine(d, _CLOSE, tzinfo=_ET)


def covering_expiry(chain: OptionsChain, hold_end: datetime) -> AtmQuote | None:
    """The nearest expiry that is still alive at the end of the hold."""
    for q in chain.expiries:  # sorted ascending
        if _expiry_close(q.expiry) >= hold_end:
            return q
    return None


def implied_move(chain: OptionsChain, as_of: datetime, hold_h: float) -> dict[str, Any] | None:
    """The options-implied one-sigma move over the hold, or None when no expiry covers it
    (or the hold has no trading time in it, so nothing can move)."""
    hold_end = as_of + timedelta(hours=hold_h)
    q = covering_expiry(chain, hold_end)
    if q is None:
        return None
    anchor = min(chain.quote_ts, as_of) if chain.quote_ts else as_of
    hold_td = trading_days(as_of, hold_end)
    exp_td = trading_days(anchor, _expiry_close(q.expiry))
    cal_days = (_expiry_close(q.expiry) - anchor).total_seconds() / 86_400.0
    if hold_td <= 0 or exp_td <= 0 or cal_days <= 0:
        return None
    iv = (q.call_iv + q.put_iv) / 2.0
    share = hold_td / exp_td
    var_expiry = iv * iv * cal_days / 365.0
    sigma = math.sqrt(var_expiry * share)
    straddle_expected = (q.call_mid + q.put_mid) / chain.spot
    straddle_sigma = straddle_expected * math.sqrt(share) / _SQRT_2_OVER_PI
    return {
        "ticker": chain.ticker, "source": "Cboe delayed quotes", "spot": chain.spot,
        "expiry": q.expiry.isoformat(), "atm_strike": q.strike, "atm_iv_pct": iv * 100.0,
        "hold_h": hold_h, "anchor": anchor.isoformat(), "hold_trading_days": hold_td, "expiry_trading_days": exp_td,
        "implied_move_pct": sigma * 100.0, "straddle_move_pct": straddle_sigma * 100.0,
        "iv30_pct": chain.iv30 * 100.0 if chain.iv30 else None,
        "quote_ts": chain.quote_ts.isoformat() if chain.quote_ts else None, "fetched_at": chain.fetched_at.isoformat(),
        "n_strikes": q.n_strikes, "desk_p5_pct": None, "line": None,
    }


def line(move_pct: float, p5_pct: float | None) -> str:
    """One plain sentence. ``p5_pct`` is the position's one-in-twenty loss (negative), as
    the report's history section carries it."""
    out = f"Options market implies about ±{move_pct:.1f}% over this hold"
    if p5_pct is not None and p5_pct < 0:
        return f"{out}; history says one in twenty worse than −{abs(p5_pct):.1f}%."
    return f"{out}."


def attach_history(block: dict[str, Any], p5_pct: float | None) -> dict[str, Any]:
    """Set the desk's own 1-in-20 loss beside the implied move and write the line."""
    block["desk_p5_pct"] = p5_pct if p5_pct is not None and p5_pct < 0 else None
    block["line"] = line(block["implied_move_pct"], block["desk_p5_pct"])
    return block


def attach_sizing(block: dict[str, Any], preset: Any) -> dict[str, Any]:  # noqa: ANN401
    """Say whether the options market's move is what the stress limit was sized on.

    ``preset`` is the ``options_implied_move`` scenario, or None when there was none."""
    cal = getattr(preset, "calibration", None) or {}
    block["sizing_binding"] = bool(cal.get("binding"))
    block["history_severe_pct"] = cal.get("history_severe_pct")
    if block["sizing_binding"] and block["history_severe_pct"] is not None:
        block["sizing_line"] = (f"The options market expects more than history: the stress limit is sized on ±{block['implied_move_pct']:.1f}% "
                                f"(history's worst severe move for this side is {block['history_severe_pct']:.1f}%).")
    elif block["sizing_binding"]:
        block["sizing_line"] = f"The options market expects ±{block['implied_move_pct']:.1f}% and the stress limit is sized on it."
    else:
        block["sizing_line"] = None
    return block
