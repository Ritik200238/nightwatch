"""Source interfaces.

The engine only ever talks to these protocols. Tests use in-memory fakes; production
wires the concrete clients in ``bitget.py``, ``yahoo.py``, ``nasdaq.py``, ``fred.py``
and ``rss.py``. Keeping the surface small is deliberate: every method here is one we
have verified against the live upstream (see the probes in git history).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from nightwatch.data.models import (
    Bar,
    EarningsEvent,
    FundingRate,
    Instrument,
    Interval,
    MacroRelease,
    NewsItem,
    OrderBookSnapshot,
    PriceKind,
    Ticker,
)


@runtime_checkable
class MarketDataSource(Protocol):
    """Candles, books, tickers and funding for one venue family."""

    def list_instruments(self) -> Sequence[Instrument]: ...

    def get_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime,
        *,
        kind: PriceKind = PriceKind.TRADE,
    ) -> list[Bar]:
        """Bars with ``start <= ts < end``, ascending, de-duplicated."""
        ...

    def get_orderbook(self, symbol: str, depth: int = 100) -> OrderBookSnapshot: ...

    def get_ticker(self, symbol: str) -> Ticker: ...

    def get_funding_history(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[FundingRate]: ...


@runtime_checkable
class EquityDataSource(Protocol):
    def get_bars(self, ticker: str, interval: Interval, start: datetime, end: datetime) -> list[Bar]: ...


@runtime_checkable
class EarningsSource(Protocol):
    def get_calendar(self, start: datetime, end: datetime) -> list[EarningsEvent]: ...

    def get_history(self, ticker: str) -> list[EarningsEvent]: ...


@runtime_checkable
class MacroSource(Protocol):
    def get_series(self, series_id: str, start: datetime, end: datetime) -> list[MacroRelease]: ...

    def get_release_calendar(self, start: datetime, end: datetime) -> list[MacroRelease]: ...


@runtime_checkable
class NewsSource(Protocol):
    def fetch(self, feeds: Iterable[str] | None = None) -> list[NewsItem]: ...
