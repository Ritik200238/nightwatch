"""The bitget-signal Skill backend: distrusted, cross-checked, and never a sizing input."""

import json
import threading
from datetime import timedelta

import httpx
import numpy as np
import pandas as pd

from nightwatch.data.bitget_signal import BitgetSignalClient, _message
from nightwatch.features import signal
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture


def _sse(payload: dict) -> str:
    return "event: message\ndata: " + json.dumps(payload) + "\n\n"


def _transport(tool_docs: dict[str, dict | None], *, wrong_id: bool = False, sessions: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            if sessions is not None:
                sessions.append(1)
            return httpx.Response(200, headers={"mcp-session-id": f"s{len(sessions or [])}"}, text=_sse({"jsonrpc": "2.0", "id": body["id"], "result": {}}))
        if method == "notifications/initialized":
            return httpx.Response(202)
        args = body["params"]["arguments"]
        doc = tool_docs.get(args.get("action") or body["params"]["name"])
        if doc is None:
            return httpx.Response(200, text=_sse({"jsonrpc": "2.0", "id": body["id"], "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}))
        rid = 99 if wrong_id else body["id"]
        return httpx.Response(200, text=_sse({"jsonrpc": "2.0", "id": rid, "result": {"isError": False, "content": [{"type": "text", "text": json.dumps(doc)}]}}))

    return BitgetSignalClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


RSI = {"symbol": "TSLA", "timeframe": "4h", "rsi": 28.92, "period": 14, "signal": "oversold"}
MACD = {"symbol": "TSLA", "timeframe": "4h", "macd": -5.027, "signal": -0.532, "histogram": -4.495, "cross": "death_cross"}


def test_the_client_reads_rsi_and_macd_and_uses_a_fresh_session_each_time():
    sessions: list = []
    c = _transport({"rsi": RSI, "macd": MACD}, sessions=sessions)
    assert c.rsi("TSLA")["rsi"] == 28.92
    assert c.macd("TSLA")["cross"] == "death_cross"
    assert len(sessions) == 2


def test_a_reply_with_someone_elses_id_is_ignored():
    assert _transport({"rsi": RSI}, wrong_id=True).rsi("TSLA") is None
    assert _message(_sse({"id": 1, "result": {}}) + _sse({"id": 2, "result": {"x": 1}}), 2)["result"] == {"x": 1}


def test_failures_and_junk_are_no_reading_never_an_exception():
    assert _transport({"rsi": None}).rsi("TSLA") is None
    assert _transport({"rsi": {"rsi": 140}}).rsi("TSLA") is None
    assert _transport({"macd": {"error": "x"}}).macd("TSLA") is None

    def boom(request):  # noqa: ANN001, ANN202
        raise httpx.ConnectTimeout("slow")

    assert BitgetSignalClient(client=httpx.Client(transport=httpx.MockTransport(boom))).rsi("TSLA") is None


def test_health_counts_the_tools_that_answered():
    h = _transport({"rsi": RSI, "macd": MACD}).health()
    assert h == {"answering": 2, "tried": 5}


def _hourly(n=400, seed=1):
    idx = pd.date_range("2026-08-01", periods=n, freq="h", tz="UTC")
    return pd.Series(100 + np.cumsum(np.random.default_rng(seed).normal(0, 0.6, n)), index=idx)


class FakeSkill:
    def __init__(self, rsi):  # noqa: ANN001
        self._rsi = rsi

    def rsi(self, ticker):  # noqa: ANN001, ANN201
        return {"rsi": self._rsi, "timeframe": "4h"}

    def macd(self, ticker):  # noqa: ANN001, ANN201
        return MACD


def test_a_reading_that_agrees_with_our_candles_is_kept_and_one_that_does_not_is_withheld():
    closes = _hourly()
    own = signal.own_rsi_4h(closes)
    assert own is not None and 0 < own < 100
    good = signal.build(FakeSkill(own + 3), "TSLA", closes)
    assert good["agrees"] and good["own_rsi"] == round(own, 1) and good["macd"]["cross"] == "death_cross"
    bad = signal.build(FakeSkill(own + 12), "TSLA", closes)
    assert not bad["agrees"] and "not shown" in bad["note"] and bad["macd"] is None


def test_an_unverifiable_reading_is_not_shown():
    assert signal.build(FakeSkill(30.0), "TSLA", None) is None
    assert signal.build(FakeSkill(30.0), "TSLA", _hourly(20)) is None


def test_own_rsi_matches_a_hand_computation_on_a_falling_series():
    idx = pd.date_range("2026-08-01", periods=200, freq="h", tz="UTC")
    assert signal.own_rsi_4h(pd.Series(np.linspace(200, 100, 200), index=idx)) < 5
    assert signal.own_rsi_4h(pd.Series(np.linspace(100, 200, 200), index=idx)) > 95


class Skill(FakeSkill):
    def health(self):  # noqa: ANN201
        return {"answering": 1, "tried": 5}


def test_the_skill_never_changes_the_verdict_or_the_caps(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    def run(with_signal):  # noqa: ANN001, ANN202
        from nightwatch.decision.ticket import HorizonKind, TradeTicket
        from nightwatch.pipeline.analyze import analyze
        from nightwatch.stress.scenarios import Side
        from tests.test_pipeline import _ctx

        monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
        ctx = _ctx(seeded_store)
        if with_signal:
            bars = ctx.store.get_bars(*_spot(ctx), start=AS_OF - timedelta(days=30))
            own = signal.own_rsi_4h(bars["close"])
            ctx.signal_client = Skill(own)
            ctx.signal_for("TSLA", fetch=True)
        t = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                        horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
        return analyze(ctx, t, as_of=AS_OF, record=False).to_dict()

    def _spot(ctx):  # noqa: ANN001, ANN202
        from nightwatch.data.models import Interval, Venue

        return Venue.BITGET_SPOT, ctx.spec("TSLA").spot_symbol, Interval.H1

    without, with_ = run(False), run(True)
    assert without["signal"] is None
    assert with_["signal"] and with_["signal"]["agrees"] and any(s["kind"] == "bitget_signal" for s in with_["sources"])
    for key in ("verdict", "gate", "sizing"):
        assert json.dumps(with_[key], sort_keys=True, default=str) == json.dumps(without[key], sort_keys=True, default=str), key


def test_an_analysis_never_waits_on_the_skill(seeded_store):  # noqa: F811
    from tests.test_pipeline import _ctx

    gate = threading.Event()

    class Slow(FakeSkill):
        def rsi(self, ticker):  # noqa: ANN001, ANN201
            gate.wait(5)
            return None

    ctx = _ctx(seeded_store)
    ctx.signal_client = Slow(30.0)
    assert ctx.signal_for("TSLA") is None
    assert "TSLA" in ctx._signal_pending
    gate.set()


def test_the_brief_and_the_follow_up_say_it_is_context():
    from nightwatch.api import followup, followup_zh

    r = {"signal": {"rsi": 28.9, "timeframe": "4h", "reading": "oversold", "own_rsi": 28.2, "agrees": True,
                    "macd": {"macd": -5.0, "signal": -0.5, "histogram": -4.5, "cross": "death_cross"}}}
    a = followup.answer(r, "what does the RSI say?")
    assert a and a.kind == "technicals" and "28.9" in a.text and "28.2" in a.text and "Context only" in a.text
    z = followup_zh.answer(r, "技术面怎么样")
    assert z and z.kind == "technicals" and "28.9" in z.text
    none = followup.answer({"signal": None}, "what is the rsi")
    assert none and "not shown" in none.text


def test_sources_shows_the_skill_backend_health_without_waiting(seeded_store, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from nightwatch.api.app import create_app
    from nightwatch.config import Settings
    from tests.test_pipeline import AS_OF

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        state = c.app.state.nw if hasattr(c.app.state, "nw") else None
        assert [r["key"] for r in c.get("/sources").json()][-1] != "bitget_signal", "off in tests by default"
        if state is not None:
            state.ctx.signal_client = Skill(30.0)
            state.ctx.signal_health()  # starts the background probe
            for _ in range(100):
                if state.ctx._signal_health:
                    break
                threading.Event().wait(0.05)
            row = c.get("/sources?fresh=1").json()[-1]  # a new key: the page itself is cached for a minute
            assert row["key"] == "bitget_signal" and row["latest_label"] == "1 of 5 tools answering"
