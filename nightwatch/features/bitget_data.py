"""More of Bitget's US-stock data catalogue, held per ticker and per entry.

``street.py`` reads four catalogue entries into one view. The service has ~67 entries, and
the equity ones that matter before holding a stock overnight (its own earnings calendar,
valuation and fundamentals, dividends, news headlines, analyst consensus) were not being
read. Each is an entry here, with:

* its own parameters and its own normaliser, written against a recorded real response;
* its own cache cell, so ``/sources`` can list it separately with when it last delivered
  and whether it is working;
* the same rules as the street feed: it never blocks an analysis and an outage reads as an
  outage.

The load rule that keeps a 1 GB box safe: **at most one call per ticker per entry per
hour**, counted from the last *attempt*, so a failing entry is not hammered. Only the
background refresh calls the service; an analysis and the chat tool read the cache and
nothing else.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from nightwatch.time_utils import UTC, utc_now

log = logging.getLogger(__name__)

MIN_INTERVAL = timedelta(hours=1)
# A cached cell older than this is not served at all: it describes a different day.
MAX_AGE = timedelta(hours=26)
SOURCE = "Bitget US-stock data (bitget-mcp-server)"


@dataclass(frozen=True)
class Entry:
    id: str
    label: str
    what: str
    params: Callable[[str], dict[str, Any]]
    normalise: Callable[[list[dict[str, Any]], str, datetime], dict[str, Any] | None]


@dataclass
class Cell:
    """What one entry last said about one ticker."""

    entry: str
    ticker: str
    attempted_at: datetime
    fetched_at: datetime | None = None  # the last time it delivered, empty answer or not
    data: dict[str, Any] | None = None  # None: delivered nothing usable (or never delivered)
    error: str | None = None  # why the latest attempt failed, if it did

    def to_dict(self) -> dict[str, Any]:
        return {"entry": self.entry, "ticker": self.ticker, "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
                "error": self.error, "data": self.data}


# ---------------------------------------------------------------------- the entries
#
# Field names below are the ones the service documents at agent.bitget.com/docs/equity (the
# catalogue's own reference). On 2026-10-05 the data backend answered every do_query with its
# own 503 for over an hour, so no live reply could be recorded for these five: every
# normaliser therefore treats each field as optional, returns None rather than guess, and the
# entry shows "no data yet" or "unavailable" on /sources until the service delivers.


def _num(v: Any) -> float | None:  # noqa: ANN401
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _day(v: Any) -> date | None:  # noqa: ANN401
    """A date out of the formats this service uses: 2026-10-21, 2026-10-21 16:00:00, 20261021, or epoch ms."""
    if v in (None, "", "example"):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(v).strip()
    for cut, fmt in ((10, "%Y-%m-%d"), (8, "%Y%m%d"), (10, "%Y/%m/%d")):
        try:
            return datetime.strptime(text[:cut], fmt).date()
        except ValueError:
            continue
    return None


def _ymd(d: date) -> str:
    return d.isoformat()


def _calendar_params(ticker: str) -> dict[str, Any]:
    today = utc_now().date()
    return {"symbol": ticker, "start_date": _ymd(today - timedelta(days=120)), "end_date": _ymd(today + timedelta(days=240))}


def _calendar(rows: list[dict[str, Any]], _ticker: str, now: datetime) -> dict[str, Any] | None:
    """The company's own next earnings date, as Bitget's calendar has it."""
    today = now.date()
    dated: list[tuple[date, bool, dict[str, Any]]] = []
    for r in rows:
        for key, confirmed in (("perf_report_dsclsr_date", True), ("perf_report_fore_dsclsr_date", False)):
            if (d := _day(r.get(key))) is not None:
                dated.append((d, confirmed, r))
    if not dated:
        return None
    upcoming = sorted((x for x in dated if x[0] >= today), key=lambda x: x[0])
    if upcoming:
        d, confirmed, r = upcoming[0]
        out: dict[str, Any] = {"next_report": _ymd(d), "days_ahead": (d - today).days, "confirmed": confirmed}
    else:
        d, _c, r = max(dated, key=lambda x: x[0])
        out = {"last_report": _ymd(d), "days_ago": (today - d).days}
    timing = str(r.get("is_trading_time") or "").strip()
    if timing and timing != "example":
        out["timing"] = timing
    if (pe := _day(r.get("period_ending"))) is not None:
        out["period_ending"] = _ymd(pe)
    if isinstance(r.get("fiscal_year"), int):
        out["fiscal_year"] = r["fiscal_year"]
    return out


def _ratios(rows: list[dict[str, Any]], _ticker: str, _now: datetime) -> dict[str, Any] | None:
    """The newest valuation row: P/E, P/B, P/S, dividend yield, market cap."""
    if not rows:
        return None
    newest = max(rows, key=lambda r: str(_day(r.get("period_ending")) or ""))
    out = {k: _num(newest.get(src)) for k, src in (("pe", "pe"), ("pb", "pb"), ("ps", "ps"), ("div_yield_12m", "div_yield_12m"), ("market_cap_usd", "tmv_usd"))}
    out = {k: v for k, v in out.items() if v is not None}
    if not out:
        return None
    if (pe := _day(newest.get("period_ending"))) is not None:
        out["period_ending"] = _ymd(pe)
    return out


def _dividends(rows: list[dict[str, Any]], _ticker: str, now: datetime) -> dict[str, Any] | None:
    """The next ex-dividend date if one is announced, else the latest paid, and the last year's count."""
    today = now.date()
    cash = [(d, r) for r in rows if (d := _day(r.get("ex_dividend_date"))) is not None and _num(r.get("amount")) is not None]
    if not cash:
        return None
    upcoming = sorted((x for x in cash if x[0] >= today), key=lambda x: x[0])
    past = sorted((x for x in cash if x[0] < today), key=lambda x: x[0], reverse=True)
    out: dict[str, Any] = {"paid_last_12m": sum(1 for d, _ in past if (today - d).days <= 365)}
    if upcoming:
        d, r = upcoming[0]
        out |= {"next_ex_date": _ymd(d), "next_amount": _num(r.get("amount")), "days_ahead": (d - today).days}
    if past:
        d, r = past[0]
        out |= {"last_ex_date": _ymd(d), "last_amount": _num(r.get("amount"))}
    if cur := (upcoming or past)[0][1].get("currency"):
        out["currency"] = str(cur)[:5]
    return out


def _consensus(rows: list[dict[str, Any]], _ticker: str, _now: datetime) -> dict[str, Any] | None:
    """The analysts' price-target consensus (the rows that carry one; the rest are EPS forecasts)."""
    for r in rows:
        if _num(r.get("target_consensus")) is not None:
            out = {k: _num(r.get(k)) for k in ("target_consensus", "target_median", "target_high", "target_low")}
            return {k: v for k, v in out.items() if v is not None}
    return None


def _profile(rows: list[dict[str, Any]], _ticker: str, _now: datetime) -> dict[str, Any] | None:
    if not rows:
        return None
    r = rows[0]
    out: dict[str, Any] = {}
    for k, src in (("sector", "sector"), ("industry", "industry_category"), ("ceo", "ceo"), ("exchange", "stock_exchange")):
        if r.get(src) and str(r[src]) != "example":
            out[k] = str(r[src])[:60]
    if (n := _num(r.get("employees"))) is not None:
        out["employees"] = int(n)
    return out or None


def _symbol_only(ticker: str) -> dict[str, Any]:
    return {"symbol": ticker}


ENTRIES: dict[str, Entry] = {e.id: e for e in (
    Entry("equity_calendar", "earnings calendar", "The company's own next earnings date and whether it reports before or after the bell, cross-checked against Nasdaq's calendar", _calendar_params, _calendar),
    Entry("equity_fundamental_ratios", "valuation ratios", "P/E, P/B, P/S, trailing dividend yield and market cap from the latest reported period", lambda t: {"symbol": t, "limit": 4}, _ratios),
    Entry("equity_fundamental_dividends", "dividends", "The next ex-dividend date and amount, or the latest paid", lambda t: {"symbol": t, "start_time": int((utc_now() - timedelta(days=400)).timestamp() * 1000)}, _dividends),
    Entry("equity_estimates_consensus", "analyst consensus", "The analysts' consensus price target with its high and low", _symbol_only, _consensus),
    Entry("equity_profile", "company profile", "Sector, industry, exchange, CEO and headcount", _symbol_only, _profile),
)}

# The four entries street.py already reads. They are held in the street cache, not here;
# they are listed so /sources and the chat tool treat every Bitget entry the same way.
STREET_ENTRIES: dict[str, tuple[str, str]] = {
    "equity_price_quote": ("live quote", "The underlying stock's live price and previous close, which the basis and the token-vs-stock gap lean on"),
    "equity_estimates_price_target": ("analyst ratings and targets", "Each firm's latest rating and price target over 90 days"),
    "equity_ownership_insider_trading": ("insider trades", "Open-market insider buys and sells over 90 days"),
    "sentiment_market_fear_greed": ("market fear and greed", "The US-stock market sentiment index, now and a week and a month ago"),
}
# Everything the chat tool may ask for. Nothing outside it is ever sent to the service.
ALLOWED = (*STREET_ENTRIES, *ENTRIES)


def _usd(v: Any) -> str:  # noqa: ANN401
    x = _num(v)
    return "n/a" if x is None else f"{x:,.2f}"


def describe(entry_id: str, d: dict[str, Any]) -> str:
    """A cached entry as one plain sentence, for the fact sheet and the chat tool. Every number
    in it is a number in ``d``, formatted and nothing else, so a citation to it can be checked."""
    if entry_id == "equity_calendar":
        if "next_report" in d:
            when = f"{d['days_ahead']} days" if d["days_ahead"] else "today"
            return (f"Bitget's calendar has the next earnings report on {d['next_report']} (in {when})"
                    + (f", {d['timing']}" if d.get("timing") else "") + (" (confirmed)" if d.get("confirmed") else " (expected)") + ".")
        return f"Bitget's calendar has no upcoming report; the latest was {d.get('last_report')} ({d.get('days_ago')} days ago)."
    if entry_id == "equity_fundamental_ratios":
        bits = [f"{lab} {_usd(d[k])}" for k, lab in (("pe", "P/E"), ("pb", "P/B"), ("ps", "P/S")) if k in d]
        if "div_yield_12m" in d:
            bits.append(f"dividend yield {_usd(d['div_yield_12m'])}")
        if "market_cap_usd" in d:
            bits.append(f"market cap {_usd(d['market_cap_usd'])} USD")
        return "Valuation" + (f" as of {d['period_ending']}" if d.get("period_ending") else "") + ": " + ", ".join(bits) + "."
    if entry_id == "equity_fundamental_dividends":
        out = []
        if "next_ex_date" in d:
            out.append(f"next ex-dividend {d['next_ex_date']} (in {d['days_ahead']} days), {_usd(d.get('next_amount'))} per share")
        if "last_ex_date" in d:
            out.append(f"latest paid ex-dividend {d['last_ex_date']}, {_usd(d.get('last_amount'))} per share")
        out.append(f"{d.get('paid_last_12m', 0)} paid in the last 12 months")
        return "Dividends: " + "; ".join(out) + "."
    if entry_id == "equity_estimates_consensus":
        bits = [f"{lab} {_usd(d[k])}" for k, lab in (("target_consensus", "consensus"), ("target_median", "median"), ("target_high", "high"), ("target_low", "low")) if k in d]
        return "Analyst price target: " + ", ".join(bits) + "."
    if entry_id == "equity_profile":
        bits = [f"{k} {d[k]}" for k in ("sector", "industry", "exchange", "ceo") if d.get(k)]
        if d.get("employees"):
            bits.append(f"{d['employees']:,} employees")
        return "Company: " + ", ".join(bits) + "."
    return ""


def street_entry_data(entry_id: str, v: Any) -> dict[str, Any] | None:  # noqa: ANN401
    """The slice of a ``StreetView`` that one of the four street entries supplied, or None if it supplied nothing."""
    if v is None or getattr(v, "empty", True):
        return None
    if entry_id == "equity_price_quote" and v.last_price is not None:
        return {"last_price": v.last_price, "prev_close": v.prev_close}
    if entry_id == "equity_estimates_price_target" and v.n_ratings:
        return {"firms": v.n_firms, "buy": v.bullish, "hold": v.neutral, "sell": v.bearish, "median_target": v.median_target,
                "upgrades_30d": v.upgrades_recent, "downgrades_30d": v.downgrades_recent}
    if entry_id == "equity_ownership_insider_trading" and (v.insider_buys or v.insider_sells):
        return {"purchases": v.insider_buys, "sales": v.insider_sells, "bought_usd": round(v.insider_bought_value), "sold_usd": round(v.insider_sold_value)}
    if entry_id == "sentiment_market_fear_greed" and v.mood_score is not None:
        return {"score": v.mood_score, "rating": v.mood_rating, "week_ago": v.mood_week_ago, "month_ago": v.mood_month_ago}
    return None


def describe_street(entry_id: str, d: dict[str, Any]) -> str:
    if entry_id == "equity_price_quote":
        return f"Bitget's quote for the stock: last {_usd(d['last_price'])}, previous close {_usd(d.get('prev_close'))}."
    if entry_id == "equity_estimates_price_target":
        return (f"Analysts, last 90 days: {d['buy']} buy, {d['hold']} hold, {d['sell']} sell from {d['firms']} firms; median target {_usd(d.get('median_target'))}; "
                f"{d['upgrades_30d']} upgrades and {d['downgrades_30d']} downgrades in the last 30 days.")
    if entry_id == "equity_ownership_insider_trading":
        return f"Insiders, last 90 days: {d['sales']} sales ({d['sold_usd']:,} USD) and {d['purchases']} purchases ({d['bought_usd']:,} USD)."
    if entry_id == "sentiment_market_fear_greed":
        return f"Market fear and greed {d['score']:.0f} ({d.get('rating')}); a week ago {_usd(d.get('week_ago'))}, a month ago {_usd(d.get('month_ago'))}."
    return ""


def earnings_check(cal: dict[str, Any] | None, nasdaq_dates: list[date], now: datetime) -> dict[str, Any] | None:
    """Bitget's next report date against Nasdaq's: two sources, one fact.

    A disagreement is the useful result: an earnings date is the single event the desk sizes
    around, and two feeds that differ by a day mean one of them is a placeholder estimate."""
    today = now.date()
    ours = min((d for d in nasdaq_dates if d >= today), default=None)
    theirs = _day(cal.get("next_report")) if cal else None
    if ours is None and theirs is None:
        return None
    if ours and theirs:
        gap = (theirs - ours).days
        return {"status": "agree" if gap == 0 else "differ", "bitget": _ymd(theirs), "nasdaq": _ymd(ours), "gap_days": gap}
    return {"status": "bitget_only" if theirs else "nasdaq_only", "bitget": _ymd(theirs) if theirs else None, "nasdaq": _ymd(ours) if ours else None, "gap_days": None}


@dataclass
class BitgetData:
    """The cache and the polite refresher for the extra catalogue entries."""

    client: Any
    entries: dict[str, Entry] = field(default_factory=lambda: dict(ENTRIES))
    min_interval: timedelta = MIN_INTERVAL
    _cells: dict[tuple[str, str], Cell] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ------------------------------------------------------------------ reading (never calls out)

    def get(self, ticker: str, entry_id: str, *, now: datetime | None = None) -> Cell | None:
        now = now or utc_now()
        with self._lock:
            cell = self._cells.get((ticker.upper(), entry_id))
        if cell is None or cell.fetched_at is None or now - cell.fetched_at > MAX_AGE:
            return None
        return cell

    def view(self, ticker: str, *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
        """Every entry that has something for the ticker, keyed by entry id, for a report."""
        out: dict[str, dict[str, Any]] = {}
        for eid in self.entries:
            cell = self.get(ticker, eid, now=now)
            if cell and cell.data is not None:
                out[eid] = {"fetched_at": cell.fetched_at.isoformat() if cell.fetched_at else None, "source": "Bitget", **cell.data}
        return out

    def cells(self) -> list[Cell]:
        with self._lock:
            return list(self._cells.values())

    # ------------------------------------------------------------------ refreshing (the only place that calls out)

    def due(self, ticker: str, entry_id: str, now: datetime) -> bool:
        with self._lock:
            cell = self._cells.get((ticker.upper(), entry_id))
        return cell is None or now - cell.attempted_at >= self.min_interval

    def refresh(self, ticker: str, entry_id: str, *, now: datetime | None = None) -> bool:
        """One call, if one is allowed this hour. True if a call was made."""
        now = now or utc_now()
        ticker = ticker.upper()
        entry = self.entries[entry_id]
        with self._lock:
            old = self._cells.get((ticker, entry_id))
            if old is not None and now - old.attempted_at < self.min_interval:
                return False
            # Claim the slot before the call so a second thread cannot also spend it.
            cell = Cell(entry=entry_id, ticker=ticker, attempted_at=now, fetched_at=old.fetched_at if old else None,
                        data=old.data if old else None, error=old.error if old else None)
            self._cells[(ticker, entry_id)] = cell
        try:
            rows = self.client.query(entry_id, **entry.params(ticker))
            status = getattr(self.client, "status", None)
            health = status() if callable(status) else None
            if not rows and health is not None and health.get("ok") is not True:
                cell.error = "service not answering"  # an outage, not "no data": keep the last good cell
                return True
            data = entry.normalise(rows, ticker, now) if rows else None
        except Exception as exc:  # noqa: BLE001 - an optional feed must never fail anything
            log.exception("bitget data %s for %s failed", entry_id, ticker)
            cell.error = type(exc).__name__
            return True
        cell.fetched_at, cell.data, cell.error = now, data, None
        return True

    def refresh_ticker(self, ticker: str, *, now: datetime | None = None) -> int:
        return sum(self.refresh(ticker, eid, now=now) for eid in self.entries)

    # ------------------------------------------------------------------ for /sources

    def source_rows(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """One row per entry: tokens it has delivered for, the newest delivery, and its state."""
        now = now or utc_now()
        rows = []
        for eid, e in self.entries.items():
            mine = [c for c in self.cells() if c.entry == eid]
            held = [c for c in mine if c.fetched_at and c.data is not None]
            newest = max((c.fetched_at for c in held if c.fetched_at), default=None)
            failing = [c for c in mine if c.error]
            if not mine:
                status, label = "no data yet", "not fetched yet"
            elif held and not failing:
                status, label = "ok", f"{len(held)} tokens with data"
            elif held:
                status, label = "degraded", f"{len(held)} tokens with data; {len(failing)} not answering"
            elif failing:
                status, label = "unavailable", f"not answering for {len(failing)} of {len(mine)} tokens"
            else:
                status, label = "ok", "answers, with nothing for these tokens"
            rows.append({
                "key": f"bitget_{eid}", "label": f"Bitget: {e.label}", "what": e.what,
                "cadence": "at most once an hour per token, in memory only",
                "last_update": newest.isoformat() if newest else None, "rows": len(held),
                "latest": newest.isoformat() if newest else None, "latest_label": label,
                "url": "https://agent.bitget.com/mcp", "status": status,
            })
        return rows


def report_block(bd: BitgetData | None, ticker: str, nasdaq_dates: list[date], now: datetime | None = None) -> dict[str, Any] | None:
    """What goes on a report: the cached entries for the ticker, the sentence for each, and the
    earnings-date cross-check. Reads the cache only; None when there is nothing to show."""
    if bd is None:
        return None
    now = now or utc_now()
    entries = bd.view(ticker, now=now)
    check = earnings_check(entries.get("equity_calendar"), nasdaq_dates, now)
    if not entries and not (check and check["status"] != "nasdaq_only"):
        return None
    for eid, d in entries.items():
        d["text"] = describe(eid, d)
    return {"source": "Bitget", "entries": entries, "earnings_check": check, "fetched_at": max((d["fetched_at"] for d in entries.values() if d.get("fetched_at")), default=None)}


def street_source_rows(cached: list[tuple[datetime, Any]], status: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    """One /sources row for each of the four entries the street view is built from."""
    from nightwatch.features.street import outage_clause

    down = bool(status) and status.get("ok") is False
    rows = []
    for eid, (label, what) in STREET_ENTRIES.items():
        held = [(ts, street_entry_data(eid, v)) for ts, v in cached]
        held = [(ts, d) for ts, d in held if d is not None]
        newest = max((ts for ts, _ in held), default=None)
        if down:
            state, text = "unavailable", f"unavailable{outage_clause(status)}" + (f"; {len(held)} tokens serve older data" if held else "")
        elif held:
            state, text = "ok", f"{len(held)} tokens with data"
        else:
            state, text = "no data yet", "not delivered yet"
        rows.append({
            "key": f"bitget_{eid}", "label": f"Bitget: {label}", "what": what, "cadence": "hourly per token, in memory only",
            "last_update": newest.isoformat() if newest else None, "rows": len(held), "latest": newest.isoformat() if newest else None,
            "latest_label": text, "url": "https://agent.bitget.com/mcp", "status": state,
        })
    return rows
