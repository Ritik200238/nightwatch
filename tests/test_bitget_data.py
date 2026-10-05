"""The rest of Bitget's catalogue: entry normalisers, the hourly call limit, the report block,
/sources rows, and the stress-test agent's ``bitget_data`` tool with its citation guard.

Honesty about the fixtures. The four street entries are tested against the recorded real TSLA
responses (tests/data/bitget_mcp_tsla_2026-09-24.json). The five new entries (calendar, ratios,
dividends, consensus, profile) could not be recorded: on 2026-10-05 the service's data backend
answered every call with its own 503 for over an hour. Their rows below are therefore built from
the field names the catalogue documents (agent.bitget.com/docs/equity), not copied from a live
reply, and the tests say what the normalisers do with them; they are not evidence about the live
shapes. All HTTP is a fake client.
"""

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from nightwatch.api import agent, analyst
from nightwatch.api.sources import street_row  # noqa: F401 - imported to prove the old row still exists
from nightwatch.features import bitget_data as bd
from nightwatch.features import street
from tests.test_agent import DONE, FakeState, Script, _call
from tests.test_analyst import REPORT
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture
from tests.test_street import FIXTURE, NOW

TODAY = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def utc_now_real():  # noqa: ANN201
    from nightwatch.time_utils import utc_now

    return utc_now()

CALENDAR = [
    {"symbol": "TSLA", "period_ending": "2026-09-30", "fiscal_year": 2026, "perf_report_fore_dsclsr_date": "2026-10-21", "perf_report_dsclsr_date": None, "is_trading_time": "盘后"},
    {"symbol": "TSLA", "period_ending": "2026-06-30", "fiscal_year": 2026, "perf_report_dsclsr_date": "2026-07-22"},
]
RATIOS = [
    {"symbol": "TSLA", "period_ending": "2026-06-30", "pe": 180.5, "pb": 14.2, "ps": 11.0, "div_yield_12m": 0.0, "tmv_usd": 1.1e12},
    {"symbol": "TSLA", "period_ending": "2026-03-31", "pe": 150.0, "pb": 12.0, "ps": 9.0, "tmv_usd": 9e11},
]
DIVIDENDS = [
    {"symbol": "AAPL", "ex_dividend_date": "2026-11-10", "amount": 0.27, "currency": "USD"},
    {"symbol": "AAPL", "ex_dividend_date": "2026-08-11", "amount": 0.26, "currency": "USD"},
    {"symbol": "AAPL", "ex_dividend_date": "2026-05-12", "amount": 0.26, "currency": "USD"},
    {"symbol": "AAPL", "ex_dividend_date": "2024-01-01", "amount": 0.2, "currency": "USD"},
]
CONSENSUS = [
    {"symbol": "TSLA", "fore_indicator_name": "eps", "fore_mean": 2.1},
    {"symbol": "TSLA", "target_consensus": 245.5, "target_median": 248.0, "target_high": 280.0, "target_low": 195.0},
]
PROFILE = [{"symbol": "TSLA", "sector": "Consumer Cyclical", "industry_category": "Auto Manufacturers", "ceo": "example", "stock_exchange": "NASDAQ", "employees": 140000}]
DATA = {"equity_calendar": CALENDAR, "equity_fundamental_ratios": RATIOS, "equity_fundamental_dividends": DIVIDENDS,
        "equity_estimates_consensus": CONSENSUS, "equity_profile": PROFILE}


class Client:
    """A catalogue client that counts calls and can be told to fail like the real one."""

    def __init__(self, data=None, down=False):  # noqa: ANN001
        self.data, self.down, self.calls = DATA if data is None else data, down, []

    def query(self, entry_id, **params):  # noqa: ANN001, ANN003, ANN201
        self.calls.append((entry_id, params))
        return [] if self.down else list(self.data.get(entry_id, []))

    def status(self):  # noqa: ANN201
        return {"ok": False if self.down else True, "down_since": None, "last_ok": None, "http_status": 503 if self.down else None, "error": None}


# ------------------------------------------------------------------ normalisers


def test_calendar_gives_the_next_report_date_and_the_bell():
    d = bd._calendar(CALENDAR, "TSLA", TODAY)
    assert d["next_report"] == "2026-10-21" and d["days_ahead"] == 16 and d["confirmed"] is False and d["timing"] == "盘后"


def test_calendar_with_only_past_reports_says_so():
    d = bd._calendar(CALENDAR[1:], "TSLA", TODAY)
    assert d["last_report"] == "2026-07-22" and d["days_ago"] == 75 and "next_report" not in d


def test_a_calendar_with_no_dates_and_placeholders_is_nothing():
    assert bd._calendar([{"symbol": "TSLA", "perf_report_fore_dsclsr_date": "example"}], "TSLA", TODAY) is None
    assert bd._calendar([], "TSLA", TODAY) is None


def test_ratios_use_the_newest_period_and_skip_missing_fields():
    d = bd._ratios(RATIOS, "TSLA", TODAY)
    assert d["pe"] == 180.5 and d["period_ending"] == "2026-06-30" and d["market_cap_usd"] == 1.1e12
    assert bd._ratios([{"period_ending": "2026-06-30"}], "TSLA", TODAY) is None


def test_dividends_find_the_next_ex_date_and_count_a_year():
    d = bd._dividends(DIVIDENDS, "AAPL", TODAY)
    assert d["next_ex_date"] == "2026-11-10" and d["days_ahead"] == 36 and d["last_ex_date"] == "2026-08-11" and d["paid_last_12m"] == 2


def test_consensus_skips_the_forecast_rows_that_carry_no_target():
    assert bd._consensus(CONSENSUS, "TSLA", TODAY) == {"target_consensus": 245.5, "target_median": 248.0, "target_high": 280.0, "target_low": 195.0}
    assert bd._consensus([{"fore_mean": 1.0}], "TSLA", TODAY) is None


def test_profile_drops_placeholder_text():
    assert bd._profile(PROFILE, "TSLA", TODAY) == {"sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "exchange": "NASDAQ", "employees": 140000}


def test_dates_come_out_of_the_formats_the_service_uses():
    want = datetime(2026, 10, 21).date()
    assert bd._day("2026-10-21") == bd._day("2026-10-21 16:00:00") == bd._day("20261021") == bd._day(1792584000000) == want
    assert bd._day("example") is None and bd._day(None) is None and bd._day("soon") is None


# ------------------------------------------------------------------ the hourly limit


def test_one_call_per_ticker_per_entry_per_hour():
    c = Client()
    b = bd.BitgetData(c)
    assert b.refresh_ticker("TSLA", now=TODAY) == 5 and len(c.calls) == 5
    assert b.refresh_ticker("TSLA", now=TODAY + timedelta(minutes=59)) == 0 and len(c.calls) == 5, "inside the hour: no call at all"
    assert b.refresh_ticker("TSLA", now=TODAY + timedelta(minutes=61)) == 5 and len(c.calls) == 10
    assert b.refresh_ticker("NVDA", now=TODAY) == 5, "another ticker has its own allowance"


def test_concurrent_refreshes_spend_the_slot_once():
    c = Client()
    b = bd.BitgetData(c)
    threads = [threading.Thread(target=b.refresh, args=("TSLA", "equity_calendar"), kwargs={"now": TODAY}) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(c.calls) == 1


def test_a_failing_service_keeps_the_last_good_cell_and_is_not_hammered():
    c = Client()
    b = bd.BitgetData(c)
    b.refresh("TSLA", "equity_fundamental_ratios", now=TODAY)
    c.down = True
    later = TODAY + timedelta(hours=2)
    b.refresh("TSLA", "equity_fundamental_ratios", now=later)
    cell = b.get("TSLA", "equity_fundamental_ratios", now=later)
    assert cell and cell.data["pe"] == 180.5, "the last good reading is still served"
    assert cell.error == "service not answering" and cell.fetched_at == TODAY
    n = len(c.calls)
    b.refresh("TSLA", "equity_fundamental_ratios", now=later + timedelta(minutes=5))
    assert len(c.calls) == n


def test_a_cell_older_than_its_day_is_not_served():
    b = bd.BitgetData(Client())
    b.refresh("TSLA", "equity_profile", now=TODAY)
    assert b.get("TSLA", "equity_profile", now=TODAY + timedelta(hours=27)) is None


def test_an_entry_that_answers_with_nothing_is_not_an_outage():
    b = bd.BitgetData(Client(data={}))
    b.refresh("TSLA", "equity_calendar", now=TODAY)
    cell = b.get("TSLA", "equity_calendar", now=TODAY)
    assert cell is not None and cell.data is None and cell.error is None


def test_an_exploding_normaliser_costs_nothing():
    broken = bd.Entry("equity_profile", "p", "w", lambda t: {"symbol": t}, lambda rows, t, n: 1 / 0)
    b = bd.BitgetData(Client(), entries={"equity_profile": broken})
    b.refresh("TSLA", "equity_profile", now=TODAY)
    assert b.get("TSLA", "equity_profile", now=TODAY) is None


# ------------------------------------------------------------------ cross-check and the report


def test_earnings_check_agree_differ_and_one_sided():
    cal = {"next_report": "2026-10-21"}
    d = lambda s: datetime.fromisoformat(s).date()  # noqa: E731
    assert bd.earnings_check(cal, [d("2026-10-21")], TODAY)["status"] == "agree"
    got = bd.earnings_check(cal, [d("2026-10-22")], TODAY)
    assert got["status"] == "differ" and got["gap_days"] == -1
    assert bd.earnings_check(cal, [], TODAY)["status"] == "bitget_only"
    assert bd.earnings_check(None, [d("2026-10-22")], TODAY)["status"] == "nasdaq_only"
    assert bd.earnings_check(None, [d("2026-01-01")], TODAY) is None, "a past Nasdaq date is not an upcoming one"


def test_the_report_block_reads_the_cache_and_never_calls():
    c = Client()
    b = bd.BitgetData(c)
    assert bd.report_block(b, "TSLA", [], TODAY) is None
    assert c.calls == []
    b.refresh_ticker("TSLA", now=TODAY)
    n = len(c.calls)
    blk = bd.report_block(b, "TSLA", [datetime(2026, 10, 22).date()], TODAY)
    assert len(c.calls) == n
    assert blk["source"] == "Bitget" and blk["earnings_check"]["status"] == "differ"
    assert "P/E 180.50" in blk["entries"]["equity_fundamental_ratios"]["text"]
    assert blk["entries"]["equity_calendar"]["source"] == "Bitget"
    assert bd.report_block(None, "TSLA", [], TODAY) is None


def _analyse(store_path, monkeypatch, *, now, warm=True):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import _ctx

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: now)
    ctx = _ctx(store_path)
    client = Client()
    ctx.bitget_data = bd.BitgetData(client)
    if warm:
        ctx.bitget_data.refresh_ticker("TSLA", now=now)
    n = len(client.calls)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    report = analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()
    return report, client, n


def test_an_analysis_of_today_carries_the_bitget_block_and_a_source_row_per_entry(seeded_store, monkeypatch):  # noqa: F811
    r, client, n = _analyse(seeded_store, monkeypatch, now=AS_OF)
    assert r["bitget"] and set(r["bitget"]["entries"]) == set(DATA)
    kinds = {s["kind"] for s in r["sources"]}
    assert {f"bitget_{e}" for e in DATA} <= kinds
    assert len(client.calls) == n, "the analysis itself read the cache and made no call"


def test_a_past_moment_never_gets_todays_bitget_data(seeded_store, monkeypatch):  # noqa: F811
    r, _c, _n = _analyse(seeded_store, monkeypatch, now=AS_OF + timedelta(days=30))
    assert r["bitget"] is None


def test_a_cold_cache_means_no_block_this_time_and_a_background_fill(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import _ctx

    gate = threading.Event()

    class Slow(Client):
        def query(self, entry_id, **params):  # noqa: ANN001, ANN003, ANN201
            gate.wait(5)
            return super().query(entry_id, **params)

    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    ctx = _ctx(seeded_store)
    client = Slow()
    ctx.bitget_data = bd.BitgetData(client)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    r = analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()
    assert r["bitget"] is None or not r["bitget"]["entries"], "returned at once with nothing cached"
    assert "TSLA" in ctx._bitget_pending
    gate.set()
    for _ in range(200):
        if len(client.calls) >= 5 and "TSLA" not in ctx._bitget_pending:
            break
        threading.Event().wait(0.05)
    assert len(client.calls) == 5, "one pass over the five entries, started in the background"
    assert bd.report_block(ctx.bitget_data, "TSLA", [], utc_now_real())["entries"]


def test_the_fact_sheet_carries_bitget_lines_under_their_own_tag():
    r = dict(REPORT)
    r["bitget"] = {"entries": {"equity_fundamental_ratios": {"text": bd.describe("equity_fundamental_ratios", bd._ratios(RATIOS, "TSLA", TODAY))}},
                   "earnings_check": {"status": "differ", "bitget": "2026-10-21", "nasdaq": "2026-10-22", "gap_days": -1}}
    sheet = analyst.fact_sheet(r)
    assert "[bitget] Valuation as of 2026-06-30: P/E 180.50" in sheet and "disagree on the next earnings date" in sheet
    clean, removed, _ = analyst.verify_tagged("It trades at a P/E of 180.50 [bitget].", sheet)
    assert removed == 0 and clean
    _c, removed, _ = analyst.verify_tagged("It trades at a P/E of 180.50 [street].", sheet)
    assert removed == 1, "the right number under the wrong section is still refused"


# ------------------------------------------------------------------ /sources


def test_every_entry_has_its_own_source_row_with_status():
    b = bd.BitgetData(Client())
    rows = {r["key"]: r for r in b.source_rows(TODAY)}
    assert set(rows) == {f"bitget_{e}" for e in DATA} and all(r["status"] == "no data yet" for r in rows.values())
    b.refresh("TSLA", "equity_calendar", now=TODAY)
    b.client.down = True
    b.refresh("NVDA", "equity_calendar", now=TODAY)
    b.refresh("TSLA", "equity_profile", now=TODAY)
    rows = {r["key"]: r for r in b.source_rows(TODAY)}
    assert rows["bitget_equity_calendar"]["status"] == "degraded" and rows["bitget_equity_calendar"]["last_update"] == TODAY.isoformat()
    assert rows["bitget_equity_profile"]["status"] == "unavailable" and rows["bitget_equity_profile"]["last_update"] is None


def test_the_four_street_entries_are_listed_separately_from_the_real_fixture():
    class Fake:
        def query(self, entry_id, **p):  # noqa: ANN001, ANN003, ANN201
            return list(FIXTURE.get(entry_id, []))

    view = street.build(Fake(), "TSLA", now=NOW)
    rows = {r["key"]: r for r in bd.street_source_rows([(NOW, view)], {"ok": True}, NOW)}
    assert set(rows) == {f"bitget_{e}" for e in bd.STREET_ENTRIES}
    assert all(r["status"] == "ok" and r["rows"] == 1 and r["last_update"] for r in rows.values())
    down = bd.street_source_rows([(NOW, view)], {"ok": False, "down_since": NOW.isoformat(), "http_status": 503}, NOW)
    assert all(r["status"] == "unavailable" and "503" in r["latest_label"] for r in down)
    empty = bd.street_source_rows([], None, NOW)
    assert all(r["status"] == "no data yet" for r in empty)


def test_street_entries_describe_themselves_from_the_real_fixture():
    class Fake:
        def query(self, entry_id, **p):  # noqa: ANN001, ANN003, ANN201
            return list(FIXTURE.get(entry_id, []))

    view = street.build(Fake(), "TSLA", now=NOW)
    for eid in bd.STREET_ENTRIES:
        data = bd.street_entry_data(eid, view)
        assert data, eid
        assert bd.describe_street(eid, data), eid


# ------------------------------------------------------------------ the agent tool


class Ctx:
    def __init__(self, b, street_view=None):  # noqa: ANN001
        self.bitget_data, self._view = b, street_view

    def tickers_with_data(self):  # noqa: ANN201
        return ("TSLA", "NVDA")

    def street_for(self, ticker, fetch=True):  # noqa: ANN001, ANN201
        return self._view


class State(FakeState):
    def __init__(self, ctx):  # noqa: ANN001
        self.ctx = ctx


def _warm(client=None):  # noqa: ANN001, ANN202
    b = bd.BitgetData(client or Client())
    b.refresh_ticker("TSLA")
    return b


def test_the_tool_only_serves_the_allow_list():
    st = State(Ctx(_warm()))
    for bad in ("crypto_futures_open_interest", "equity_fundamental_balance", "../etc", ""):
        with pytest.raises(ValueError, match="entry must be one of"):
            agent.tool_bitget_data(st, REPORT, {"entry": bad, "ticker": "TSLA"})
    assert set(bd.ALLOWED) == set(bd.STREET_ENTRIES) | set(bd.ENTRIES) and len(bd.ALLOWED) == 9


def test_the_tool_refuses_a_ticker_the_desk_does_not_cover():
    with pytest.raises(ValueError, match="not a ticker"):
        agent.tool_bitget_data(State(Ctx(_warm())), REPORT, {"entry": "equity_calendar", "ticker": "ZZZZ"})


def test_the_tool_answers_from_the_cache_without_a_call():
    c = Client()
    st = State(Ctx(_warm(c)))
    n = len(c.calls)
    out = agent.tool_bitget_data(st, REPORT, {"entry": "equity_estimates_consensus", "ticker": "tsla"})
    assert "consensus 245.50" in out and "high 280.00" in out and len(c.calls) == n


def test_a_cold_entry_is_fetched_once_with_a_timeout_and_then_limited():
    c = Client()
    b = bd.BitgetData(c)
    st = State(Ctx(b))
    out = agent.tool_bitget_data(st, REPORT, {"entry": "equity_profile", "ticker": "TSLA"})
    assert "Consumer Cyclical" in out and len(c.calls) == 1
    agent.tool_bitget_data(st, REPORT, {"entry": "equity_profile", "ticker": "TSLA"})
    assert len(c.calls) == 1, "the second ask is a cache hit"


def test_a_service_that_does_not_answer_is_an_error_the_model_can_read_not_a_hang(monkeypatch):
    gate = threading.Event()

    class Slow(Client):
        def query(self, entry_id, **params):  # noqa: ANN001, ANN003, ANN201
            gate.wait(5)
            return super().query(entry_id, **params)

    monkeypatch.setattr(agent, "BITGET_TIMEOUT_S", 0.2)
    st = State(Ctx(bd.BitgetData(Slow())))
    with pytest.raises(ValueError, match="no equity_calendar data"):
        agent.tool_bitget_data(st, REPORT, {"entry": "equity_calendar", "ticker": "TSLA"})
    gate.set()


def test_the_tool_serves_a_street_entry_from_the_street_cache():
    class Fake:
        def query(self, entry_id, **p):  # noqa: ANN001, ANN003, ANN201
            return list(FIXTURE.get(entry_id, []))

    view = street.build(Fake(), "TSLA", now=NOW)
    st = State(Ctx(_warm(), view))
    out = agent.tool_bitget_data(st, REPORT, {"entry": "sentiment_market_fear_greed"})
    assert out.startswith("Market fear and greed")
    st_none = State(Ctx(_warm(), None))
    with pytest.raises(ValueError, match="no sentiment_market_fear_greed data"):
        agent.tool_bitget_data(st_none, REPORT, {"entry": "sentiment_market_fear_greed"})


def test_results_are_trimmed():
    big = [{"symbol": "TSLA", "sector": "x" * 59, "industry_category": "y" * 59, "stock_exchange": "z" * 59, "ceo": "w" * 59, "employees": 1}]
    st = State(Ctx(_warm(Client(data={"equity_profile": big}))))
    assert len(agent.tool_bitget_data(st, REPORT, {"entry": "equity_profile", "ticker": "TSLA"})) <= agent.BITGET_RESULT_CHARS


def test_a_number_cited_from_the_tool_passes_only_under_the_bitget_tag():
    """Through the real loop: the model calls the tool, then cites its number."""
    st = State(Ctx(_warm()))
    final = {"final": {"summary": "Consensus target is 245.50 [bitget].",
                       "findings": ["Consensus target is 245.50 [street].", "Median target is 248.00 USDT.", "The high target is 280.00 [bitget]."],
                       "verdict_restated": ""}}
    prov = Script([_call("bitget_data", {"entry": "equity_estimates_consensus", "ticker": "TSLA"}), final])
    run = agent.Run()
    agent.run_agent(prov, st, REPORT, run)
    assert run.status == "done", run.error
    assert run.steps[0]["tool"] == "bitget_data" and "245.50" in run.steps[0]["result_summary"]
    assert "245.50" in prov.users[1], "the result was fed back to the model under its section"
    assert run.final["summary"] == "Consensus target is 245.50 [bitget]."
    assert run.final["findings"] == ["The high target is 280.00 [bitget]."], "wrong tag and no tag are both removed"
    assert run.removed == 2


def test_the_model_is_told_about_the_tool():
    assert "bitget_data" in agent.TOOLS_DOC and "equity_calendar" in agent.TOOLS_DOC and agent.SECTION["bitget_data"] == "bitget"
    assert json.dumps(DONE)
