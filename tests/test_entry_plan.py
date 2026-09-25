"""Getting into the sized position: all at once when the book allows it, in slices when
it does not, and an honest no when even a slice is too expensive."""

from datetime import datetime
from types import SimpleNamespace

from nightwatch.execution.entry_plan import plan_entry
from nightwatch.time_utils import UTC


def book(ask_sizes, bid_sizes=None, mid=100.0, step=0.05):  # noqa: ANN001, ANN202
    asks = [SimpleNamespace(price=mid + step * (i + 1), size=s) for i, s in enumerate(ask_sizes)]
    bids = [SimpleNamespace(price=mid - step * (i + 1), size=s) for i, s in enumerate(bid_sizes or ask_sizes)]
    return SimpleNamespace(mid=mid, asks=asks, bids=bids, ts=datetime(2026, 9, 25, tzinfo=UTC))


def test_a_size_the_book_absorbs_is_one_order():
    p = plan_entry(book([500] * 10), 5_000, long=True, taker_fee=0.001, budget_bps=25)
    assert p.slices == 1 and p.side == "buy" and p.full_fills
    assert p.limit_price == 100.05, "5,000 USDT fills inside the first level"


def test_a_size_too_big_for_the_budget_is_sliced_to_fit():
    p = plan_entry(book([10] * 60, step=0.1), 20_000, long=True, taker_fee=0.001, budget_bps=25)
    assert p.slices and p.slices > 1
    assert p.slice_cost_bps <= 25 and p.slice_notional * p.slices == 20_000
    assert "refills" in p.note, "the assumption is stated, not hidden"


def test_a_short_is_opened_by_selling_into_the_bids():
    p = plan_entry(book([500] * 10, bid_sizes=[500] * 10), 5_000, long=False, taker_fee=0.001, budget_bps=25)
    assert p.side == "sell" and p.limit_price == 99.95


def test_a_book_where_even_a_slice_breaks_the_budget_says_so():
    p = plan_entry(book([1] * 5, step=2.0), 10_000, long=True, taker_fee=0.001, budget_bps=25)
    assert p.slices is None and "breaks the cost budget" in p.note


def test_no_book_means_no_plan():
    assert plan_entry(None, 1_000, long=True, taker_fee=0.001, budget_bps=25) is None
