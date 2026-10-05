"""Perpetual open interest: how much leveraged exposure is open on the token's perp.

Context for a leveraged trade, not an input to the size. A crowded perp (open interest
up sharply) is a bigger target for a liquidation cascade than a thinning one, and that is
all this says. Nothing here has been measured against what the token did next, so it
reaches the report as a plain line and never the verdict.

Two numbers: open interest now (Bitget's public ``/api/v3/market/open-interest``) and the
same figure about a day ago from the desk's own recorder (the ``tickers`` table), so the
change is measured against what was actually seen, not an assumption. Where the recorder
has no row near 24 h ago (a fresh install) the change is simply left out and the line
says so by omission.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nightwatch.data.models import Venue
from nightwatch.data.store import Store

LOOKBACK = timedelta(hours=24)
TOLERANCE = timedelta(hours=3)
# Beyond this the change is too small to call a direction in words.
FLAT_PCT = 1.0


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
    out["line"] = line(out)
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
