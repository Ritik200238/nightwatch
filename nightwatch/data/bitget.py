"""Bitget public market-data client (spot + USDT-margined perpetuals).

Facts this client is built on (all verified live on 2026-09-12, see git history):

* Recent candles: ``/api/v2/spot/market/candles`` and ``/api/v2/mix/market/candles``
  return up to 1000 bars ascending; they accept ``startTime``/``endTime``.
* Historical candles: ``.../history-candles`` return at most **200** bars per call,
  ascending, ending at ``endTime`` (inclusive). Spot history for rTokens reaches back
  to January 2025; perps to at least October 2025.
* Perp candles accept ``kLineType`` = ``MARKET`` | ``INDEX`` | ``MARK`` on both endpoints.
* Timestamps are epoch milliseconds as strings. Prices/sizes are strings.
* Spot candle row: ``[ts, open, high, low, close, baseVolume, usdtVolume, quoteVolume]``.
  Perp candle row: ``[ts, open, high, low, close, baseVolume, quoteVolume]``.
* The order book endpoint returns the whole book (≈60 levels for rTokens) when asked
  for more than it has.
* A remaining-budget header (``x-mbx-used-remain-limit``) is present on responses.
* Success payloads carry ``code == "00000"``; anything else is an error.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from nightwatch.data.http import HttpClient, UpstreamError
from nightwatch.data.models import (
    Bar,
    FundingRate,
    Instrument,
    InstrumentType,
    Interval,
    OrderBookLevel,
    OrderBookSnapshot,
    PriceKind,
    Ticker,
    Venue,
)
from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms, utc_now

log = logging.getLogger(__name__)

BASE_URL = "https://api.bitget.com"
PRODUCT_TYPE = "usdt-futures"
HISTORY_PAGE = 200
RECENT_PAGE = 1000
FUNDING_PAGE = 100

_SPOT_INTERVAL = {
    Interval.M1: "1min",
    Interval.M5: "5min",
    Interval.M15: "15min",
    Interval.H1: "1h",
    Interval.H4: "4h",
    Interval.D1: "1day",
}
_PERP_INTERVAL = {
    Interval.M1: "1m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.H1: "1H",
    Interval.H4: "4H",
    Interval.D1: "1D",
}
_KLINE_TYPE = {PriceKind.TRADE: "MARKET", PriceKind.INDEX: "INDEX", PriceKind.MARK: "MARK"}


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _i(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


class BitgetPublicClient:
    """One instance per venue family. Implements ``MarketDataSource``."""

    def __init__(
        self,
        venue: Venue,
        *,
        http: HttpClient | None = None,
        rate_per_sec: float = 8.0,
    ):
        if venue not in (Venue.BITGET_SPOT, Venue.BITGET_UMCBL):
            raise ValueError(f"unsupported venue {venue}")
        self.venue = venue
        self.is_perp = venue == Venue.BITGET_UMCBL
        self._http = http or HttpClient(
            BASE_URL,
            headers={"Accept": "application/json", "User-Agent": "nightwatch/0.1"},
            rate_per_sec=rate_per_sec,
            burst=int(rate_per_sec),
            remaining_header="x-mbx-used-remain-limit",
        )

    # ------------------------------------------------------------------ plumbing

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        payload = self._http.get_json(path, params)
        if not isinstance(payload, dict) or payload.get("code") != "00000":
            raise UpstreamError(
                f"bitget {path}: {payload!r}"[:300], payload=payload
            )
        return payload.get("data")

    def _interval(self, interval: Interval) -> str:
        return (_PERP_INTERVAL if self.is_perp else _SPOT_INTERVAL)[interval]

    def server_time(self) -> datetime:
        data = self._get("/api/v2/public/time")
        return from_epoch_ms(data["serverTime"])

    # -------------------------------------------------------------- instruments

    def list_instruments(self) -> Sequence[Instrument]:
        now = utc_now()
        if self.is_perp:
            rows = self._get("/api/v2/mix/market/contracts", {"productType": PRODUCT_TYPE})
            return [self._parse_contract(r, now) for r in rows]
        rows = self._get("/api/v2/spot/public/symbols")
        return [self._parse_spot_symbol(r, now) for r in rows]

    def _parse_spot_symbol(self, r: dict[str, Any], now: datetime) -> Instrument:
        base = str(r.get("baseCoin", ""))
        symbol = str(r["symbol"])
        # Tokenized US stocks on Bitget spot are listed as rTICKER (e.g. rTSLA).
        tokenized = base.startswith("r") and base[1:].isalpha() and base[1:].isupper()
        return Instrument(
            venue=self.venue,
            symbol=symbol,
            type=InstrumentType.SPOT,
            base=base,
            quote=str(r.get("quoteCoin", "")),
            underlying_ticker=base[1:] if tokenized else None,
            is_tokenized_stock=tokenized,
            status=str(r.get("status", "")),
            price_precision=_i(r.get("pricePrecision")),
            quantity_precision=_i(r.get("quantityPrecision")),
            min_notional_quote=_f(r.get("minTradeUSDT")),
            maker_fee=_f(r.get("makerFeeRate")),
            taker_fee=_f(r.get("takerFeeRate")),
            listed_at=from_epoch_ms(r["openTime"]) if r.get("openTime") else None,
            observed_at=now,
            raw=dict(r),
        )

    def _parse_contract(self, r: dict[str, Any], now: datetime) -> Instrument:
        base = str(r.get("baseCoin", ""))
        tokenized = str(r.get("isRwa", "")).upper() == "YES"
        return Instrument(
            venue=self.venue,
            symbol=str(r["symbol"]),
            type=InstrumentType.PERP,
            base=base,
            quote=str(r.get("quoteCoin", "")),
            underlying_ticker=base if tokenized else None,
            is_tokenized_stock=tokenized,
            status=str(r.get("symbolStatus", "")),
            price_precision=_i(r.get("pricePlace")),
            quantity_precision=_i(r.get("volumePlace")),
            min_notional_quote=_f(r.get("minTradeUSDT")),
            maker_fee=_f(r.get("makerFeeRate")),
            taker_fee=_f(r.get("takerFeeRate")),
            max_leverage=_i(r.get("maxLever")),
            funding_interval_hours=_i(r.get("fundInterval")),
            listed_at=from_epoch_ms(r["openTime"]) if r.get("openTime") else None,
            observed_at=now,
            raw=dict(r),
        )

    # ------------------------------------------------------------------- candles

    def get_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        *,
        kind: PriceKind = PriceKind.TRADE,
    ) -> list[Bar]:
        """All bars with ``start <= ts < end``, ascending, de-duplicated.

        Pages backwards from ``end`` through the history endpoint (200/call) because
        it is the only endpoint verified to reach arbitrarily far back. Stops when a
        page is empty, makes no progress, or crosses ``start``.
        """
        start, end = ensure_utc(start), ensure_utc(end)
        if end <= start:
            return []
        if kind != PriceKind.TRADE and not self.is_perp:
            raise ValueError("index/mark candles exist only for perpetuals")

        step = timedelta(seconds=interval.seconds)
        by_ts: dict[int, Bar] = {}
        cursor_end_ms = to_epoch_ms(end) - 1  # endTime is inclusive upstream
        start_ms = to_epoch_ms(start)
        observed = utc_now()
        pages = 0

        while cursor_end_ms >= start_ms:
            rows = self._candles_page(symbol, interval, kind, end_ms=cursor_end_ms)
            pages += 1
            if not rows:
                break
            page_min = None
            for row in rows:
                bar = self._parse_candle(row, symbol, interval, kind, observed)
                ts_ms = to_epoch_ms(bar.ts)
                if page_min is None or ts_ms < page_min:
                    page_min = ts_ms
                if start_ms <= ts_ms < to_epoch_ms(end):
                    by_ts[ts_ms] = bar
            if page_min is None or page_min - 1 >= cursor_end_ms:
                break  # no progress: upstream returned the same window
            cursor_end_ms = page_min - 1
            if len(rows) < HISTORY_PAGE:
                # Short page means we hit the start of available history.
                break

        bars = [by_ts[k] for k in sorted(by_ts)]
        _warn_on_gaps(bars, step, symbol)
        log.debug("bitget %s %s %s: %d bars in %d pages", self.venue.value, symbol, interval.value, len(bars), pages)
        return bars

    def _candles_page(
        self, symbol: str, interval: Interval, kind: PriceKind, *, end_ms: int
    ) -> list[list[str]]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "granularity": self._interval(interval),
            "endTime": str(end_ms),
            "limit": str(HISTORY_PAGE),
        }
        if self.is_perp:
            params["productType"] = PRODUCT_TYPE
            params["kLineType"] = _KLINE_TYPE[kind]
            path = "/api/v2/mix/market/history-candles"
        else:
            path = "/api/v2/spot/market/history-candles"
        data = self._get(path, params)
        return list(data or [])

    def get_recent_bars(
        self,
        symbol: str,
        interval: Interval,
        limit: int = RECENT_PAGE,
        *,
        kind: PriceKind = PriceKind.TRADE,
    ) -> list[Bar]:
        """Latest ``limit`` bars (≤ 1000) from the recent endpoint. Used for
        incremental refreshes where one call covers the whole delta."""
        if not 1 <= limit <= RECENT_PAGE:
            raise ValueError("limit must be 1..1000")
        params: dict[str, Any] = {
            "symbol": symbol,
            "granularity": self._interval(interval),
            "limit": str(limit),
        }
        if self.is_perp:
            params["productType"] = PRODUCT_TYPE
            params["kLineType"] = _KLINE_TYPE[kind]
            path = "/api/v2/mix/market/candles"
        else:
            if kind != PriceKind.TRADE:
                raise ValueError("index/mark candles exist only for perpetuals")
            path = "/api/v2/spot/market/candles"
        observed = utc_now()
        rows = self._get(path, params) or []
        bars = [self._parse_candle(r, symbol, interval, kind, observed) for r in rows]
        bars.sort(key=lambda b: b.ts)
        return bars

    def _parse_candle(
        self, row: Sequence[str], symbol: str, interval: Interval, kind: PriceKind, observed: datetime
    ) -> Bar:
        if len(row) < 6:
            raise UpstreamError(f"bitget candle row too short: {row!r}")
        volume_base = _f(row[5])
        if self.is_perp:
            volume_quote = _f(row[6]) if len(row) > 6 else None
        else:
            # spot: [.., baseVolume, usdtVolume, quoteVolume]
            volume_quote = _f(row[7]) if len(row) > 7 else _f(row[6]) if len(row) > 6 else None
        return Bar(
            venue=self.venue,
            symbol=symbol,
            interval=interval,
            kind=kind,
            ts=from_epoch_ms(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume_base=volume_base,
            volume_quote=volume_quote,
            observed_at=observed,
        )

    # ---------------------------------------------------------------- order book

    def get_orderbook(self, symbol: str, depth: int = 150) -> OrderBookSnapshot:
        observed = utc_now()
        if self.is_perp:
            data = self._get(
                "/api/v2/mix/market/merge-depth",
                {"symbol": symbol, "productType": PRODUCT_TYPE, "limit": "max"},
            )
        else:
            data = self._get("/api/v2/spot/market/orderbook", {"symbol": symbol, "limit": str(depth)})
        bids = tuple(OrderBookLevel(price=float(p), size=float(s)) for p, s in data.get("bids", []))
        asks = tuple(OrderBookLevel(price=float(p), size=float(s)) for p, s in data.get("asks", []))
        # Defensive ordering: best first regardless of upstream order.
        bids = tuple(sorted(bids, key=lambda lv: -lv.price))
        asks = tuple(sorted(asks, key=lambda lv: lv.price))
        ts = from_epoch_ms(data["ts"]) if data.get("ts") else observed
        return OrderBookSnapshot(
            venue=self.venue, symbol=symbol, ts=ts, observed_at=observed, bids=bids, asks=asks
        )

    # -------------------------------------------------------------------- ticker

    def get_ticker(self, symbol: str) -> Ticker:
        observed = utc_now()
        if self.is_perp:
            rows = self._get("/api/v2/mix/market/ticker", {"symbol": symbol, "productType": PRODUCT_TYPE})
        else:
            rows = self._get("/api/v2/spot/market/tickers", {"symbol": symbol})
        if not rows:
            raise UpstreamError(f"bitget: no ticker for {symbol}")
        r = rows[0]
        return Ticker(
            venue=self.venue,
            symbol=symbol,
            ts=from_epoch_ms(r["ts"]) if r.get("ts") else observed,
            last=_f(r.get("lastPr")),
            bid=_f(r.get("bidPr")),
            ask=_f(r.get("askPr")),
            bid_size=_f(r.get("bidSz")),
            ask_size=_f(r.get("askSz")),
            index_price=_f(r.get("indexPrice")),
            mark_price=_f(r.get("markPrice")),
            funding_rate=_f(r.get("fundingRate")),
            open_interest=_f(r.get("holdingAmount")),
            volume_24h_quote=_f(r.get("usdtVolume")) or _f(r.get("quoteVolume")),
            observed_at=observed,
        )

    # ------------------------------------------------------------------- funding

    def get_current_funding(self, symbol: str) -> FundingRate:
        if not self.is_perp:
            raise ValueError("funding exists only for perpetuals")
        observed = utc_now()
        rows = self._get("/api/v2/mix/market/current-fund-rate", {"symbol": symbol, "productType": PRODUCT_TYPE})
        r = rows[0]
        return FundingRate(
            venue=self.venue,
            symbol=symbol,
            ts=from_epoch_ms(r["nextUpdate"]) if r.get("nextUpdate") else observed,
            rate=float(r["fundingRate"]),
            interval_hours=_i(r.get("fundingRateInterval")),
            observed_at=observed,
        )

    def get_funding_history(self, symbol: str, start: datetime, end: datetime) -> list[FundingRate]:
        if not self.is_perp:
            raise ValueError("funding exists only for perpetuals")
        start, end = ensure_utc(start), ensure_utc(end)
        observed = utc_now()
        out: dict[int, FundingRate] = {}
        page = 1
        while True:
            rows = self._get(
                "/api/v2/mix/market/history-fund-rate",
                {"symbol": symbol, "productType": PRODUCT_TYPE, "pageSize": str(FUNDING_PAGE), "pageNo": str(page)},
            ) or []
            if not rows:
                break
            oldest = None
            for r in rows:
                ts = from_epoch_ms(r["fundingTime"])
                ts_ms = to_epoch_ms(ts)
                oldest = ts_ms if oldest is None else min(oldest, ts_ms)
                if start <= ts < end:
                    out[ts_ms] = FundingRate(
                        venue=self.venue, symbol=symbol, ts=ts, rate=float(r["fundingRate"]), observed_at=observed
                    )
            if oldest is None or oldest < to_epoch_ms(start) or len(rows) < FUNDING_PAGE:
                break
            page += 1
        return [out[k] for k in sorted(out)]

    def close(self) -> None:
        self._http.close()


def _warn_on_gaps(bars: list[Bar], step: timedelta, symbol: str) -> None:
    """24/7 venues should have no gaps; log the first few so sync can report them."""
    missing = 0
    first_gap = None
    for prev, cur in zip(bars, bars[1:], strict=False):
        delta = cur.ts - prev.ts
        if delta > step:
            n = int(delta / step) - 1
            missing += n
            if first_gap is None:
                first_gap = (prev.ts, cur.ts)
    if missing:
        log.info("bitget %s: %d missing bars (first gap %s -> %s)", symbol, missing, *first_gap)
