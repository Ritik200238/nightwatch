"""Bitget client tests against a mocked transport (no network)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from nightwatch.data.bitget import BASE_URL, HISTORY_PAGE, BitgetPublicClient
from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import Interval, PriceKind, Venue

UTC = timezone.utc
H = 3_600_000


def ok(data):
    return httpx.Response(200, json={"code": "00000", "msg": "success", "requestTime": 0, "data": data})


def spot_client():
    return BitgetPublicClient(
        Venue.BITGET_SPOT,
        http=HttpClient(BASE_URL, rate_per_sec=1000, burst=1000),
    )


def perp_client():
    return BitgetPublicClient(
        Venue.BITGET_UMCBL,
        http=HttpClient(BASE_URL, rate_per_sec=1000, burst=1000),
    )


def spot_row(ts_ms: int, px: float = 100.0):
    return [str(ts_ms), str(px), str(px + 1), str(px - 1), str(px + 0.5), "10", "1000", "1000.5"]


def perp_row(ts_ms: int, px: float = 100.0):
    return [str(ts_ms), str(px), str(px + 1), str(px - 1), str(px + 0.5), "10", "1000"]


# --- candle parsing ---------------------------------------------------------------


@respx.mock
def test_spot_candle_columns_and_ordering():
    t0 = 1_789_000_000_000
    respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles").mock(
        return_value=ok([spot_row(t0 + H), spot_row(t0)])  # deliberately unsorted
    )
    bars = spot_client().get_bars(
        "RTSLAUSDT", Interval.H1, datetime.fromtimestamp(t0 / 1000, tz=UTC),
        datetime.fromtimestamp((t0 + 2 * H) / 1000, tz=UTC),
    )
    assert [b.ts.timestamp() * 1000 for b in bars] == [t0, t0 + H]
    b = bars[0]
    assert (b.open, b.high, b.low, b.close) == (100.0, 101.0, 99.0, 100.5)
    assert b.volume_base == 10.0 and b.volume_quote == 1000.5  # spot: quoteVolume is col 7
    assert b.kind == PriceKind.TRADE and b.venue == Venue.BITGET_SPOT


@respx.mock
def test_perp_candle_columns_and_kline_type_param():
    t0 = 1_789_000_000_000
    route = respx.get(f"{BASE_URL}/api/v2/mix/market/history-candles").mock(return_value=ok([perp_row(t0)]))
    bars = perp_client().get_bars(
        "TSLAUSDT", Interval.H1, datetime.fromtimestamp(t0 / 1000, tz=UTC),
        datetime.fromtimestamp((t0 + H) / 1000, tz=UTC), kind=PriceKind.INDEX,
    )
    assert bars[0].volume_quote == 1000.0
    assert bars[0].kind == PriceKind.INDEX
    params = dict(route.calls[0].request.url.params)
    assert params["kLineType"] == "INDEX" and params["productType"] == "usdt-futures"
    assert params["granularity"] == "1H"


def test_index_candles_rejected_for_spot():
    with pytest.raises(ValueError):
        spot_client().get_bars("RTSLAUSDT", Interval.H1, datetime(2026, 1, 1, tzinfo=UTC),
                               datetime(2026, 1, 2, tzinfo=UTC), kind=PriceKind.INDEX)


# --- pagination ------------------------------------------------------------------


@respx.mock
def test_backward_pagination_dedupes_and_respects_range():
    """Three pages of 200 hourly bars; the request window cuts both ends."""
    t_end = 1_789_000_000_000
    all_rows = {t_end - i * H: spot_row(t_end - i * H) for i in range(600)}

    def responder(request):
        end_ms = int(request.url.params["endTime"])
        page = sorted(ts for ts in all_rows if ts <= end_ms)[-HISTORY_PAGE:]
        return ok([all_rows[ts] for ts in page])

    respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles").mock(side_effect=responder)

    start = datetime.fromtimestamp((t_end - 450 * H) / 1000, tz=UTC)
    end = datetime.fromtimestamp((t_end - 50 * H) / 1000, tz=UTC)  # exclusive
    bars = spot_client().get_bars("RTSLAUSDT", Interval.H1, start, end)

    assert len(bars) == 400
    assert bars[0].ts == start
    assert bars[-1].ts == end - timedelta(hours=1)
    assert all(b2.ts - b1.ts == timedelta(hours=1) for b1, b2 in zip(bars, bars[1:], strict=False))


@respx.mock
def test_pagination_stops_on_short_page_and_no_progress():
    t_end = 1_789_000_000_000
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        # First call: a short page (history start reached); we must not loop forever.
        return ok([spot_row(t_end - 3 * H), spot_row(t_end - 2 * H)])

    respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles").mock(side_effect=responder)
    bars = spot_client().get_bars(
        "RTSLAUSDT", Interval.H1, datetime.fromtimestamp((t_end - 100 * H) / 1000, tz=UTC),
        datetime.fromtimestamp(t_end / 1000, tz=UTC),
    )
    assert len(bars) == 2 and calls["n"] == 1


@respx.mock
def test_empty_range_makes_no_request():
    route = respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles").mock(return_value=ok([]))
    assert spot_client().get_bars("X", Interval.H1, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)) == []
    assert not route.called


# --- instruments -------------------------------------------------------------------


@respx.mock
def test_spot_tokenized_detection_and_fees():
    respx.get(f"{BASE_URL}/api/v2/spot/public/symbols").mock(
        return_value=ok(
            [
                {"symbol": "RTSLAUSDT", "baseCoin": "rTSLA", "quoteCoin": "USDT", "status": "online",
                 "pricePrecision": "2", "quantityPrecision": "4", "minTradeUSDT": "10",
                 "takerFeeRate": "0.001", "makerFeeRate": "0.001", "openTime": "1780323652017"},
                {"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "status": "online",
                 "takerFeeRate": "0.002", "makerFeeRate": "0.002"},
                {"symbol": "HMSTRUSDT", "baseCoin": "HMSTR", "quoteCoin": "USDT", "status": "online"},
            ]
        )
    )
    ins = {i.symbol: i for i in spot_client().list_instruments()}
    assert ins["RTSLAUSDT"].is_tokenized_stock and ins["RTSLAUSDT"].underlying_ticker == "TSLA"
    assert ins["RTSLAUSDT"].taker_fee == 0.001 and ins["RTSLAUSDT"].min_notional_quote == 10.0
    assert ins["RTSLAUSDT"].listed_at is not None
    assert not ins["BTCUSDT"].is_tokenized_stock
    assert not ins["HMSTRUSDT"].is_tokenized_stock  # no r-prefix: not a stock token


@respx.mock
def test_perp_tokenized_detection_uses_isrwa():
    respx.get(f"{BASE_URL}/api/v2/mix/market/contracts").mock(
        return_value=ok(
            [
                {"symbol": "TSLAUSDT", "baseCoin": "TSLA", "quoteCoin": "USDT", "symbolStatus": "normal",
                 "makerFeeRate": "0.0002", "takerFeeRate": "0.0006", "maxLever": "100", "fundInterval": "8",
                 "pricePlace": "2", "volumePlace": "2", "isRwa": "YES", "openTime": "1769994062288"},
                {"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "symbolStatus": "normal", "isRwa": "NO"},
            ]
        )
    )
    ins = {i.symbol: i for i in perp_client().list_instruments()}
    assert ins["TSLAUSDT"].is_tokenized_stock and ins["TSLAUSDT"].underlying_ticker == "TSLA"
    assert ins["TSLAUSDT"].funding_interval_hours == 8 and ins["TSLAUSDT"].max_leverage == 100
    assert not ins["BTCUSDT"].is_tokenized_stock


# --- order book / ticker / funding --------------------------------------------------


@respx.mock
def test_orderbook_sorted_best_first():
    respx.get(f"{BASE_URL}/api/v2/spot/market/orderbook").mock(
        return_value=ok({"bids": [["99", "1"], ["100", "2"]], "asks": [["102", "1"], ["101", "3"]], "ts": "1789000000000"})
    )
    snap = spot_client().get_orderbook("RTSLAUSDT")
    assert snap.best_bid == 100.0 and snap.best_ask == 101.0
    assert snap.mid == 100.5 and round(snap.spread_bps, 2) == round(1 / 100.5 * 1e4, 2)


@respx.mock
def test_perp_ticker_fields():
    respx.get(f"{BASE_URL}/api/v2/mix/market/ticker").mock(
        return_value=ok([{"symbol": "TSLAUSDT", "lastPr": "365.16", "bidPr": "365.16", "askPr": "365.17",
                          "bidSz": "0.17", "askSz": "288.46", "indexPrice": "365.1925", "markPrice": "365.17",
                          "fundingRate": "0.0001", "holdingAmount": "42159.34", "usdtVolume": "15216190.897",
                          "ts": "1789198893480"}])
    )
    t = perp_client().get_ticker("TSLAUSDT")
    assert t.index_price == 365.1925 and t.mark_price == 365.17
    assert t.open_interest == 42159.34 and t.funding_rate == 0.0001


@respx.mock
def test_funding_history_pages_until_start():
    t_end = 1_789_000_000_000
    eight_h = 8 * H
    rows = [{"symbol": "TSLAUSDT", "fundingRate": "0.0001", "fundingTime": str(t_end - i * eight_h)} for i in range(250)]

    def responder(request):
        page = int(request.url.params["pageNo"])
        return ok(rows[(page - 1) * 100: page * 100])

    respx.get(f"{BASE_URL}/api/v2/mix/market/history-fund-rate").mock(side_effect=responder)
    start = datetime.fromtimestamp((t_end - 150 * eight_h) / 1000, tz=UTC)
    end = datetime.fromtimestamp((t_end + 1) / 1000, tz=UTC)
    out = perp_client().get_funding_history("TSLAUSDT", start, end)
    assert len(out) == 151
    assert out[0].ts == start and out[-1].ts.timestamp() * 1000 == t_end


# --- errors ------------------------------------------------------------------------


@respx.mock
def test_upstream_error_code_raises():
    respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles").mock(
        return_value=httpx.Response(200, json={"code": "40020", "msg": "Parameter limit error", "data": None})
    )
    with pytest.raises(UpstreamError):
        spot_client().get_bars("RTSLAUSDT", Interval.H1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))


@respx.mock
def test_transport_retries_then_succeeds_on_5xx():
    t0 = 1_789_000_000_000
    route = respx.get(f"{BASE_URL}/api/v2/spot/market/history-candles")
    route.side_effect = [httpx.Response(503), httpx.Response(503), ok([spot_row(t0)])]
    client = BitgetPublicClient(
        Venue.BITGET_SPOT,
        http=HttpClient(BASE_URL, rate_per_sec=1000, burst=1000),
    )
    client._http._retry.base_delay = 0.0  # keep the test fast
    bars = client.get_bars("RTSLAUSDT", Interval.H1, datetime.fromtimestamp(t0 / 1000, tz=UTC),
                           datetime.fromtimestamp((t0 + H) / 1000, tz=UTC))
    assert len(bars) == 1 and route.call_count == 3
