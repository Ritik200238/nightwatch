"""Rebalance plans, whole-book crash replays and reverse stress, on synthetic history."""

import pytest

from nightwatch.decision import book_plans
from nightwatch.decision.portfolio import Position, build_book_model
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture
from tests.test_portfolio import frame, market  # noqa: F401 - fixture

EQUITY = 100_000.0
TABLE = {
    "_meta": {"windows": {"c1": {"name": "Crash one", "market_days": {"gap_down": "2020-03-16", "gap_up": "2020-03-13"}},
                           "c2": {"name": "Crash two", "market_days": {"gap_down": "2022-02-24", "gap_up": "2022-03-09"}}}},
    "A": {"c1": {"gap_down_pct": -10.0, "gap_up_pct": 5.0}, "c2": {"gap_down_pct": -4.0, "gap_up_pct": 2.0}},
    "B": {"c1": {"gap_down_pct": -8.0, "gap_up_pct": 6.0}, "c2": {"gap_down_pct": -2.0, "gap_up_pct": 1.0}},
}


@pytest.fixture
def frames(market):  # noqa: F811
    return {"A": frame(seed=1, shared=market, beta=0.95), "B": frame(seed=2, shared=market, beta=0.95)}


def _build(frames, held, new, *, limit_pct=2.0, perps=("A", "B"), leverage=None):
    model, _, _ = build_book_model(held, new.ticker, frames, horizon_h=24)
    return book_plans.build(model, held, new, equity=EQUITY, limit_pct_of_equity=limit_pct, horizon_h=24.0,
                            perp_names=set(perps), spot_taker=0.001, perp_taker=0.0006, leverage=leverage, table=TABLE)


def test_a_breach_gets_plans_that_are_rescored_inside_the_limit(frames):
    held, new = [Position("A", "long", 30_000)], Position("B", "long", 30_000)
    st = _build(frames, held, new)
    assert st.breached and st.plans
    assert {p.lever for p in st.plans} <= {"smaller_trade", "skip_trade", "trim_holding", "hedge_perp"}
    for p in st.plans:
        assert p.after.tail_quote >= p.before.tail_quote  # every plan makes the bad case no worse
        if p.achieves_limit:
            assert -p.after.tail_quote <= st.limit_quote + 1e-6 and p.after.inside_limit
    smaller = next(p for p in st.plans if p.lever == "smaller_trade")
    assert 0 < smaller.amount_quote < new.notional_quote


def test_no_breach_means_no_plans_but_still_crashes_and_reverse(frames):
    st = _build(frames, [Position("A", "long", 3_000)], Position("B", "long", 2_000), limit_pct=50.0)
    assert not st.breached and st.plans == []
    assert len(st.crashes) == 2 and st.reverse


def test_the_book_crash_is_one_market_day_not_a_sum_of_worst_cases(frames):
    held, new = [Position("A", "long", 10_000)], Position("B", "short", 10_000)
    st = _build(frames, held, new)
    c1 = next(c for c in st.crashes if c.key == "c1")
    # long A -10%, short B on the same down day gains 8%: the harsher day for this book is the up day
    assert c1.held_quote == pytest.approx(-1_000.0)
    assert c1.asked_quote == pytest.approx(min(-1_000.0 + 800.0, 500.0 - 600.0))


def test_reverse_stress_shock_is_loss_over_net_exposure(frames):
    st = _build(frames, [Position("A", "long", 30_000)], Position("B", "long", 10_000), limit_pct=4.0)
    lv = next(x for x in st.reverse if x.key == "limit")
    assert lv.loss_quote == pytest.approx(4_000.0)
    assert lv.shock_pct_before == pytest.approx(4_000 / 30_000 * 100)
    assert lv.shock_pct_after == pytest.approx(4_000 / 40_000 * 100)
    assert st.direction == "down"


def test_leveraged_leg_is_compared_with_the_loss_limit(frames):
    lev = {"leverage": 10.0, "liquidation_distance_pct": 6.0, "perp_symbol": "RBUSDT"}
    st = _build(frames, [Position("A", "long", 30_000)], Position("B", "long", 10_000), leverage=lev)
    assert st.liquidation and st.liquidation.distance_pct == 6.0
    assert st.liquidation.comes_before_limit is False  # 6% away is sooner than the 10% common move that costs 4% of equity
    assert 0 <= st.liquidation.windows_hit <= st.liquidation.windows


def test_an_unhedgeable_carrier_gets_no_perp_plan(frames):
    st = _build(frames, [Position("A", "long", 30_000)], Position("B", "long", 30_000), perps=())
    assert all(p.lever != "hedge_perp" for p in st.plans)


def test_holdings_with_no_history_still_get_a_crash_line(frames):
    held = [Position("A", "long", 10_000), Position("ZZZ", "long", 5_000)]
    st = _build(frames, held, Position("B", "long", 5_000))
    c1 = next(c for c in st.crashes if c.key == "c1")
    assert "ZZZ" in c1.missing and c1.held_quote == pytest.approx(-1_000.0)


def test_no_book_no_stress(frames):
    assert book_plans.build(None, [], None, equity=EQUITY, limit_pct_of_equity=4.0, horizon_h=24.0, perp_names=set(), spot_taker=0, perp_taker=0) is None


def test_pipeline_report_carries_the_stress_and_it_is_cheap(seeded_store):  # noqa: F811
    import time

    from nightwatch.decision.sizing import SizingPolicy
    from nightwatch.decision.ticket import TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_book_sizing import EQUITY, _entry
    from tests.test_pipeline import AS_OF, _ctx

    ctx = _ctx(seeded_store)
    ctx.sizing_policy = SizingPolicy(max_book_tail_pct_of_equity=1.0)
    t = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=EQUITY, stop_price=_entry(ctx, "TSLA") * 0.96,
                    thesis="t", invalidation="i", open_positions=(("TSLA", "long", 60_000.0), ("NVDA", "long", 40_000.0)))
    t0 = time.perf_counter()
    r = analyze(ctx, t, as_of=AS_OF, record=False)
    took = time.perf_counter() - t0
    st = r.portfolio.stress
    assert st is not None and st.breached and st.plans
    d = r.to_dict()["portfolio"]["stress"]
    assert d["plans"][0]["after"]["tail_quote"] >= d["plans"][0]["before"]["tail_quote"]
    assert r.timings_ms["portfolio"] < 5000 and took < 60
    ctx.store.close()
