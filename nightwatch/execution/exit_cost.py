"""Exit cost and hedge economics.

Exit cost
---------
"Can I get out, and what will it cost?" is answered on the *actual* book, not a
model: we walk the resting orders for the trader's size and report the average fill
versus mid (bps), the fee, the number of levels consumed, and whether the order fills.
A cost curve across sizes and the largest size that stays under a bps budget are
derived from the same walk, so the report can say "you can exit up to $X at ≤ 25 bps".

When historical book snapshots exist, the same walk is replayed over them to show how
the cost of exiting *this* size has varied by session (weekend vs regular hours).

Hedge
-----
A perp hedge neutralises the underlying move on the hedged share. It costs taker or
maker fees on entry and exit, funding over the horizon, and leaves *basis risk*: the
token can still drift against fair value. We quantify all three, using the token's
own closed-hours basis distribution for the residual.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from nightwatch.data.book_metrics import walk_book
from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot

DEFAULT_SIZES = (1_000, 2_500, 5_000, 10_000, 20_000, 50_000, 100_000, 250_000)


@dataclass(frozen=True)
class ExitQuote:
    notional_quote: float
    side: str  # "sell" (closing a long) or "buy" (closing a short)
    mid: float
    avg_price: float | None
    walk_cost_bps: float | None
    fee_bps: float
    total_cost_bps: float | None
    total_cost_quote: float | None
    levels_consumed: int
    fully_filled: bool
    book_ts: str


def quote_exit(book: OrderBookSnapshot, notional_quote: float, *, closing_long: bool, taker_fee: float) -> ExitQuote:
    side = "sell" if closing_long else "buy"
    levels = book.bids if closing_long else book.asks
    mid = book.mid
    if mid is None or notional_quote <= 0:
        return ExitQuote(notional_quote, side, mid or float("nan"), None, None, taker_fee * 1e4, None, None, 0, False, book.ts.isoformat())
    res = walk_book(levels, mid, notional_quote)
    if np.isnan(res.cost_bps):
        return ExitQuote(notional_quote, side, mid, None, None, taker_fee * 1e4, None, None, 0, False, book.ts.isoformat())
    total_bps = res.cost_bps + taker_fee * 1e4
    return ExitQuote(
        notional_quote=notional_quote, side=side, mid=mid, avg_price=res.avg_price, walk_cost_bps=res.cost_bps,
        fee_bps=taker_fee * 1e4, total_cost_bps=total_bps, total_cost_quote=total_bps / 1e4 * notional_quote,
        levels_consumed=res.levels_consumed, fully_filled=res.fully_filled, book_ts=book.ts.isoformat(),
    )


def cost_curve(book: OrderBookSnapshot, *, closing_long: bool, taker_fee: float, sizes: Sequence[float] = DEFAULT_SIZES) -> pd.DataFrame:
    rows = []
    for n in sizes:
        q = quote_exit(book, float(n), closing_long=closing_long, taker_fee=taker_fee)
        rows.append({"notional": n, "walk_cost_bps": q.walk_cost_bps, "total_cost_bps": q.total_cost_bps, "levels": q.levels_consumed, "fully_filled": q.fully_filled})
    return pd.DataFrame(rows)


def max_notional_within(book: OrderBookSnapshot, *, closing_long: bool, taker_fee: float, budget_bps: float, cap: float = 5_000_000.0) -> float:
    """Largest quote notional whose total exit cost stays within ``budget_bps`` (bisection)."""
    if quote_exit(book, 1.0, closing_long=closing_long, taker_fee=taker_fee).total_cost_bps is None:
        return 0.0
    if quote_exit(book, 1.0, closing_long=closing_long, taker_fee=taker_fee).total_cost_bps > budget_bps:
        return 0.0
    lo, hi = 1.0, cap
    for _ in range(60):
        mid = (lo + hi) / 2.0
        q = quote_exit(book, mid, closing_long=closing_long, taker_fee=taker_fee)
        if q.fully_filled and q.total_cost_bps is not None and q.total_cost_bps <= budget_bps:
            lo = mid
        else:
            hi = mid
    return float(lo)


def replay_exit_cost(snapshots: Sequence[OrderBookSnapshot], notional_quote: float, *, closing_long: bool, taker_fee: float) -> pd.DataFrame:
    """Exit cost of a fixed size across historical snapshots (for by-session statistics)."""
    rows = []
    for snap in snapshots:
        q = quote_exit(snap, notional_quote, closing_long=closing_long, taker_fee=taker_fee)
        rows.append({"ts": snap.ts, "total_cost_bps": q.total_cost_bps, "fully_filled": q.fully_filled, "spread_bps": snap.spread_bps})
    return pd.DataFrame(rows).set_index("ts") if rows else pd.DataFrame()


# ------------------------------------------------------------------------ hedge


@dataclass(frozen=True)
class HedgeQuote:
    hedge_ratio: float
    hedged_notional: float
    perp_symbol: str
    entry_fee_quote: float
    exit_fee_quote: float
    funding_quote: float  # expected over the horizon at the current rate
    funding_quote_p95: float  # if funding sits at its 95th-percentile |rate|
    total_cost_quote: float
    total_cost_bps_of_position: float
    residual_basis_p95_bps: float | None  # token-vs-index dislocation not removed by the hedge
    residual_basis_quote_p95: float | None
    note: str


def quote_hedge(
    *,
    position_notional: float,
    hedge_ratio: float,
    horizon_h: float,
    perp_symbol: str,
    perp_fee: float,
    funding_rate_now: float,
    funding_rate_abs_p95: float,
    funding_interval_h: int = 8,
    residual_basis_abs_p95_bps: float | None,
    maker: bool = False,
) -> HedgeQuote:
    if not 0.0 <= hedge_ratio <= 1.0:
        raise ValueError("hedge_ratio must be in [0, 1]")
    hedged = position_notional * hedge_ratio
    fee = perp_fee * hedged
    intervals = max(0.0, horizon_h / funding_interval_h)
    funding = abs(funding_rate_now) * intervals * hedged
    funding_p95 = abs(funding_rate_abs_p95) * intervals * hedged
    total = 2 * fee + funding
    residual_q = None if residual_basis_abs_p95_bps is None else residual_basis_abs_p95_bps / 1e4 * hedged
    note = "maker fees assumed on both legs" if maker else "taker fees assumed on both legs"
    return HedgeQuote(
        hedge_ratio=hedge_ratio, hedged_notional=hedged, perp_symbol=perp_symbol, entry_fee_quote=fee, exit_fee_quote=fee,
        funding_quote=funding, funding_quote_p95=funding_p95, total_cost_quote=total,
        total_cost_bps_of_position=(total / position_notional * 1e4) if position_notional else 0.0,
        residual_basis_p95_bps=residual_basis_abs_p95_bps, residual_basis_quote_p95=residual_q, note=note,
    )


def levels_from_metrics_row(row: pd.Series) -> tuple[tuple[OrderBookLevel, ...], tuple[OrderBookLevel, ...]] | None:  # pragma: no cover - helper for future use
    return None
