"""The hold laid out against the US market clock.

A tokenized stock trades all night, but the stock it tracks does not. What matters for
the hold is where the US regular sessions fall inside it: the stretch with no price
discovery is where gaps happen. This lists the regular sessions around the hold, from
the NYSE calendar in ``time_utils`` (holidays and early closes included), so the page can
draw "now, close, open, end of hold" and run a live countdown without carrying its own
copy of the calendar.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nightwatch.time_utils import _regular_bounds, classify_session, ensure_utc, is_trading_day, next_trading_day, previous_trading_day

# Enough sessions past the hold that a viewer reading a day-old report still finds the next open.
_TRAILING_DAYS = 6


def build(as_of: datetime, horizon_h: float, hold_start: datetime | None = None) -> dict[str, Any]:
    """Regular sessions from the last one before ``as_of`` to a few days past the hold.

    ``hold_start`` is for a hold that begins later than the analysis (a scheduled weekend,
    asked on a Tuesday, starts at Friday's close): the hold, and so ``hold_end``, is counted
    from there. Without it the hold starts at ``as_of``."""
    t0 = ensure_utc(as_of)
    hs = ensure_utc(hold_start) if hold_start is not None and ensure_utc(hold_start) > t0 else None
    end = (hs or t0) + timedelta(hours=float(horizon_h))
    info = classify_session(t0)
    d = info.et_date
    # The session that opened last at or before t0: today's if it has opened, else the previous one.
    start = d if is_trading_day(d) and _regular_bounds(d)[0] <= t0 else previous_trading_day(d)
    sessions: list[dict[str, str]] = []
    day = start
    limit = end + timedelta(days=_TRAILING_DAYS)
    while True:
        o, c = _regular_bounds(day)
        if o > limit:
            break
        sessions.append({"open": o.isoformat(), "close": c.isoformat()})
        day = next_trading_day(day)
    nxt = next((s for s in sessions if datetime.fromisoformat(s["open"]) > t0), None)
    return {
        "as_of": t0.isoformat(),
        **({"hold_start": hs.isoformat()} if hs else {}),
        "hold_end": end.isoformat(),
        "market_open_at_as_of": not info.is_closed,
        "next_open": nxt["open"] if nxt else None,
        "sessions": sessions,
    }
