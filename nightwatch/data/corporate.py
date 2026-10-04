"""Dividends, splits and exchange notices for the stocks behind the tokens.

Where each fact comes from, verified live on 2026-10-04 (no key for any of them):

* **Nasdaq** ``/api/quote/{symbol}/dividends?assetclass=stocks`` - every dividend with its
  ex-date, cash amount, *declaration date* and payment date, upcoming ones included (AAPL
  listed the 2026-08-10 ex-date declared on 2026-07-30). The declaration date is what
  makes the read point-in-time: a dividend only counts for a report as of a moment
  after it was declared. A company that pays none answers with ``rows: null``.
* **Nasdaq** ``/api/calendar/splits`` - the forward split calendar for the whole market
  in one request: symbol, ``new : old`` ratio and effective date. No announcement date,
  so the desk's own first sighting stands in for it.
* **Yahoo chart** ``events=div,splits`` - past dividends and splits, for the symbols
  Nasdaq does not cover (ETFs) and for a split history. Dates only, no announcement date.
* **Bitget announcements** ``/api/v2/public/annoucements`` - the exchange's own notices.
  Bitget publishes "Cash Dividend Settlement" notices for its stock perpetuals and
  trading/withdrawal suspensions for named rTokens. The feed holds only the latest ten per
  type, so it is a recent-notice read, not a calendar.

Bitget's data MCP lists a ``equity_fundamental_dividends`` entry too. It was not used: the
service answered HTTP 503 for every query (its existing quote entry as well) for the whole
of the session this was built in, so what its rows look like could not be checked.

Nothing here is guessed. A source that fails contributes nothing and the others still run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from nightwatch.data.http import HttpClient
from nightwatch.data.models import CorporateEvent
from nightwatch.data.nasdaq import _HEADERS as NASDAQ_HEADERS
from nightwatch.data.nasdaq import BASE_URL as NASDAQ_URL
from nightwatch.data.nasdaq import _et_midnight, _money, _parse_us_date
from nightwatch.data.store import Store
from nightwatch.data.yahoo import _HEADERS as YAHOO_HEADERS
from nightwatch.data.yahoo import BASE_URL as YAHOO_URL
from nightwatch.time_utils import ET, UTC, utc_now

log = logging.getLogger(__name__)

BITGET_URL = "https://api.bitget.com"
BITGET_ANN_PATH = "/api/v2/public/annoucements"
# The announcement types that can carry a dividend, suspension or delisting notice.
BITGET_ANN_TYPES = ("latest_news", "maintenance_system_updates", "symbol_delisting")

SRC_NASDAQ_DIV = "nasdaq_dividends"
SRC_NASDAQ_SPLIT = "nasdaq_splits"
SRC_YAHOO = "yahoo_chart"
SRC_BITGET = "bitget_announcement"

# Dividends older than this are not worth keeping: the desk looks forward, and a year of
# history is enough to see the payer's rhythm.
KEEP_BACK_DAYS = 400

_DIVIDEND_WORDS = re.compile(r"dividend", re.I)
_SUSPEND_WORDS = re.compile(r"suspend|halt", re.I)
_NOT_TRADING = re.compile(r"withdraw|deposit|network|transfer", re.I)


def _norm_ratio(text: str) -> str | None:
    """``"1 : 10"`` -> ``"1:10"``; ``"1.5:1"`` stays. None when it is not a ratio."""
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[:/]\s*([0-9]+(?:\.[0-9]+)?)\s*", str(text or ""))
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def _et_date_of(epoch_s: float) -> date:
    return datetime.fromtimestamp(epoch_s, tz=UTC).astimezone(ET).date()


# ------------------------------------------------------------------- parsers


def parse_nasdaq_dividends(ticker: str, payload: Any, observed: datetime, *, since: datetime | None = None) -> list[CorporateEvent]:  # noqa: ANN401
    rows = ((((payload or {}).get("data") or {}).get("dividends")) or {}).get("rows") or []
    out: list[CorporateEvent] = []
    for r in rows:
        ex = _parse_us_date(str(r.get("exOrEffDate", "")))
        if ex is None:
            continue
        when = _et_midnight(ex)
        if since is not None and when < since:
            continue
        declared = _parse_us_date(str(r.get("declarationDate", "")))
        out.append(CorporateEvent(
            ticker=ticker.upper(), kind="dividend", event_date=when, source=SRC_NASDAQ_DIV,
            amount=_money(r.get("amount")), currency=r.get("currency") or "USD",
            announced_at=_et_midnight(declared) if declared else None,
            detail=f"{r.get('type') or 'Cash'} dividend; record {r.get('recordDate') or 'n/a'}, paid {r.get('paymentDate') or 'n/a'}",
            observed_at=observed,
        ))
    return out


def parse_nasdaq_splits(payload: Any, wanted: set[str], observed: datetime) -> list[CorporateEvent]:  # noqa: ANN401
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    out: list[CorporateEvent] = []
    for r in rows:
        symbol = str(r.get("symbol", "")).upper().strip()
        d = _parse_us_date(str(r.get("executionDate", "")))
        if symbol not in wanted or d is None:
            continue
        ratio = _norm_ratio(r.get("ratio"))
        out.append(CorporateEvent(
            ticker=symbol, kind="split", event_date=_et_midnight(d), source=SRC_NASDAQ_SPLIT,
            ratio=ratio, detail=f"split {ratio or r.get('ratio')} (new:old)", observed_at=observed,
        ))
    return out


def parse_yahoo_events(ticker: str, payload: Any, observed: datetime, *, since: datetime | None = None) -> list[CorporateEvent]:  # noqa: ANN401
    results = (((payload or {}).get("chart") or {}).get("result")) or []
    events = (results[0].get("events") if results else None) or {}
    out: list[CorporateEvent] = []
    for ev in (events.get("dividends") or {}).values():
        if ev.get("date") is None or ev.get("amount") is None:
            continue
        when = _et_midnight(_et_date_of(float(ev["date"])))
        if since is None or when >= since:
            out.append(CorporateEvent(ticker=ticker.upper(), kind="dividend", event_date=when, source=SRC_YAHOO,
                                      amount=float(ev["amount"]), currency="USD", detail="cash dividend", observed_at=observed))
    for ev in (events.get("splits") or {}).values():
        if ev.get("date") is None:
            continue
        ratio = _norm_ratio(ev.get("splitRatio") or f"{ev.get('numerator')}:{ev.get('denominator')}")
        out.append(CorporateEvent(ticker=ticker.upper(), kind="split", event_date=_et_midnight(_et_date_of(float(ev["date"]))), source=SRC_YAHOO,
                                  ratio=ratio, detail=f"split {ratio} (new:old)", observed_at=observed))
    return out


def tickers_named(title: str, wanted: set[str]) -> set[str]:
    """Which of our tickers an announcement title names: ``rMSTR`` (the spot token) or
    ``CMCSAUSDT`` / ``RTSLAUSDT`` (the perpetual / spot symbol)."""
    found: set[str] = set()
    for tok in re.split(r"[^A-Za-z0-9]+", title):
        if not tok:
            continue
        if tok.endswith("USDT") and len(tok) > 4:
            base = tok[:-4]
            for cand in (base, base[1:] if base.startswith("R") else None):
                if cand and cand in wanted:
                    found.add(cand)
        elif tok.startswith("r") and tok[1:].isupper() and tok[1:] in wanted:
            found.add(tok[1:])
    return found


def parse_bitget_announcements(rows: Iterable[dict[str, Any]], wanted: set[str], observed: datetime) -> list[CorporateEvent]:
    out: list[CorporateEvent] = []
    for r in rows:
        title = str(r.get("annTitle") or "")
        try:
            at = datetime.fromtimestamp(int(r["cTime"]) / 1000, tz=UTC)
        except (KeyError, TypeError, ValueError):
            continue
        names = tickers_named(title, wanted)
        if not names:
            continue
        if _DIVIDEND_WORDS.search(title):
            kind = "notice"
        elif _SUSPEND_WORDS.search(title) and not _NOT_TRADING.search(title):
            kind = "suspension"
        else:
            kind = "notice"
        for t in sorted(names):
            out.append(CorporateEvent(
                ticker=t, kind=kind, event_date=_et_midnight(at.astimezone(ET).date()), source=SRC_BITGET,
                announced_at=at, detail=title, url=r.get("annUrl") or None, observed_at=observed,
            ))
    return out


# ------------------------------------------------------------------- clients


class CorporateEventsClient:
    """Fetches the three public sources. Each method fails soft: the caller keeps going."""

    def __init__(self, *, nasdaq: HttpClient | None = None, yahoo: HttpClient | None = None, bitget: HttpClient | None = None):
        self._nasdaq = nasdaq or HttpClient(NASDAQ_URL, headers=NASDAQ_HEADERS, rate_per_sec=2.0, burst=2, timeout=15.0)
        self._yahoo = yahoo or HttpClient(YAHOO_URL, headers=YAHOO_HEADERS, rate_per_sec=2.0, burst=2, timeout=15.0)
        self._bitget = bitget or HttpClient(BITGET_URL, rate_per_sec=2.0, burst=2, timeout=15.0)

    def close(self) -> None:
        for c in (self._nasdaq, self._yahoo, self._bitget):
            c.close()

    def dividends(self, ticker: str, *, now: datetime | None = None) -> list[CorporateEvent]:
        now = now or utc_now()
        payload = self._nasdaq.get_json(f"/api/quote/{ticker.lower()}/dividends", {"assetclass": "stocks"})
        return parse_nasdaq_dividends(ticker, payload, now, since=now - timedelta(days=KEEP_BACK_DAYS))

    def splits_calendar(self, wanted: set[str], *, now: datetime | None = None) -> list[CorporateEvent]:
        payload = self._nasdaq.get_json("/api/calendar/splits")
        return parse_nasdaq_splits(payload, wanted, now or utc_now())

    def yahoo_events(self, yahoo_ticker: str, ticker: str, *, now: datetime | None = None) -> list[CorporateEvent]:
        payload = self._yahoo.get_json(f"/v8/finance/chart/{yahoo_ticker}", {"range": "2y", "interval": "1d", "events": "div,splits"})
        now = now or utc_now()
        return parse_yahoo_events(ticker, payload, now, since=now - timedelta(days=KEEP_BACK_DAYS))

    def announcements(self, wanted: set[str], *, now: datetime | None = None) -> list[CorporateEvent]:
        out: list[CorporateEvent] = []
        seen: set[str] = set()
        for ann_type in BITGET_ANN_TYPES:
            payload = self._bitget.get_json(BITGET_ANN_PATH, {"language": "en_US", "annType": ann_type})
            rows = [r for r in ((payload or {}).get("data") or []) if str(r.get("annId")) not in seen]
            seen.update(str(r.get("annId")) for r in rows)
            out.extend(parse_bitget_announcements(rows, wanted, now or utc_now()))
        return out


def sync_corporate_events(store: Store, entries: Sequence[Any], client: CorporateEventsClient | None = None) -> int:
    """Refresh every source for every universe entry; one failure never stops the rest.

    ``entries`` are ``UniverseEntry`` (``ticker`` and ``yahoo_ticker`` are read).
    """
    began = utc_now()
    wanted = {e.ticker.upper() for e in entries}
    n = 0

    def put(events: list[CorporateEvent]) -> None:
        nonlocal n
        n += store.upsert_corporate_events(events)

    for label, fetch in (("splits calendar", lambda: client.splits_calendar(wanted)), ("bitget announcements", lambda: client.announcements(wanted))):
        try:
            put(fetch())
        except Exception as exc:  # noqa: BLE001 - one source down must not stop the others
            log.warning("corporate events: %s failed: %s", label, exc)
    for e in entries:
        for label, fetch in (("nasdaq dividends", lambda e=e: client.dividends(e.ticker)),
                             ("yahoo events", lambda e=e: client.yahoo_events(e.yahoo_ticker, e.ticker))):
            try:
                put(fetch())
            except Exception as exc:  # noqa: BLE001
                log.info("corporate events: %s %s failed: %s", label, e.ticker, exc)
    store.log_sync("corporate_events", rows=n, started_at=began, finished_at=utc_now())
    return n
