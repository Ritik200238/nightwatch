"""Bitget Wallet's tokenized-stock listing (bitget-wallet-skill): the recorded reply, the
request hash, fail-soft behaviour, the cautions it raises and the cache."""

import hashlib
import json
import threading
from pathlib import Path

import httpx

from nightwatch.data.bitget_rwa import BitgetRwaClient, signed_headers, token_symbol
from nightwatch.features import rwa_status
from tests.test_pipeline import _ctx, seeded_store  # noqa: F401 - fixture

# A recorded reply (TSLAon, 2026-10-05), trimmed of the description and icons only.
DOC = json.loads((Path(__file__).parent / "data" / "bgw_rwa_stockinfo_TSLAon_2026-10-05.json").read_text(encoding="utf-8"))


def client(handler):  # noqa: ANN001, ANN201
    return BitgetRwaClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_request_is_signed_the_way_the_skill_documents():
    path = "/market/v2/rwa/StockInfo?ticker=TSLAon"
    h = signed_headers(path, ts_ms=1791190000000)
    assert h["X-SIGN"] == "0x" + hashlib.sha256(("GET" + path + "1791190000000").encode()).hexdigest()
    assert h["channel"] == "toc_agent" and h["X-TIMESTAMP"] == "1791190000000"
    assert token_symbol("tsla") == "TSLAon"


def test_the_recorded_reply_is_read_and_the_ticker_is_checked():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["sign"] = str(req.url), req.headers.get("x-sign")
        return httpx.Response(200, json=DOC)

    info = client(handler).stock_info("TSLA")
    assert info["status"] == "online" and info["market_status_code"] == "regular" and seen["url"].endswith("StockInfo?ticker=TSLAon")
    assert seen["sign"].startswith("0x")
    assert client(lambda r: httpx.Response(200, json=DOC)).stock_info("NVDA") is None, "a reply about another token is not this token's"


def test_failures_and_junk_are_no_reading_never_an_exception():
    assert client(lambda r: httpx.Response(500)).stock_info("TSLA") is None
    assert client(lambda r: httpx.Response(200, text="<html>")).stock_info("TSLA") is None
    assert client(lambda r: httpx.Response(200, json={"status": 1, "data": DOC["data"]})).stock_info("TSLA") is None
    assert client(lambda r: httpx.Response(200, json={"status": 0, "data": None})).stock_info("TSLA") is None

    def boom(req):  # noqa: ANN001, ANN202
        raise httpx.ConnectTimeout("slow")

    assert client(boom).stock_info("TSLA") is None


def test_a_normal_listing_raises_nothing():
    b = rwa_status.build(DOC["data"], 20_000.0, True)
    assert b["flags"] == [] and b["status"] == "online" and b["tx_max_usd"] == 3_000_000 and b["tx_min_usd"] == 20


def test_a_pause_an_alert_an_offline_listing_and_an_out_of_range_size_each_raise_a_flag():
    base = dict(DOC["data"])
    assert any("pause (halted)" in f for f in rwa_status.build({**base, "special_pause_reason_code": "halted"}, 1000.0, True)["flags"])
    assert any("alert: Corporate action" in f for f in rwa_status.build({**base, "market_alert_content": "Corporate action"}, 1000.0, True)["flags"])
    assert any("lists TSLAon as offline" in f for f in rwa_status.build({**base, "status": "offline"}, 1000.0, True)["flags"])
    assert any("above Bitget Wallet's per-order maximum" in f for f in rwa_status.build(base, 5_000_000.0, True)["flags"])
    assert any("below Bitget Wallet's per-order minimum" in f for f in rwa_status.build(base, 5.0, True)["flags"])
    assert rwa_status.build(None, 1000.0, True) is None


def wait_for(cond, n=100):  # noqa: ANN001, ANN201
    import time

    for _ in range(n):
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeRwa:
    def __init__(self, info):  # noqa: ANN001
        self.info, self.calls, self.gate = info, 0, threading.Event()

    def stock_info(self, ticker):  # noqa: ANN001, ANN201
        self.calls += 1
        return self.info


def test_a_cold_cache_never_waits_and_one_refresh_serves_later_reads(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    assert ctx.rwa_for("TSLA") is None, "no client, nothing to say"
    ctx.rwa_client = FakeRwa(DOC["data"])
    assert ctx.rwa_for("TSLA") is None
    assert wait_for(lambda: "TSLA" in ctx._rwa)
    for _ in range(4):
        assert ctx.rwa_for("TSLA")["ticker"] == "TSLAon"
    assert ctx.rwa_client.calls == 1


def test_a_failed_refresh_keeps_the_last_good_listing(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.rwa_client = FakeRwa(DOC["data"])
    assert ctx.rwa_for("TSLA", fetch=True)["status"] == "online"
    ctx.rwa_client = FakeRwa(None)
    assert ctx.rwa_for("TSLA", max_age=__import__("datetime").timedelta(0), fetch=True)["status"] == "online"


def _analyse(path, monkeypatch, info, notional=10_000.0):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from nightwatch.time_utils import utc_now  # noqa: F401
    from tests.test_pipeline import AS_OF

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.time_utils.utc_now", lambda: AS_OF)
    ctx = _ctx(path)
    ctx.rwa_client = FakeRwa(info)
    ctx._rwa["TSLA"] = (AS_OF, info)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=notional, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_a_paused_token_is_a_warning_and_a_raised_flag_and_leaves_the_size_alone(seeded_store, monkeypatch):  # noqa: F811
    ok = _analyse(seeded_store, monkeypatch, dict(DOC["data"]))
    paused = _analyse(seeded_store, monkeypatch, {**DOC["data"], "special_pause_reason_code": "halted"})
    assert ok["rwa_listing"]["flags"] == [] and any(s["kind"] == "bitget_wallet_rwa" for s in ok["sources"])
    assert next(x for x in ok["source_effects"] if x["kind"] == "bitget_wallet_rwa")["effect"] == "context"
    assert any("trading pause (halted)" in w for w in paused["warnings"]) and not any("trading pause" in w for w in ok["warnings"])
    assert next(x for x in paused["source_effects"] if x["kind"] == "bitget_wallet_rwa")["effect"] == "raised_flag"
    assert paused["verdict"]["recommended_notional"] == ok["verdict"]["recommended_notional"]


def test_no_cached_listing_means_no_row(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, None)
    assert r["rwa_listing"] is None and not any(s["kind"] == "bitget_wallet_rwa" for s in r["sources"])


def test_the_sources_page_row_and_used_for_column():
    from datetime import UTC, datetime

    from nightwatch.api.sources import annotate_used_for, rwa_row

    now = datetime(2026, 10, 5, tzinfo=UTC)
    rows = annotate_used_for([rwa_row({"TSLA": (now, DOC["data"]), "NVDA": (now, None)}), {"key": "bitget_earnings_calendar"}, {"key": "other"}])
    assert rows[0]["rows"] == 1 and rows[0]["effect"] == "raises a flag" and rows[0]["used_for_zh"]
    assert rows[1]["effect"] == "context only" and "used_for" not in rows[2]
