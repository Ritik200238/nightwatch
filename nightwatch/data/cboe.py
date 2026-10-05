"""Listed-options quotes from Cboe's public delayed-quote feed.

Verified live on 2026-10-05 (no key; the CDN answers a plain GET, redirects included):

* ``https://cdn.cboe.com/api/global/delayed_quotes/options/<TICKER>.json`` returns the
  whole chain in one document (TSLA: about 5,000 contracts, 2.2 MB) with a ``timestamp``
  (US Eastern wall clock), the underlying's ``current_price`` and ``last_trade_time``, and
  per contract: ``option`` (OCC symbol, ``TSLA261009C00365000`` = root, YYMMDD, C/P,
  strike x 1000), ``bid``, ``ask``, ``iv`` (a fraction: 0.3486 = 34.9 %; the underlying's ``iv30`` is in percent), ``open_interest``.
* A ticker with no listed options is not a 200 with an empty chain; the CDN answers 403/404,
  which is read here as "no options", not as an outage.
* Quotes are delayed about 15 minutes, and outside the session they are the last session's.

The document is far too big to keep, so it is reduced at once to what the implied move
needs: per expiry, the at-the-money strike's call and put (mid, IV). That summary is a few
kilobytes and is what the desk caches.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from nightwatch.data.http import HttpClient, RetryPolicy, UpstreamError

log = logging.getLogger(__name__)

BASE_URL = "https://cdn.cboe.com"
PATH = "/api/global/delayed_quotes/options/{ticker}.json"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
_OCC = re.compile(r"^(?P<root>[A-Z.]{1,6})(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class AtmQuote:
    """The at-the-money strike of one expiry."""

    expiry: date
    strike: float
    call_mid: float
    put_mid: float
    call_iv: float  # fractions: 0.35 = 35 %
    put_iv: float
    n_strikes: int  # strikes of this expiry that had a usable two-sided quote on both sides


@dataclass
class OptionsChain:
    ticker: str
    spot: float
    quote_ts: datetime | None  # the underlying's last trade, UTC
    fetched_at: datetime
    iv30: float | None  # Cboe's 30-day IV for the underlying, a fraction
    expiries: list[AtmQuote] = field(default_factory=list)

    @property
    def listed(self) -> bool:
        return bool(self.expiries)


class NoOptions(LookupError):
    """The underlying has no listed options (or Cboe does not carry it)."""


def _num(x: Any) -> float | None:  # noqa: ANN401
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN is not a number here


def _two_sided(row: dict[str, Any]) -> tuple[float, float] | None:
    """(mid, iv) of a contract with a real two-sided quote and a positive IV, else None."""
    bid, ask, iv = _num(row.get("bid")), _num(row.get("ask")), _num(row.get("iv"))
    if bid is None or ask is None or iv is None or bid <= 0 or ask < bid or iv <= 0:
        return None
    return (bid + ask) / 2.0, iv


def parse_chain(doc: dict[str, Any], ticker: str, fetched_at: datetime) -> OptionsChain:
    """Reduce Cboe's chain document to one at-the-money quote per expiry."""
    data = doc.get("data") or {}
    spot = _num(data.get("current_price"))
    if not spot or spot <= 0:
        raise UpstreamError(f"cboe {ticker}: no underlying price")
    quote_ts = None
    raw_ts = data.get("last_trade_time")
    if raw_ts:
        try:
            quote_ts = datetime.fromisoformat(str(raw_ts)).replace(tzinfo=_ET).astimezone(ZoneInfo("UTC"))
        except ValueError:
            quote_ts = None
    iv30 = _num(data.get("iv30"))
    iv30 = iv30 / 100.0 if iv30 else None  # the underlying's iv30 is in percent, unlike the per-contract iv
    by_expiry: dict[date, dict[float, dict[str, tuple[float, float]]]] = {}
    for row in data.get("options") or []:
        m = _OCC.match(str(row.get("option") or ""))
        if not m or m["root"] != ticker:  # adjusted or look-alike roots are not this stock's chain
            continue
        quote = _two_sided(row)
        if quote is None:
            continue
        yymmdd = m["yymmdd"]
        try:
            expiry = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:]))
        except ValueError:
            continue
        by_expiry.setdefault(expiry, {}).setdefault(int(m["strike"]) / 1000.0, {})[m["cp"]] = quote
    out: list[AtmQuote] = []
    for expiry in sorted(by_expiry):
        both = {k: v for k, v in by_expiry[expiry].items() if "C" in v and "P" in v}
        if not both:
            continue
        k = min(both, key=lambda s: abs(s - spot))
        (cm, civ), (pm, piv) = both[k]["C"], both[k]["P"]
        out.append(AtmQuote(expiry=expiry, strike=k, call_mid=cm, put_mid=pm, call_iv=civ, put_iv=piv, n_strikes=len(both)))
    return OptionsChain(ticker=ticker, spot=spot, quote_ts=quote_ts, fetched_at=fetched_at, iv30=iv30, expiries=out)


class CboeOptionsClient:
    """Fetches and reduces one ticker's chain. One request at a time: each is a 2 MB body
    that is parsed in memory, and the box has 1 GB."""

    def __init__(self, *, http: HttpClient | None = None):
        self._http = http or HttpClient(
            BASE_URL, headers=_HEADERS, timeout=12.0, rate_per_sec=2.0, burst=2,
            retry=RetryPolicy(max_attempts=2, base_delay=0.5, max_delay=2.0),
        )
        self._lock = threading.Lock()

    def get_chain(self, ticker: str, *, fetched_at: datetime) -> OptionsChain:
        """Raises ``NoOptions`` for a name Cboe does not carry, ``UpstreamError`` or a
        transport error for anything else that goes wrong."""
        with self._lock:
            try:
                doc = self._http.get_json(PATH.format(ticker=ticker))
            except UpstreamError as exc:
                if exc.status in (403, 404):
                    raise NoOptions(ticker) from exc
                raise
            chain = parse_chain(doc, ticker, fetched_at)
            del doc
        if not chain.listed:
            raise NoOptions(ticker)
        return chain

    def close(self) -> None:
        self._http.close()
