"""How to get into the position the desk sized, on the book as it stands.

The desk prices getting out, because that is the half that can trap a position. Getting
in is the half a trader does first, and on a thin tokenized-stock book a market order for
the full size can walk several levels. So the plan answers three things from the live
book: what the whole size costs to take at once, whether that fits the cost budget, and
if not, how many equal slices keep each one inside it and at what limit price each slice
fills.

It assumes the book refills between slices, and says so: the recorded archive shows how
depth varies by time of week, but not how fast a given book replenishes, and pretending
to know would put a false number on the page. Nothing here places an order.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from nightwatch.execution.exit_cost import max_notional_within, quote_exit

MAX_SLICES = 20


@dataclass
class EntryPlan:
    side: str  # "buy" to open a long, "sell" to open a short
    notional: float
    budget_bps: float
    full_cost_bps: float | None
    full_fills: bool
    slices: int | None  # None when even the smallest slice breaks the budget
    slice_notional: float | None
    slice_cost_bps: float | None
    limit_price: float | None  # the price a single slice fills to, to post as a limit
    mid: float | None
    book_ts: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fill_price(levels: Any, notional: float) -> float | None:  # noqa: ANN401
    """The price of the last level a taker order of ``notional`` reaches."""
    left = notional
    for lvl in levels:
        take = lvl.price * lvl.size
        if take >= left:
            return float(lvl.price)
        left -= take
    return None


def plan_entry(book: Any, notional: float, *, long: bool, taker_fee: float, budget_bps: float) -> EntryPlan | None:  # noqa: ANN401
    """The entry plan for ``notional`` on ``book``, or None without a usable book."""
    if book is None or notional <= 0 or book.mid is None:
        return None
    # Opening a long buys, which walks the asks - the same walk as closing a short.
    closing_long = not long
    side = "buy" if long else "sell"
    levels = book.asks if long else book.bids
    full = quote_exit(book, notional, closing_long=closing_long, taker_fee=taker_fee)
    plan = EntryPlan(
        side=side, notional=notional, budget_bps=budget_bps, full_cost_bps=full.total_cost_bps, full_fills=full.fully_filled,
        slices=None, slice_notional=None, slice_cost_bps=None, limit_price=None, mid=book.mid, book_ts=full.book_ts,
    )
    if full.fully_filled and full.total_cost_bps is not None and full.total_cost_bps <= budget_bps:
        plan.slices, plan.slice_notional, plan.slice_cost_bps = 1, notional, full.total_cost_bps
        plan.limit_price = _fill_price(levels, notional)
        return plan
    largest = max_notional_within(book, closing_long=closing_long, taker_fee=taker_fee, budget_bps=budget_bps)
    if largest <= 0:
        plan.note = "even a small order breaks the cost budget on this book right now"
        return plan
    n = math.ceil(notional / largest)
    if n > MAX_SLICES:
        plan.note = f"it would take more than {MAX_SLICES} slices to stay inside the cost budget; the book is too thin for this size now"
        return plan
    each = notional / n
    q = quote_exit(book, each, closing_long=closing_long, taker_fee=taker_fee)
    plan.slices, plan.slice_notional, plan.slice_cost_bps = n, each, q.total_cost_bps
    plan.limit_price = _fill_price(levels, each)
    plan.note = "assumes the book refills between slices; how fast this one does is not something the desk measures"
    return plan
