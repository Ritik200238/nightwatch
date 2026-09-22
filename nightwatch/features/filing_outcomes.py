"""What actually happened after each filing the model read.

The model's read is an opinion formed from the filing's own words, and an opinion is
worth exactly what it predicts. This joins each read to the token's own bars and asks
the only question that settles it: over the window from the filing to the next US
regular open - the window the stock cannot trade in and the token can - what did the
price do?

The window is the product's window, not a convenient one. A filing accepted at 16:05
Eastern is measured to the next morning's open, because that is how long someone
holding the token is exposed to it before the market can price it.

Nothing here is point-in-time sensitive in the usual way: the model read text that was
public at ``accepted_at`` and never saw a price. The outcome is the label, and a label
is allowed to look forward - that is what makes it a label.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.time_utils import classify_session, ensure_utc

log = logging.getLogger(__name__)

# A filing lands mid-hour; the first bar a holder could act on is the next completed one.
# Measuring from the bar *containing* the filing would credit the model with part of the
# move that happened before the filing was public.
SNAP = "1h"


def window_after(ts: datetime) -> tuple[datetime, float]:
    """From a filing to the next US regular open, and how many hours that is.

    While the market is open there is no overnight window, so the measurement runs to
    the next open anyway - which for an intraday filing is the following morning, and
    includes a session the stock could react in. Those are reported separately rather
    than mixed in.
    """
    at = ensure_utc(ts)
    info = classify_session(at)
    end = info.regular_open_utc
    if end <= at:  # already past today's open; the next one is tomorrow's
        end = classify_session(at + timedelta(days=1)).regular_open_utc
    return end, max(0.5, (end - at).total_seconds() / 3600.0)


def outcome_for(frame: pd.DataFrame, ts: datetime) -> dict[str, float] | None:
    """The token's move from the first completed bar after ``ts`` to the next open."""
    t0 = pd.Timestamp(ensure_utc(ts)).ceil(SNAP)
    end, hours = window_after(ts)
    t1 = pd.Timestamp(end).ceil(SNAP)
    if t0 not in frame.index or t1 > frame.index[-1] or t1 <= t0:
        return None
    entry = float(frame.at[t0, "spot_close"])
    window = frame.loc[t0:t1]
    if not np.isfinite(entry) or entry <= 0 or window.empty:
        return None
    closes = window["spot_close"].ffill()
    if closes.isna().all():
        return None
    exit_close = float(closes.iloc[-1])
    lo = float(np.nanmin(window["spot_low"].to_numpy(dtype=float)))
    hi = float(np.nanmax(window["spot_high"].to_numpy(dtype=float)))
    return {
        "ret_pct": (exit_close / entry - 1.0) * 100.0,
        "mae_pct": (lo / entry - 1.0) * 100.0,
        "mfe_pct": (hi / entry - 1.0) * 100.0,
        "hours": hours,
    }


def collect(ctx: Any, reads: pd.DataFrame) -> pd.DataFrame:  # noqa: ANN401
    """Join every read to what followed it. ``reads`` needs accession, ticker, accepted_at."""
    from nightwatch.features.snapshot import InsufficientData
    from nightwatch.time_utils import utc_now

    if reads.empty:
        return pd.DataFrame()
    end_all = utc_now()
    frames: dict[str, pd.DataFrame] = {}
    rows: list[dict] = []
    for r in reads.itertuples(index=False):
        ticker = str(r.ticker)
        if ticker not in frames:
            try:
                frames[ticker] = ctx.feature_frame(ticker, end_all)
            except (InsufficientData, KeyError):
                frames[ticker] = pd.DataFrame()
        frame = frames[ticker]
        if frame.empty:
            continue
        at = pd.Timestamp(int(r.accepted_at), unit="ms", tz="UTC").to_pydatetime()
        out = outcome_for(frame, at)
        if out is None:
            continue
        closed = classify_session(at).is_closed
        rows.append({
            "accession": r.accession, "ticker": ticker, "accepted_at": at,
            "category": r.category, "market_moving": r.market_moving, "direction": r.direction,
            "headline": getattr(r, "headline", ""), "market_was_shut": closed, **out,
        })
    return pd.DataFrame(rows)


def load_reads(store: Any) -> pd.DataFrame:  # noqa: ANN401
    """Every stored read, with the filing timestamp it belongs to."""
    return pd.read_sql_query(
        "SELECT r.accession, r.ticker, r.category, r.market_moving, r.direction, r.headline, f.accepted_at, f.form, f.items "
        "FROM filing_reads r JOIN filings f ON f.accession = r.accession",
        store._conn,
    )
