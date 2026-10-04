"""The corporate-event section of a report: what the stored calendar knows about a hold.

Ex-dividend dates, splits and exchange suspension notices that fall inside the hold, the
next one after it, and any recent Bitget notice that names the token. Read from the
stored ``corporate_events`` table only (see ``nightwatch.data.corporate`` for where each
row comes from), so an analysis never waits on a network call.

Point in time: the store hands back only events that were public by the report's
``as_of`` - by the announcement date where the source gives one, by the desk's first
sighting where it does not. A replay of a past night therefore cannot see a dividend
declared afterwards.

What this section does **not** say is how Bitget treats an rToken holder at the event.
That is not documented anywhere this desk could read, so the text says it is not verified
instead of describing a mechanism.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from nightwatch.data.models import CorporateEvent
from nightwatch.data.store import Store
from nightwatch.time_utils import ET, ensure_utc

NOTICE_DAYS = 10

SOURCE_LABEL = {
    "nasdaq_dividends": "Nasdaq dividend history",
    "nasdaq_splits": "Nasdaq split calendar",
    "yahoo_chart": "Yahoo Finance",
    "bitget_announcement": "Bitget announcement",
}
# Prefer the source that carries the declaration date.
_PREFERENCE = {"nasdaq_dividends": 0, "nasdaq_splits": 0, "bitget_announcement": 1, "yahoo_chart": 2}

HANDLING_NOT_VERIFIED = (
    "How Bitget adjusts an rToken holder for this is not verified here: it publishes cash-dividend settlement notices "
    "for its stock perpetuals, but nothing this desk could read says what the spot token receives. Check Bitget's own notice before holding through it."
)


def _open_of(ev: CorporateEvent) -> datetime:
    """The regular open on the event's ET date: when a dividend or split first shows in the price."""
    d = ev.event_date.astimezone(ET).date()
    return datetime.combine(d, time(9, 30), tzinfo=ET)


def _dedupe(events: list[CorporateEvent]) -> list[CorporateEvent]:
    best: dict[tuple[str, Any], CorporateEvent] = {}
    for e in sorted(events, key=lambda e: _PREFERENCE.get(e.source, 9)):
        best.setdefault((e.kind, e.event_date, e.detail if e.kind in ("notice", "suspension") else None), e)
    return sorted(best.values(), key=lambda e: e.event_date)


def _describe(ev: CorporateEvent, price: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": ev.kind,
        "date": ev.event_date.astimezone(ET).date().isoformat(),
        "amount": ev.amount,
        "currency": ev.currency,
        "ratio": ev.ratio,
        "announced": ev.announced_at.astimezone(ET).date().isoformat() if ev.announced_at else None,
        "source": ev.source,
        "source_label": SOURCE_LABEL.get(ev.source, ev.source),
        "detail": ev.detail,
        "url": ev.url,
    }
    if ev.kind == "dividend" and ev.amount and price:
        out["amount_pct_of_price"] = ev.amount / price * 100.0
    return out


def build(store: Store, ticker: str, *, as_of: datetime, horizon_h: float, price: float | None = None) -> dict[str, Any]:
    """The section as a plain dict (it travels in the report JSON)."""
    at = ensure_utc(as_of)
    end = at + timedelta(hours=horizon_h)
    checked = store.last_sync("corporate_events")
    events = _dedupe(store.get_corporate_events(ticker, as_of=at))
    dated = [e for e in events if e.kind in ("dividend", "split")]
    inside = [e for e in dated if at < _open_of(e) <= end]
    after = next((e for e in dated if _open_of(e) > end), None)
    last_split = next((e for e in reversed(events) if e.kind == "split" and _open_of(e) <= at), None)
    notices = [e for e in events if e.kind in ("notice", "suspension") and e.event_date >= at - timedelta(days=NOTICE_DAYS)]
    sources = sorted({SOURCE_LABEL.get(e.source, e.source) for e in events})
    return {
        "ticker": ticker,
        "as_of": at.isoformat(),
        "window_end": end.isoformat(),
        "checked_at": checked.isoformat() if checked else None,
        "covered": checked is not None,
        "in_hold": [_describe(e, price) for e in inside],
        "next_after": _describe(after, price) if after else None,
        "last_split": _describe(last_split, price) if last_split else None,
        "notices": [_describe(e, price) for e in notices][-4:],
        "handling": HANDLING_NOT_VERIFIED if inside else None,
        "sources": sources,
    }


def is_empty(section: dict[str, Any] | None) -> bool:
    """Nothing to show: no event in the hold, none ahead, and no notice."""
    return not section or not (section.get("in_hold") or section.get("next_after") or section.get("notices"))


def plain(ev: dict[str, Any]) -> str:
    """One event in a sentence, with its source."""
    when = ev["date"]
    src = f"({ev['source_label']}{', declared ' + ev['announced'] if ev.get('announced') else ''})"
    if ev["kind"] == "dividend":
        amt = f" of {ev['amount']:g} {ev.get('currency') or 'USD'} a share" if ev.get("amount") else ""
        pct = f", about {ev['amount_pct_of_price']:.2f}% of the price" if ev.get("amount_pct_of_price") else ""
        return f"ex-dividend{amt} on {when}{pct} {src}"
    if ev["kind"] == "split":
        return f"{ev['ratio'] or 'a'} split effective {when} {src}"
    return f"{ev.get('detail') or ev['kind']} ({when}; {ev['source_label']})"
