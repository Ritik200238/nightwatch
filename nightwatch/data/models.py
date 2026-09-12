"""Typed records shared by every data source and the store.

Design rules
------------
* Timestamps are aware UTC datetimes. Sources convert at the boundary.
* Prices/sizes are floats parsed from source strings; we keep the raw source
  precision in SQLite via ``REAL`` and never re-round on the way in.
* Every record that can be used in analysis carries ``observed_at`` — when *we*
  learned it — so point-in-time queries can exclude anything we could not have
  known at a given moment (see ``store.py``).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nightwatch.time_utils import ensure_utc


class Venue(str, Enum):
    BITGET_SPOT = "bitget_spot"
    BITGET_UMCBL = "bitget_usdt_futures"  # USDT-margined perpetuals
    YAHOO = "yahoo"


class PriceKind(str, Enum):
    TRADE = "trade"  # last-trade candles
    INDEX = "index"  # exchange index (fair value) candles
    MARK = "mark"  # mark-price candles


class Interval(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def seconds(self) -> int:
        return {
            Interval.M1: 60,
            Interval.M5: 300,
            Interval.M15: 900,
            Interval.H1: 3600,
            Interval.H4: 14400,
            Interval.D1: 86400,
        }[self]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bar(_Record):
    venue: Venue
    symbol: str
    interval: Interval
    kind: PriceKind = PriceKind.TRADE
    ts: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume_base: float | None = None
    volume_quote: float | None = None
    observed_at: datetime

    @field_validator("ts", "observed_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @field_validator("high")
    @classmethod
    def _hi(cls, v: float) -> float:
        if v < 0:
            raise ValueError("negative high")
        return v


class InstrumentType(str, Enum):
    SPOT = "spot"
    PERP = "perp"
    EQUITY = "equity"


class Instrument(_Record):
    venue: Venue
    symbol: str
    type: InstrumentType
    base: str
    quote: str
    underlying_ticker: str | None = None  # e.g. "TSLA" for RTSLAUSDT / TSLAUSDT
    is_tokenized_stock: bool = False
    status: str
    price_precision: int | None = None
    quantity_precision: int | None = None
    min_notional_quote: float | None = None
    maker_fee: float | None = None  # fraction, e.g. 0.001
    taker_fee: float | None = None
    max_leverage: int | None = None
    funding_interval_hours: int | None = None
    listed_at: datetime | None = None
    observed_at: datetime
    raw: dict = Field(default_factory=dict)


class OrderBookLevel(_Record):
    price: float
    size: float


class OrderBookSnapshot(_Record):
    venue: Venue
    symbol: str
    ts: datetime  # exchange timestamp of the snapshot
    observed_at: datetime
    bids: tuple[OrderBookLevel, ...]  # best first
    asks: tuple[OrderBookLevel, ...]  # best first

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float | None:
        mid = self.mid
        if mid is None or mid <= 0:
            return None
        return (self.best_ask - self.best_bid) / mid * 1e4  # type: ignore[operator]


class FundingRate(_Record):
    venue: Venue
    symbol: str
    ts: datetime  # funding time
    rate: float  # fraction per interval
    interval_hours: int | None = None
    observed_at: datetime


class Ticker(_Record):
    venue: Venue
    symbol: str
    ts: datetime
    last: float | None
    bid: float | None
    ask: float | None
    bid_size: float | None = None
    ask_size: float | None = None
    index_price: float | None = None
    mark_price: float | None = None
    funding_rate: float | None = None
    open_interest: float | None = None
    volume_24h_quote: float | None = None
    observed_at: datetime


class EarningsEvent(_Record):
    ticker: str
    report_date: datetime  # ET calendar date at 00:00 ET, stored as UTC instant
    timing: str | None = None  # "bmo" (before open) / "amc" (after close) / "unknown"
    eps_estimate: float | None = None
    eps_actual: float | None = None
    surprise_pct: float | None = None
    fiscal_quarter_end: str | None = None
    source: str
    observed_at: datetime


class MacroRelease(_Record):
    series_id: str  # FRED series (e.g. CPIAUCSL) or event code (e.g. FOMC)
    name: str
    release_ts: datetime  # scheduled release instant, UTC
    value: float | None = None
    period: str | None = None
    source: str
    observed_at: datetime


class NewsItem(_Record):
    source: str
    id: str  # stable per-source id (guid/link hash)
    published_at: datetime
    title: str
    link: str | None = None
    summary: str | None = None
    tickers: tuple[str, ...] = ()
    observed_at: datetime
