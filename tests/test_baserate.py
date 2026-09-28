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
