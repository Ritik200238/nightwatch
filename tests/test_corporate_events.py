"""Dividends, splits and exchange notices: parsed from real response shapes, stored point
in time, and put in front of the trader only as plain, sourced facts.

The payloads are trimmed copies of what Nasdaq, Yahoo and Bitget returned on 2026-10-04,
so the parsing is tested against their actual field names. Nothing here touches the
network; the client tests run through a mock transport.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta

import httpx
import pytest

from nightwatch.api import followup, followup_zh
from nightwatch.data import corporate
from nightwatch.data.http import HttpClient
from nightwatch.data.models import CorporateEvent
from nightwatch.data.store import Store
from nightwatch.features import corporate as section
from nightwatch.time_utils import ET, UTC
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

NASDAQ_AAPL = {"data": {"dividends": {"asOf": None, "headers": {}, "rows": [
    {"exOrEffDate": "08/10/2026", "type": "Cash", "amount": "$0.27", "declarationDate": "07/30/2026", "recordDate": "08/10/2026", "paymentDate": "08/13/2026", "currency": "USD"},
    {"exOrEffDate": "11/10/2025", "type": "Cash", "amount": "$0.26", "declarationDate": "10/30/2025", "recordDate": "11/10/2025", "paymentDate": "11/13/2025", "currency": "USD"},
    {"exOrEffDate": "N/A", "type": "Cash", "amount": "$0.10", "declarationDate": "N/A", "recordDate": "N/A", "paymentDate": "N/A"},
]}}, "message": None}
NASDAQ_TSLA = {"data": {"dividends": {"asOf": None, "headers": None, "rows": None}}, "message": "Dividend History information is presently unavailable for this company."}
NASDAQ_SPLITS = {"data": {"rows": [
    {"symbol": "LU", "name": "Lufax", "ratio": "1 : 10", "executionDate": "10/23/2026"},
    {"symbol": "DXJ", "name": "WisdomTree", "ratio": "3 : 1", "executionDate": "10/09/2026"},
    {"symbol": "ZZZZ", "name": "Other", "ratio": "2:1", "executionDate": "10/09/2026"},
]}}
YAHOO_NVDA = {"chart": {"result": [{"events": {
    "dividends": {"1789047000": {"amount": 0.25, "date": 1789047000}},
    "splits": {"1718026200": {"date": 1718026200, "numerator": 10.0, "denominator": 1.0, "splitRatio": "10:1"}},
}}]}}
BITGET_ANN = [
    {"annId": "1", "annTitle": "[Important] Bitget Announcement on Cash Dividend Settlement for CMCSAUSDT Stock Perps", "annType": "latest_news", "cTime": "1791072005098", "annUrl": "https://www.bitget.com/a/1"},
    {"annId": "2", "annTitle": "Bitget announcement on resuming rMSTR - Morph withdrawals", "annType": "maintenance_system_updates", "cTime": "1791025105044", "annUrl": "https://www.bitget.com/a/2"},
    {"annId": "3", "annTitle": "Bitget announcement on suspending rTSLA trading", "annType": "latest_news", "cTime": "1791070000000", "annUrl": "https://www.bitget.com/a/3"},
    {"annId": "4", "annTitle": "Bitget announcement on suspending GMT - Solana network withdrawal service", "annType": "maintenance_system_updates", "cTime": "1791115860225"},
]


def ev(ticker="TSLA", kind="dividend", date=(2026, 10, 6), *, source="nasdaq_dividends", amount=0.25, ratio=None, announced=None, observed=NOW, detail=None) -> CorporateEvent:
    return CorporateEvent(ticker=ticker, kind=kind, event_date=datetime(*date, tzinfo=ET).astimezone(UTC), source=source, amount=amount, ratio=ratio,
                          currency="USD" if amount else None, announced_at=announced, detail=detail, observed_at=observed)


# ---------------------------------------------------------------------- parsing


def test_nasdaq_dividends_keep_the_declaration_date_and_skip_unusable_rows():
    got = corporate.parse_nasdaq_dividends("AAPL", NASDAQ_AAPL, NOW)
    assert [(e.event_date.astimezone(ET).date().isoformat(), e.amount) for e in got] == [("2026-08-10", 0.27), ("2025-11-10", 0.26)]
    assert got[0].announced_at.astimezone(ET).date().isoformat() == "2026-07-30"
    assert all(e.source == "nasdaq_dividends" and e.kind == "dividend" for e in got)


def test_a_company_that_pays_nothing_is_no_events_not_an_error():
    assert corporate.parse_nasdaq_dividends("TSLA", NASDAQ_TSLA, NOW) == []


def test_the_split_calendar_is_filtered_to_our_tickers_and_ratios_are_normalised():
    got = corporate.parse_nasdaq_splits(NASDAQ_SPLITS, {"LU", "DXJ"}, NOW)
    assert {(e.ticker, e.ratio) for e in got} == {("LU", "1:10"), ("DXJ", "3:1")}
    assert all(e.announced_at is None for e in got), "the calendar does not say when it was announced"


def test_yahoo_dividends_and_splits_land_on_the_eastern_date():
    got = corporate.parse_yahoo_events("NVDA", YAHOO_NVDA, NOW)
    by_kind = {e.kind: e for e in got}
    assert by_kind["split"].ratio == "10:1" and by_kind["split"].event_date.astimezone(ET).date().isoformat() == "2024-06-10"
    assert by_kind["dividend"].amount == 0.25


def test_announcements_are_matched_to_the_token_and_perp_symbols_only():
    got = corporate.parse_bitget_announcements(BITGET_ANN, {"CMCSA", "MSTR", "TSLA", "GMT"}, NOW)
    kinds = {(e.ticker, e.kind) for e in got}
    assert ("CMCSA", "notice") in kinds, "a perp dividend-settlement notice names CMCSAUSDT"
    assert ("MSTR", "notice") in kinds, "rMSTR withdrawals resuming is a notice, not a trading event"
    assert ("TSLA", "suspension") in kinds
    assert not any(e.ticker == "GMT" for e in got), "GMT is not an rToken here, and a withdrawal pause is not a trading suspension"
    assert all(e.announced_at is not None and e.source == "bitget_announcement" for e in got)


def test_a_withdrawal_suspension_is_not_called_a_trading_suspension():
    rows = [{"annId": "9", "annTitle": "Bitget announcement on suspending rMSTR - Morph withdrawals", "cTime": "1791025105044"}]
    assert [e.kind for e in corporate.parse_bitget_announcements(rows, {"MSTR"}, NOW)] == ["notice"]


# ------------------------------------------------------------------- fetch + sync


def _client() -> corporate.CorporateEventsClient:
    def nasdaq(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/calendar/splits":
            return httpx.Response(200, json=NASDAQ_SPLITS)
        if req.url.path == "/api/quote/aapl/dividends":
            return httpx.Response(200, json=NASDAQ_AAPL)
        if req.url.path == "/api/quote/tsla/dividends":
            return httpx.Response(200, json=NASDAQ_TSLA)
        return httpx.Response(500)

    def yahoo(req: httpx.Request) -> httpx.Response:
        if "AAPL" in req.url.path:
            return httpx.Response(503)  # one source failing for one ticker
        return httpx.Response(200, json=YAHOO_NVDA)

    def bitget(req: httpx.Request) -> httpx.Response:
        rows = BITGET_ANN if req.url.params.get("annType") == "latest_news" else []
        return httpx.Response(200, json={"code": "00000", "data": rows})

    def mk(base, handler):  # noqa: ANN001, ANN202
        from nightwatch.data.http import RetryPolicy

        return HttpClient(base, transport=httpx.MockTransport(handler), rate_per_sec=1000, burst=1000, retry=RetryPolicy(max_attempts=1))

    return corporate.CorporateEventsClient(nasdaq=mk("https://api.nasdaq.com", nasdaq), yahoo=mk("https://query1.finance.yahoo.com", yahoo), bitget=mk("https://api.bitget.com", bitget))


class Entry:
    def __init__(self, ticker):  # noqa: ANN001
        self.ticker = self.yahoo_ticker = ticker


def test_a_sync_stores_every_source_that_answers_and_survives_the_one_that_does_not(tmp_path):
    with Store(tmp_path / "c.sqlite") as s:
        n = corporate.sync_corporate_events(s, [Entry("AAPL"), Entry("TSLA"), Entry("NVDA")], _client())
        assert n > 0 and s.last_sync("corporate_events") is not None
        aapl = s.get_corporate_events("AAPL")
        assert {e.source for e in aapl} == {"nasdaq_dividends"}, "Yahoo answered 503 for AAPL, Nasdaq still landed"
        assert any(e.kind == "split" and e.source == "yahoo_chart" for e in s.get_corporate_events("NVDA"))
        assert any(e.kind == "suspension" for e in s.get_corporate_events("TSLA"))
        # A second sync changes nothing and keeps each row's first sighting.
        first = {(e.kind, e.event_date, e.source): e.observed_at for e in s.get_corporate_events("AAPL")}
        corporate.sync_corporate_events(s, [Entry("AAPL")], _client())
        assert {(e.kind, e.event_date, e.source): e.observed_at for e in s.get_corporate_events("AAPL")} == first


# ------------------------------------------------------------- point in time + section


def test_the_store_only_returns_what_was_public_by_as_of(tmp_path):
    with Store(tmp_path / "p.sqlite") as s:
        declared = datetime(2026, 9, 20, tzinfo=UTC)
        s.upsert_corporate_events([
            ev(announced=declared, observed=NOW),  # declared 20 Sep, first seen 4 Oct
            ev(date=(2026, 10, 9), source="yahoo_chart", observed=NOW),  # no announcement date, first seen 4 Oct
        ])
        before = datetime(2026, 9, 10, tzinfo=UTC)
        mid = datetime(2026, 9, 25, tzinfo=UTC)
        assert s.get_corporate_events("TSLA", as_of=before) == []
        assert len(s.get_corporate_events("TSLA", as_of=mid)) == 1, "the declaration date counts, not the sync date"
        assert len(s.get_corporate_events("TSLA", as_of=NOW)) == 2


_DB = itertools.count()


def _stored(tmp_path, events, *, synced=True):  # noqa: ANN001, ANN202
    s = Store(tmp_path / f"s{next(_DB)}.sqlite")
    s.upsert_corporate_events(events)
    if synced:
        s.log_sync("corporate_events", rows=len(events), started_at=NOW, finished_at=NOW)
    return s


def test_the_section_lists_what_falls_inside_the_hold_and_the_next_one_after(tmp_path):
    s = _stored(tmp_path, [
        ev(date=(2026, 10, 6), announced=datetime(2026, 9, 20, tzinfo=UTC)),
        ev(date=(2026, 12, 8), announced=datetime(2026, 9, 20, tzinfo=UTC)),
        ev(date=(2026, 6, 1), kind="split", amount=None, ratio="3:1", source="yahoo_chart"),
        ev(date=(2026, 10, 6), source="yahoo_chart"),  # the same dividend from a second source
    ])
    c = section.build(s, "TSLA", as_of=NOW, horizon_h=72.0, price=250.0)
    assert [(e["kind"], e["date"], e["amount"], e["source"]) for e in c["in_hold"]] == [("dividend", "2026-10-06", 0.25, "nasdaq_dividends")], "deduplicated, preferring the source with a declaration date"
    assert c["in_hold"][0]["amount_pct_of_price"] == pytest.approx(0.1)
    assert c["next_after"]["date"] == "2026-12-08"
    assert c["last_split"]["ratio"] == "3:1"
    assert c["covered"] and "not verified" in c["handling"]


def test_an_ex_dividend_date_already_open_is_not_inside_a_hold_that_starts_after_it(tmp_path):
    s = _stored(tmp_path, [ev(date=(2026, 10, 2), announced=datetime(2026, 9, 1, tzinfo=UTC))])
    c = section.build(s, "TSLA", as_of=NOW, horizon_h=72.0)
    assert c["in_hold"] == [] and c["next_after"] is None and c["handling"] is None


def test_an_unsynced_calendar_is_not_the_same_as_an_empty_one(tmp_path):
    c = section.build(_stored(tmp_path, [], synced=False), "TSLA", as_of=NOW, horizon_h=72.0)
    assert c["covered"] is False and c["checked_at"] is None
    assert section.is_empty(c)


def test_recent_notices_are_listed_and_old_ones_are_not(tmp_path):
    s = _stored(tmp_path, [
        ev(kind="suspension", amount=None, source="bitget_announcement", date=(2026, 10, 3), announced=datetime(2026, 10, 3, 12, tzinfo=UTC), detail="Bitget suspends rTSLA trading"),
        ev(kind="notice", amount=None, source="bitget_announcement", date=(2026, 8, 1), announced=datetime(2026, 8, 1, 12, tzinfo=UTC), detail="old notice"),
    ])
    c = section.build(s, "TSLA", as_of=NOW, horizon_h=72.0)
    assert [n["kind"] for n in c["notices"]] == ["suspension"]


# --------------------------------------------------------------------------- chat


def _report(tmp_path, events, synced=True):  # noqa: ANN001, ANN202
    s = _stored(tmp_path, events, synced=synced)
    return {"corporate_events": section.build(s, "TSLA", as_of=NOW, horizon_h=72.0, price=250.0)}


@pytest.mark.parametrize("q", ["any split or dividend coming?", "is there an ex-dividend date in this hold", "will it get suspended", "any corporate actions?"])
def test_corporate_questions_route_to_the_corporate_answer(q):
    kinds = [k for k, p, _ in followup.ROUTES if p.search(q)]
    assert kinds and kinds[0] == "corporate"


@pytest.mark.parametrize("q", ["split the order into slices", "can I split it across two entries", "why not bigger?"])
def test_ordinary_words_do_not_trigger_it(q):
    assert "corporate" not in [k for k, p, _ in followup.ROUTES if p.search(q)]


def test_chat_states_the_dividend_with_its_source_and_says_the_handling_is_not_verified(tmp_path):
    r = _report(tmp_path, [ev(date=(2026, 10, 6), announced=datetime(2026, 9, 20, tzinfo=UTC))])
    a = followup.answer(r, "any dividend coming?")
    assert a and a.kind == "corporate"
    assert "ex-dividend of 0.25 USD a share on 2026-10-06" in a.text and "Nasdaq dividend history" in a.text and "not verified" in a.text


def test_chat_with_nothing_known_says_so_plainly_and_does_not_guess(tmp_path):
    a = followup.answer(_report(tmp_path, []), "any split coming?")
    assert a and "No ex-dividend date or split falls inside this hold in the stored calendar" in a.text
    assert "not a guarantee" in a.text


def test_chat_with_an_unsynced_calendar_refuses_to_answer_from_nothing(tmp_path):
    a = followup.answer(_report(tmp_path, [], synced=False), "any dividend?")
    assert a and "not been synced" in a.text and "guess" in a.text


def test_chat_without_the_section_admits_the_gap():
    a = followup.answer({}, "any split coming?")
    assert a and "no dividend or split check" in a.text


def test_chinese_questions_get_chinese_answers_from_the_same_section(tmp_path):
    r = _report(tmp_path, [ev(date=(2026, 10, 6), announced=datetime(2026, 9, 20, tzinfo=UTC))])
    a = followup_zh.answer(r, "有分红吗")
    assert a and a.kind == "corporate" and "2026-10-06 除息每股 0.25 USD" in a.text and "无法核实" in a.text
    empty = followup_zh.answer(_report(tmp_path, []), "会拆股吗")
    assert empty and "没有除息日或拆股" in empty.text
    assert "还没有同步" in followup_zh.answer(_report(tmp_path, [], synced=False), "有分红吗").text


# ----------------------------------------------------------------- in the report


def _analyse(store_path):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF, _ctx

    ctx = _ctx(store_path)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="holding for the dividend", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_a_report_carries_the_section_and_says_it_in_assumptions_and_premise(seeded_store):  # noqa: F811
    from tests.test_pipeline import AS_OF

    declared = AS_OF - timedelta(days=20)
    with Store(seeded_store) as s:
        s.upsert_corporate_events([ev(date=(2026, 9, 14), announced=declared, observed=declared)])
        s.log_sync("corporate_events", rows=1, started_at=AS_OF, finished_at=AS_OF)
    r = _analyse(seeded_store)
    ce = r["corporate_events"]
    assert ce["in_hold"] and ce["in_hold"][0]["date"] == "2026-09-14" and ce["in_hold"][0]["source"] == "nasdaq_dividends"
    assert any(a["topic"] == "corporate events" and a["kind"] == "caveat" and "not verified" in a["text"] for a in r["assumptions"])
    assert any("ex-dividend of 0.25" in p for p in r["premise"])
    assert any(src["kind"] == "corporate_events" and src["rows_used"] == 1 for src in r["sources"])
    json.dumps(r)


def test_a_replay_before_the_declaration_does_not_see_it(seeded_store):  # noqa: F811
    from tests.test_pipeline import AS_OF

    with Store(seeded_store) as s:
        s.upsert_corporate_events([ev(ticker="TSLA", date=(2026, 9, 14), source="yahoo_chart", observed=AS_OF + timedelta(days=30))])
    r = _analyse(seeded_store)
    assert all(e["source"] != "yahoo_chart" for e in r["corporate_events"]["in_hold"])


def test_the_sync_builds_its_own_client_when_none_is_given(monkeypatch, tmp_path):
    """The recorder calls sync_corporate_events(store, entries) with no client; it must not
    silently fail every fetch (the first live sync stored 0 rows in 3 ms that way)."""
    from types import SimpleNamespace

    from nightwatch.data import corporate
    from nightwatch.data.store import Store

    made = []

    class Fake:
        def __init__(self, *a, **k):
            made.append(self)

        def splits_calendar(self, wanted):
            return []

        def announcements(self, wanted):
            return []

        def dividends(self, ticker):
            return []

        def yahoo_events(self, yahoo_ticker, ticker):
            return []

    monkeypatch.setattr(corporate, "CorporateEventsClient", Fake)
    corporate.sync_corporate_events(Store(tmp_path / "nw.sqlite"), [SimpleNamespace(ticker="AAPL", yahoo_ticker="AAPL")])
    assert len(made) == 1
