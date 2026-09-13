"""What it has actually cost to get out, hour of week by hour of week.

Nobody publishes how deep a tokenized-stock book is at three in the morning on a Sunday.
The recorder has been snapshotting every book every minute since it was switched on, so
this reads that archive and answers the question the exit-cost estimate can only answer
for right now: is the book always this good, and what does it look like when the US
market is shut?

Reported per time-of-week bucket, from the stored depth columns rather than a model:

* the spread, median and worst case
* how much can be sold inside 25 basis points of the mid
* how often the book was too thin to absorb a reference size at all

Every figure carries the number of snapshots behind it, and a bucket with fewer than a
few hours of observations is marked as thin rather than quietly averaged in. Until the
recorder has a couple of weeks of history the weekend buckets will say exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.data.models import Venue
from nightwatch.data.store import Store
from nightwatch.time_utils import from_epoch_ms, hour_of_week_bucket, to_epoch_ms, utc_now

MIN_SNAPSHOTS_PER_BUCKET = 120  # two hours of minute snapshots before a bucket means much
REFERENCE_NOTIONAL = 20_000.0
COST_BUDGET_BPS = 25.0


@dataclass(frozen=True)
class BucketLiquidity:
    bucket: str
    n_snapshots: int
    thin: bool
    hours_covered: float
    spread_median_bps: float | None
    spread_p95_bps: float | None
    depth_25bps_median: float | None  # sellable inside 25 bps, quote terms
    depth_25bps_p5: float | None  # the bad case
    share_below_reference: float | None  # snapshots too thin for the reference size


@dataclass(frozen=True)
class LiquidityHistory:
    symbol: str
    since: datetime | None
    until: datetime | None
    n_snapshots: int
    buckets: list[BucketLiquidity] = field(default_factory=list)
    reference_notional: float = REFERENCE_NOTIONAL
    note: str = ""

    @property
    def worst_bucket(self) -> BucketLiquidity | None:
        usable = [b for b in self.buckets if not b.thin and b.depth_25bps_median is not None]
        return min(usable, key=lambda b: b.depth_25bps_median) if usable else None

    @property
    def best_bucket(self) -> BucketLiquidity | None:
        usable = [b for b in self.buckets if not b.thin and b.depth_25bps_median is not None]
        return max(usable, key=lambda b: b.depth_25bps_median) if usable else None


def load(store: Store, symbol: str, *, venue: Venue = Venue.BITGET_SPOT, since: datetime | None = None, until: datetime | None = None) -> pd.DataFrame:
    """Stored snapshot metrics for one symbol. No level JSON: the columns are enough."""
    lo = to_epoch_ms(since) if since else 0
    hi = to_epoch_ms(until or utc_now())
    return pd.read_sql_query(
        """SELECT ts, spread_bps, depth_bid_25bps, depth_ask_25bps, bid_notional_total
           FROM orderbook_snapshots WHERE venue=? AND symbol=? AND ts BETWEEN ? AND ? ORDER BY ts""",
        store._conn, params=(venue.value, symbol, lo, hi),
    )


def summarise(store: Store, symbol: str, *, venue: Venue = Venue.BITGET_SPOT, since: datetime | None = None, reference: float = REFERENCE_NOTIONAL) -> LiquidityHistory:
    """Group the archive by time of week and describe each bucket."""
    df = load(store, symbol, venue=venue, since=since)
    if df.empty:
        return LiquidityHistory(symbol=symbol, since=None, until=None, n_snapshots=0, note="no order-book snapshots recorded yet")

    df["when"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["bucket"] = [hour_of_week_bucket(t.to_pydatetime()).value for t in df["when"]]
    # Selling hits bids, so the sell side is the one that matters for an exit.
    df["depth25"] = df["depth_bid_25bps"]

    buckets: list[BucketLiquidity] = []
    for name, g in df.groupby("bucket", sort=True):
        n = len(g)
        depth = g["depth25"].dropna()
        spread = g["spread_bps"].dropna()
        span_h = float((g["when"].max() - g["when"].min()) / timedelta(hours=1)) if n > 1 else 0.0
        buckets.append(
            BucketLiquidity(
                bucket=str(name), n_snapshots=n, thin=n < MIN_SNAPSHOTS_PER_BUCKET, hours_covered=span_h,
                spread_median_bps=float(spread.median()) if len(spread) else None,
                spread_p95_bps=float(np.percentile(spread, 95)) if len(spread) else None,
                depth_25bps_median=float(depth.median()) if len(depth) else None,
                depth_25bps_p5=float(np.percentile(depth, 5)) if len(depth) else None,
                share_below_reference=float((depth < reference).mean()) if len(depth) else None,
            )
        )

    buckets.sort(key=lambda b: (b.depth_25bps_median is None, b.depth_25bps_median))
    usable = [b for b in buckets if not b.thin]
    note = ""
    if not usable:
        note = "every bucket is still thin: the recorder needs more hours before these can be compared"
    elif len(usable) < len(buckets):
        note = f"{len(buckets) - len(usable)} of {len(buckets)} buckets are still thin and are marked as such"
    return LiquidityHistory(
        symbol=symbol, since=from_epoch_ms(int(df["ts"].iloc[0])), until=from_epoch_ms(int(df["ts"].iloc[-1])),
        n_snapshots=int(len(df)), buckets=buckets, reference_notional=reference, note=note,
    )


def render(h: LiquidityHistory) -> str:
    if not h.buckets:
        return f"LIQUIDITY HISTORY ({h.symbol}): {h.note}"
    lines = [f"LIQUIDITY HISTORY — {h.symbol}, {h.n_snapshots:,} snapshots from {h.since:%Y-%m-%d %H:%M} to {h.until:%Y-%m-%d %H:%M} UTC"]
    lines.append(f"  {'bucket':<14} {'snaps':>7} {'spread med':>11} {'spread p95':>11} {'sellable in 25bps':>19} {'bad case':>10} {'too thin for ' + f'{h.reference_notional:,.0f}':>22}")
    for b in h.buckets:
        thin = " (thin)" if b.thin else ""
        lines.append(
            f"  {b.bucket:<14} {b.n_snapshots:>7,} {b.spread_median_bps or float('nan'):>10.1f} {b.spread_p95_bps or float('nan'):>11.1f}"
            f" {b.depth_25bps_median or float('nan'):>16,.0f} {b.depth_25bps_p5 or float('nan'):>10,.0f} {(b.share_below_reference or 0) * 100:>20.0f}%{thin}"
        )
    if h.note:
        lines.append(f"  {h.note}")
    worst, best = h.worst_bucket, h.best_bucket
    if worst and best and worst.bucket != best.bucket:
        ratio = (best.depth_25bps_median / worst.depth_25bps_median) if worst.depth_25bps_median else None
        if ratio:
            lines.append(f"  the book is {ratio:.1f}x deeper in {best.bucket} than in {worst.bucket}")
    return "\n".join(lines)
