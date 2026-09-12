from datetime import UTC, datetime, timedelta

from nightwatch.data.book_metrics import walk_book
from nightwatch.data.models import (
    Bar,
    EarningsEvent,
    FundingRate,
    Instrument,
    InstrumentType,
    Interval,
    OrderBookLevel,
    OrderBookSnapshot,
    PriceKind,
    Venue,
)
from nightwatch.data.store import Store

UTC = UTC
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def bar(i: int, observed: datetime, close: float = 100.0) -> Bar:
    return Bar(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", interval=Interval.H1, ts=T0 + timedelta(hours=i),
               open=close, high=close + 1, low=close - 1, close=close, volume_base=1, volume_quote=100, observed_at=observed)


def test_bars_roundtrip_and_upsert_keeps_earliest_observed(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        early, late = T0 + timedelta(days=1), T0 + timedelta(days=2)
        assert s.upsert_bars([bar(0, early, 100), bar(1, early, 101)]) == 2
        # Re-observe bar 0 later with a revised close: values update, observed_at stays early.
        s.upsert_bars([bar(0, late, 100.5)])
        df = s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)
        assert list(df["close"]) == [100.5, 101.0]
        assert df["observed_at"].iloc[0].to_pydatetime() == early
        assert s.bar_coverage(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1) == (T0, T0 + timedelta(hours=1), 2)


def test_point_in_time_read_excludes_bars_not_yet_closed(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        s.upsert_bars([bar(0, T0), bar(1, T0), bar(2, T0)])  # bars 00:00, 01:00, 02:00
        # At 01:30 only the 00:00 bar has closed (01:00 bar closes at 02:00).
        df = s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1, as_of=T0 + timedelta(hours=1, minutes=30))
        assert len(df) == 1 and df.index[0].to_pydatetime() == T0
        # Exactly at 02:00 the 01:00 bar is closed and included.
        assert len(s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1, as_of=T0 + timedelta(hours=2))) == 2


def test_bar_range_filters_and_kind_isolation(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        s.upsert_bars([bar(i, T0) for i in range(5)])
        idx = Bar(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", interval=Interval.H1, kind=PriceKind.INDEX, ts=T0,
                  open=1, high=1, low=1, close=1, observed_at=T0)
        s.upsert_bars([idx])
        df = s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1, start=T0 + timedelta(hours=1), end=T0 + timedelta(hours=3))
        assert len(df) == 2
        assert len(s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1, kind=PriceKind.INDEX)) == 1


def test_gap_detection(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        s.upsert_bars([bar(0, T0), bar(1, T0), bar(4, T0), bar(5, T0)])
        gaps = s.bar_gaps(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)
        assert gaps == [(T0 + timedelta(hours=1), T0 + timedelta(hours=4), 2)]


def test_empty_bars_frame_has_expected_shape(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        df = s.get_bars(Venue.BITGET_SPOT, "NOPE", Interval.H1)
        assert df.empty and list(df.columns)[:4] == ["open", "high", "low", "close"]


def test_instruments_roundtrip(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        ins = Instrument(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", type=InstrumentType.SPOT, base="rTSLA", quote="USDT",
                         underlying_ticker="TSLA", is_tokenized_stock=True, status="online", observed_at=T0, raw={"x": 1})
        other = Instrument(venue=Venue.BITGET_SPOT, symbol="BTCUSDT", type=InstrumentType.SPOT, base="BTC", quote="USDT",
                           status="online", observed_at=T0)
        s.upsert_instruments([ins, other])
        toks = s.list_instruments(Venue.BITGET_SPOT, tokenized_only=True)
        assert [t.symbol for t in toks] == ["RTSLAUSDT"] and toks[0].raw == {"x": 1}


def test_orderbook_metrics_and_walk(tmp_path):
    bids = tuple(OrderBookLevel(price=100 - i * 0.05, size=1.0) for i in range(10))  # 5 bps steps
    asks = tuple(OrderBookLevel(price=100 + 0.05 + i * 0.05, size=1.0) for i in range(10))
    snap = OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=T0, observed_at=T0, bids=bids, asks=asks)
    with Store(tmp_path / "t.sqlite") as s:
        sid = s.insert_orderbook(snap)
        df = s.get_orderbook_metrics(Venue.BITGET_SPOT, "RTSLAUSDT")
        assert len(df) == 1
        assert abs(df["spread_bps"].iloc[0] - 5.0) < 0.01
        # 10 bps either side of mid (100.025): bids at 100, 99.95 (~2.5, 7.5 bps) => 2 levels
        assert round(df["depth_bid_10bps"].iloc[0], 2) == round(100 + 99.95, 2)
        back = s.get_orderbook_snapshot(sid)
        assert back is not None and back.bids == bids and back.asks == asks
        assert s.latest_orderbook(Venue.BITGET_SPOT, "RTSLAUSDT") == back

    # Walking $250 through asks: first level 100.05*1, second 100.10*1, third partial.
    res = walk_book(asks, snap.mid, 250.0)
    assert res.fully_filled and res.levels_consumed == 3
    assert 0 < res.cost_bps < 15


def test_walk_book_insufficient_liquidity():
    asks = (OrderBookLevel(price=100.0, size=1.0),)
    res = walk_book(asks, 99.99, 1_000.0)
    assert not res.fully_filled and res.filled_notional == 100.0


def test_funding_and_earnings_roundtrip(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        s.upsert_funding([FundingRate(venue=Venue.BITGET_UMCBL, symbol="TSLAUSDT", ts=T0, rate=0.0001, interval_hours=8, observed_at=T0)])
        assert s.get_funding(Venue.BITGET_UMCBL, "TSLAUSDT")["rate"].iloc[0] == 0.0001
        e = EarningsEvent(ticker="TSLA", report_date=T0, timing="amc", eps_estimate=0.5, source="nasdaq", observed_at=T0)
        s.upsert_earnings([e])
        # Second source observation fills in the actual without losing the estimate.
        s.upsert_earnings([EarningsEvent(ticker="TSLA", report_date=T0, source="nasdaq", eps_actual=0.6, observed_at=T0 + timedelta(days=1))])
        got = s.get_earnings("TSLA")[0]
        assert got.eps_estimate == 0.5 and got.eps_actual == 0.6 and got.observed_at == T0
        assert s.get_earnings("TSLA", as_of=T0 - timedelta(days=1)) == []


def test_sync_log(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        assert s.last_sync("bars") is None
        s.log_sync("bars", venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", rows=10, started_at=T0, finished_at=T0 + timedelta(minutes=1))
        assert s.last_sync("bars", venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT") == T0 + timedelta(minutes=1)
