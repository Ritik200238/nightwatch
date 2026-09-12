"""Order-book depth metrics.

These are the numbers the product turns into "can you actually get out?". They are
computed once per snapshot by the recorder and stored alongside the raw levels, so
historical liquidity can be analysed without re-parsing books.

Definitions (all relative to the mid price):

* ``spread_bps``            – (best_ask − best_bid) / mid × 10⁴
* ``depth_{side}_{k}bps``   – quote notional resting within *k* bps of the mid on that side
* ``imbalance_{k}bps``      – (bid_depth − ask_depth) / (bid_depth + ask_depth) within k bps
* ``walk_cost_bps(side, notional)`` – average execution price of a market order of the
  given quote notional expressed as bps away from the mid; ``None`` when the book cannot
  absorb the order.
"""

from __future__ import annotations

from dataclasses import dataclass

from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot

DEPTH_BPS_LEVELS: tuple[int, ...] = (10, 25, 50, 100)


@dataclass(frozen=True)
class WalkResult:
    filled_notional: float
    avg_price: float
    cost_bps: float  # positive = worse than mid
    levels_consumed: int
    fully_filled: bool


def depth_within_bps(levels: tuple[OrderBookLevel, ...], mid: float, bps: float, side: str) -> float:
    """Quote notional resting within ``bps`` of ``mid`` on ``side`` ('bid'/'ask')."""
    limit = bps / 1e4
    total = 0.0
    for lv in levels:
        if side == "bid":
            if (mid - lv.price) / mid > limit:
                break
        else:
            if (lv.price - mid) / mid > limit:
                break
        total += lv.price * lv.size
    return total


def walk_book(levels: tuple[OrderBookLevel, ...], mid: float, notional: float) -> WalkResult:
    """Simulate a market order consuming ``levels`` (best first) up to ``notional`` quote."""
    if notional <= 0:
        raise ValueError("notional must be positive")
    remaining = notional
    base_filled = 0.0
    quote_filled = 0.0
    consumed = 0
    for lv in levels:
        level_notional = lv.price * lv.size
        take = min(remaining, level_notional)
        if take <= 0:
            break
        base_filled += take / lv.price
        quote_filled += take
        remaining -= take
        consumed += 1
        if remaining <= 1e-9:
            break
    if base_filled <= 0:
        return WalkResult(0.0, float("nan"), float("nan"), 0, False)
    avg = quote_filled / base_filled
    cost_bps = abs(avg - mid) / mid * 1e4
    return WalkResult(quote_filled, avg, cost_bps, consumed, remaining <= 1e-9)


def snapshot_metrics(snap: OrderBookSnapshot) -> dict[str, float | int | None]:
    """Flat metric dict for persistence. ``None`` where the book is one-sided/empty."""
    out: dict[str, float | int | None] = {
        "best_bid": snap.best_bid,
        "best_ask": snap.best_ask,
        "mid": snap.mid,
        "spread_bps": snap.spread_bps,
        "n_bids": len(snap.bids),
        "n_asks": len(snap.asks),
        "bid_notional_total": sum(lv.price * lv.size for lv in snap.bids),
        "ask_notional_total": sum(lv.price * lv.size for lv in snap.asks),
    }
    mid = snap.mid
    for k in DEPTH_BPS_LEVELS:
        if mid is None:
            out[f"depth_bid_{k}bps"] = None
            out[f"depth_ask_{k}bps"] = None
            out[f"imbalance_{k}bps"] = None
            continue
        b = depth_within_bps(snap.bids, mid, k, "bid")
        a = depth_within_bps(snap.asks, mid, k, "ask")
        out[f"depth_bid_{k}bps"] = b
        out[f"depth_ask_{k}bps"] = a
        out[f"imbalance_{k}bps"] = (b - a) / (b + a) if (b + a) > 0 else None
    return out
