"""Bitget lookups a leveraged chat needs must never hold the chat for the exchange's answer time.

Measured on the seeded store (analysis alone about 1.1 s): with a perp endpoint taking 4 s a call,
a leveraged analysis took 9.1 s, and with it down 13-17 s (production retries 20 s timeouts, which
is where a 105 s leveraged chat came from). With the tiers and open interest warmed ahead of time
the same analysis takes 1.5 s, and a cold one waits at most the bound below.
"""

import threading
import time
from datetime import timedelta

from tests.test_open_interest import _ctx
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture

ROWS = [{"startUnit": 0, "endUnit": 1e9, "leverage": 20, "keepMarginRate": 0.01}]


class SlowPerp:
    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail, self.calls = delay, fail, 0
        self.release = threading.Event()

    def _answer(self, value):
        self.calls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("down")
        return value

    def get_position_tiers(self, symbol):
        return self._answer(ROWS)

    def get_open_interest(self, symbol):
        return self._answer((1_000.0, AS_OF))


def test_a_missing_tier_table_is_waited_for_only_briefly_then_arrives_behind_the_request(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.perp_client = SlowPerp(delay=0.6)
    t0 = time.perf_counter()
    assert ctx.margin_tiers("TSLAUSDT", wait_s=0.05) is None
    assert time.perf_counter() - t0 < 0.4, "the request did not wait for the exchange"
    time.sleep(0.9)
    assert ctx.margin_tiers("TSLAUSDT")[0].max_leverage == 20.0
    assert ctx.perp_client.calls == 1


def test_a_down_exchange_is_asked_once_not_by_every_chat(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.perp_client = SlowPerp(fail=True)
    for _ in range(4):
        assert ctx.margin_tiers("TSLAUSDT", wait_s=1.0) is None
    assert ctx.perp_client.calls == 1


def test_a_stale_tier_table_is_served_at_once_while_a_new_one_is_fetched(seeded_store):  # noqa: F811
    from nightwatch.execution.leverage import parse_tiers

    ctx = _ctx(seeded_store)
    ctx.perp_client = SlowPerp(delay=0.5)
    ctx._tiers["TSLAUSDT"] = (AS_OF - timedelta(days=2), parse_tiers(ROWS))
    t0 = time.perf_counter()
    assert ctx.margin_tiers("TSLAUSDT") is not None
    assert time.perf_counter() - t0 < 0.3


def test_open_interest_dollar_figure_uses_the_price_of_the_asking_analysis(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.perp_client = SlowPerp()
    assert ctx.open_interest_for("TSLAUSDT", price=100.0)["usd"] == 100_000.0
    assert ctx.open_interest_for("TSLAUSDT", price=200.0)["usd"] == 200_000.0
    assert ctx.perp_client.calls == 1
