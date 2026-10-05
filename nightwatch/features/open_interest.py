"""Perpetual open interest: how much leveraged exposure is open on the token's perp.

A crowded perp (open interest up sharply) is a bigger target for a liquidation cascade
than a thinning one. A sharp rise is raised as a caution flag on the report and, for a
leveraged trade, as a line in the leverage section. It never changes the size: nothing
here has been measured against what the token did next.

"Sharp" is not a number picked by hand. It is the top decile of this perp's own 24 h
changes in the recorder's history (at least ``MIN_OBS`` of them, so a fresh install flags
nothing), and never less than ``FLOOR_PCT``: when open interest barely moves, its biggest
moves are still noise.

Two numbers: open interest now (Bitget's public ``/api/v3/market/open-interest``) and the
same figure about a day ago from the desk's own recorder (the ``tickers`` table), so the
change is measured against what was actually seen, not an assumption. Where the recorder
has no row near 24 h ago (a fresh install) the change is simply left out and the line
says so by omission.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from nightwatch.data.models import Venue
from nightwatch.data.store import Store

LOOKBACK = timedelta(hours=24)
TOLERANCE = timedelta(hours=3)
# Beyond this the change is too small to call a direction in words.
FLAT_PCT = 1.0
HISTORY = timedelta(days=30)
DECILE = 90.0
MIN_OBS = 48
FLOOR_PCT = 3.0


def changes_24h(series: list[tuple[datetime, float]], *, tolerance: timedelta = timedelta(hours=1)) -> np.ndarray:
    """Every 24 h percentage change in an hourly series: each point against the point
    nearest 24 h before it, when there is one within ``tolerance``."""
    if len(series) < 2:
        return np.array([])
    t = np.array([x[0].timestamp() for x in series])
    v = np.array([x[1] for x in series])
    want = t - LOOKBACK.total_seconds()
    idx = np.clip(np.searchsorted(t, want), 1, len(t) - 1)
    pick = np.where(np.abs(t[idx - 1] - want) <= np.abs(t[idx] - want), idx - 1, idx)
    ok = (np.abs(t[pick] - want) <= tolerance.total_seconds()) & (v[pick] > 0) & (pick < np.arange(len(t)))
    return (v[ok] / v[pick][ok] - 1.0) * 100.0


def crowding(change_pct: float | None, series: list[tuple[datetime, float]]) -> dict[str, Any]:
    """Whether this 24 h change is in the top decile of the perp's own history.

    ``threshold_pct`` is None (and ``crowded`` False) until there are MIN_OBS past changes."""
    hist = changes_24h(series)
    if change_pct is None or hist.size < MIN_OBS:
        return {"crowded": False, "threshold_pct": None, "n_history": int(hist.size)}
    thr = max(float(np.percentile(hist, DECILE)), FLOOR_PCT)
    return {"crowded": change_pct >= thr, "threshold_pct": thr, "n_history": int(hist.size)}


def build(symbol: str, contracts: float, observed_at: datetime, store: Store | None, *, price: float | None = None) -> dict[str, Any]:
    """The report's open-interest block. ``price`` is the perp's price, for a dollar figure."""
    then = store.open_interest_near(Venue.BITGET_UMCBL, symbol, observed_at - LOOKBACK, tolerance=TOLERANCE) if store is not None else None
    change = None
    if then is not None and then[1] > 0:
        change = (contracts / then[1] - 1.0) * 100.0
    out: dict[str, Any] = {
        "symbol": symbol, "contracts": contracts, "usd": contracts * price if price else None,
        "observed_at": observed_at.isoformat(), "change_24h_pct": change,
        "compared_with_ts": then[0].isoformat() if then else None,
    }
    series = store.open_interest_hourly(Venue.BITGET_UMCBL, symbol, observed_at - HISTORY) if store is not None else []
    out.update(crowding(change, series))
    out["line"] = line(out)
    out["crowded_line"] = f"crowded: OI {change:+.0f}% in 24h (top decile of its last {out['n_history']} day-over-day changes)" if out["crowded"] else None
    return out


def _qty(x: float) -> str:
    return f"{x:,.0f}" if x >= 100 else f"{x:,.2f}"


def _usd(x: float) -> str:
    return f"${x / 1e6:,.1f}M" if x >= 1e6 else f"${x / 1e3:,.0f}k"


def line(oi: dict[str, Any]) -> str:
    """"Open interest 38,322 contracts (about $14.2M), up 3.4% in 24h.", in plain words."""
    now = f"open interest {_qty(oi['contracts'])} contracts" + (f" (about {_usd(oi['usd'])})" if oi.get("usd") else "")
    ch = oi.get("change_24h_pct")
    if ch is None:
        return f"{now[0].upper()}{now[1:]} on Bitget's perp; no reading from a day ago to compare with yet."
    if abs(ch) < FLAT_PCT:
        return f"{now[0].upper()}{now[1:]}, about the same as 24 h ago ({ch:+.1f}%)."
    return f"{now[0].upper()}{now[1:]}, {'up' if ch > 0 else 'down'} {abs(ch):.1f}% in 24h."
