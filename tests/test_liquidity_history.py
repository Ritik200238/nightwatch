"""The recorded book archive, grouped by time of week."""

from datetime import UTC, datetime, timedelta

import pytest

from nightwatch.data.models import OrderBookLevel, OrderBookSnapshot, Venue
from nightwatch.data.store import Store
from nightwatch.execution.liquidity_history import MIN_SNAPSHOTS_PER_BUCKET, render, summarise

# A Wednesday inside the US session, and the Saturday that follows it.
SESSION = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
WEEKEND = datetime(2026, 9, 12, 6, 0, tzinfo=UTC)


def book(mid: float, depth_each: float, levels: int, ts: datetime) -> OrderBookSnapshot:
    bids = tuple(OrderBookLevel(price=mid * (1 - 0.0002 * (i + 1)), size=depth_each / mid) for i in range(levels))
    asks = tuple(OrderBookLevel(price=mid * (1 + 0.0002 * (i + 1)), size=depth_each / mid) for i in range(levels))
    return OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=ts, observed_at=ts, bids=bids, asks=asks)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "l.sqlite")
    n = MIN_SNAPSHOTS_PER_BUCKET + 20
    for i in range(n):
        s.insert_orderbook(book(100.0, 30_000.0, 6, SESSION + timedelta(minutes=i)))  # deep
        s.insert_orderbook(book(100.0, 2_000.0, 6, WEEKEND + timedelta(minutes=i)))  # thin
    yield s
    s.close()


def test_nothing_recorded_says_so(tmp_path):
    with Store(tmp_path / "empty.sqlite") as s:
        h = summarise(s, "RTSLAUSDT")
        assert h.n_snapshots == 0 and "no order-book snapshots" in h.note
        assert render(h).startswith("LIQUIDITY HISTORY")


def test_the_session_book_is_deeper_than_the_weekend_book(store):
    h = summarise(store, "RTSLAUSDT")
    names = {b.bucket for b in h.buckets}
    assert "us_regular" in names and "weekend" in names
    session = next(b for b in h.buckets if b.bucket == "us_regular")
    weekend = next(b for b in h.buckets if b.bucket == "weekend")
    assert session.depth_25bps_median > weekend.depth_25bps_median
    assert h.best_bucket.bucket == "us_regular" and h.worst_bucket.bucket == "weekend"
    assert "deeper in us_regular than in weekend" in render(h)


def test_it_counts_how_often_the_book_was_too_thin(store):
    h = summarise(store, "RTSLAUSDT", reference=20_000.0)
    weekend = next(b for b in h.buckets if b.bucket == "weekend")
    session = next(b for b in h.buckets if b.bucket == "us_regular")
    assert weekend.share_below_reference == pytest.approx(1.0)  # 2k a level, never enough
    assert session.share_below_reference == pytest.approx(0.0)


def test_a_bucket_with_few_snapshots_is_marked_thin(tmp_path):
    with Store(tmp_path / "thin.sqlite") as s:
        for i in range(10):
            s.insert_orderbook(book(100.0, 30_000.0, 6, SESSION + timedelta(minutes=i)))
        h = summarise(s, "RTSLAUSDT")
        assert h.buckets[0].thin and h.worst_bucket is None
        assert "every bucket is still thin" in h.note
        assert "(thin)" in render(h)


def test_the_window_is_reported(store):
    h = summarise(store, "RTSLAUSDT")
    assert h.since is not None and h.until is not None and h.since < h.until
    assert h.n_snapshots == (MIN_SNAPSHOTS_PER_BUCKET + 20) * 2
