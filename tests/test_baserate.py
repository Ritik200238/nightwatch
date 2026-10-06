"""The historical distribution asked for directly, with no trade attached."""

import threading
from types import SimpleNamespace

from nightwatch.api import baserate
from tests.test_pipeline import AS_OF, _ctx, seeded_store  # noqa: F401 - fixture


def test_a_base_rate_question_is_recognised_and_a_trade_is_not():
    q = baserate.detect("what's the base rate of TSLA falling 5% over a weekend?", ["TSLA"])
    assert q is not None and q.ticker == "TSLA" and q.move_pct == 5.0 and not q.up and q.weekend
    up = baserate.detect("what are the odds TSLA rallies 3% overnight", ["TSLA"])
    assert up is not None and up.up and not up.weekend
    assert baserate.detect("TSLA 周末跌5%的概率是多少", ["TSLA"]) is not None
    assert baserate.detect("long 20k TSLA overnight, stop 3%", ["TSLA"]) is None


def test_the_answer_counts_closed_windows_and_similar_moments(seeded_store):  # noqa: F811
    state = SimpleNamespace(ctx=_ctx(seeded_store), lock=threading.Lock())
    q = baserate.detect("how often does TSLA fall 1% overnight?", ["TSLA"])
    out = baserate.answer(state, q, as_of=AS_OF)
    assert out["mode"] == "base_rate" and out["report"] is not None
    assert "past overnight closes" in out["reply"] and "USDT long" in out["reply"]


# ------------------------------------------------------- the trade on screen carries into the answer


def _client(seeded_store, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from nightwatch.api.app import create_app
    from nightwatch.config import Settings

    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    return TestClient(create_app(settings, warm=False))


def test_the_rerun_uses_the_trade_on_screen_not_a_default_long(seeded_store, monkeypatch):  # noqa: F811
    with _client(seeded_store, monkeypatch) as c:
        trade = {"ticker": "TSLA", "side": "short", "notional_quote": 35000, "account_equity_quote": 250000, "stop_price": 330,
                 "leverage": 3, "horizon_kind": "hours", "horizon_hours": 30, "as_of": AS_OF.isoformat()}
        fid = c.post("/analyze", json=trade).json()["forecast_id"]
        ask = "how often does TSLA fall 1% overnight?"
        out = c.post("/chat", json={"messages": [{"role": "user", "content": ask}], "context_forecast_id": fid}).json()
        t = out["report"]["ticket"]
        assert (t["side"], t["notional_quote"], t["account_equity_quote"], t["stop_price"], t["leverage"], t["horizon_hours"]) == ("short", 35000, 250000, 330, 3, 30)
        assert "10,000" not in out["reply"] and "default" not in out["reply"]
        assert "35,000 USDT short" in out["reply"] and "stop at 330.00" in out["reply"] and "3x leverage" in out["reply"] and "account 250,000 USDT" in out["reply"]
        assert "held for 30h" in out["reply"]  # says which hold was used
        assert out["base_rate"]["trade"]["own"] is True
        # no trade on screen: the default is named as a default, with its own hold
        plain = c.post("/chat", json={"messages": [{"role": "user", "content": ask}]}).json()
        assert "default 10,000 USDT long held until the next US open" in plain["reply"] and "not your own trade" in plain["reply"]
        # a different token than the one on screen does not borrow the trade
        other = c.post("/chat", json={"messages": [{"role": "user", "content": "how often does NVDA fall 1% overnight?"}], "context_forecast_id": fid}).json()
        assert other["report"]["ticket"]["ticker"] == "NVDA" and other["report"]["ticket"]["notional_quote"] == 10000


def test_a_weekend_question_names_the_weekend_hold_it_used(seeded_store, monkeypatch):  # noqa: F811
    with _client(seeded_store, monkeypatch) as c:
        out = c.post("/chat", json={"messages": [{"role": "user", "content": "how often does TSLA fall 1% over a weekend?"}]}).json()
        assert "weekend" in out["reply"] and "held the same way" not in out["reply"]
        assert "default 10,000 USDT long held" in out["reply"]
        zh = c.post("/chat", json={"messages": [{"role": "user", "content": "TSLA 周末跌1%的概率是多少"}]}).json()
        assert "默认交易" in zh["reply"] and "周末" in zh["reply"]
