"""Sources that change the answer: the options-implied preset, the crowded-perp flag, and the
"what each source did" list built from the pipeline's own decisions."""

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from nightwatch.data.cboe import AtmQuote, OptionsChain
from nightwatch.data.models import Ticker, Venue
from nightwatch.data.store import Store
from nightwatch.features import open_interest as oi
from nightwatch.features import options as options_mod
from nightwatch.stress.scenarios import EmpiricalInputs, Severity, build_presets
from nightwatch.time_utils import UTC
from tests.test_pipeline import _ctx, seeded_store  # noqa: F401 - fixture


def _inputs(**kw):  # noqa: ANN003, ANN202
    rng = np.random.default_rng(3)
    base = dict(closed_window_ret_pct=rng.normal(0, 1.5, 300), earnings_gap_pct=np.array([]), abs_basis_closed_bps=np.abs(rng.normal(20, 10, 300)),
                rv_24h_now=0.35, horizon_h=24.0)
    base.update(kw)
    return EmpiricalInputs(**base)


def _worst_severe_adverse(presets, sign):  # noqa: ANN001, ANN202
    return max(sign * p.price_move_pct for p in presets if p.severity == Severity.SEVERE and p.price_move_pct)


# ------------------------------------------------------------ 1. the options-implied preset


def test_no_options_means_no_preset_and_nothing_else_changes():
    base = build_presets(_inputs())
    assert "options_implied_move" not in {p.id for p in base}
    assert [p.id for p in build_presets(_inputs(options_implied_move_pct=None))] == [p.id for p in base]


@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_the_preset_is_taken_in_the_adverse_direction_and_is_severe(sign):
    p = next(x for x in build_presets(_inputs(options_implied_move_pct=2.5, adverse_sign=sign)) if x.id == "options_implied_move")
    assert p.price_move_pct == pytest.approx(sign * 2.5) and p.severity == Severity.SEVERE and p.horizon_h == 24.0


def test_a_bigger_options_move_than_history_binds_and_a_smaller_one_does_not():
    without = build_presets(_inputs())
    history = _worst_severe_adverse(without, -1.0)
    big = next(p for p in build_presets(_inputs(options_implied_move_pct=history + 3.0)) if p.id == "options_implied_move")
    small = next(p for p in build_presets(_inputs(options_implied_move_pct=history / 2)) if p.id == "options_implied_move")
    assert big.calibration["binding"] is True and small.calibration["binding"] is False
    assert big.calibration["history_severe_pct"] == pytest.approx(history)


def test_adding_the_preset_never_makes_the_worst_severe_loss_smaller():
    """The size limit reads the worst severe preset: it can only tighten."""
    for move in (0.2, 1.0, 3.0, 8.0, 20.0):
        for sign in (-1.0, 1.0):
            before = _worst_severe_adverse(build_presets(_inputs(adverse_sign=sign)), sign)
            after = _worst_severe_adverse(build_presets(_inputs(adverse_sign=sign, options_implied_move_pct=move)), sign)
            assert after >= before and after == pytest.approx(max(before, move))


def test_the_stress_cap_is_never_larger_with_the_options_preset():
    from nightwatch.decision.gate import GatePolicy
    from nightwatch.decision.sensitivity import DecisionContext
    from nightwatch.decision.sizing import SizingPolicy
    from tests.test_sensitivity import ENTRY, NOW, book, ticket

    def cap(move):  # noqa: ANN001, ANN202
        dc = DecisionContext(
            entry_price=ENTRY, analog_p5_loss_pct=-3.0, quality_flags=(), regime_label="favorable", risk_multiplier=1.0, recent_losing_exits=(),
            breaker_state="NORMAL", breaker_reason="", now=NOW, book=book(), spot_taker_fee=0.001,
            presets=tuple(build_presets(_inputs(horizon_h=48.0, options_implied_move_pct=move))),
            max_exit_notional_within_budget=60_000.0, hedge_cost_bps_of_position=12.0, hedge_residual_p5_loss_pct=-0.4,
            gate_policy=GatePolicy(), sizing_policy=SizingPolicy(),
        )
        ev = dc.evaluate(ticket(notional_quote=80_000.0))
        return next(c.notional for c in ev.sizing.caps if c.name == "stress")

    plain, small, huge = cap(None), cap(0.3), cap(25.0)
    assert small == pytest.approx(plain)
    assert huge < plain


def test_the_line_says_so_plainly_only_when_options_expect_more():
    class P:
        def __init__(self, binding, hist):  # noqa: ANN001
            self.calibration = {"binding": binding, "history_severe_pct": hist}

    b = options_mod.attach_sizing({"implied_move_pct": 6.4}, P(True, 4.1))
    assert b["sizing_binding"] and b["sizing_line"].startswith("The options market expects more than history: the stress limit is sized on ±6.4%")
    q = options_mod.attach_sizing({"implied_move_pct": 1.0}, P(False, 4.1))
    assert not q["sizing_binding"] and q["sizing_line"] is None
    assert options_mod.attach_sizing({"implied_move_pct": 1.0}, None)["sizing_binding"] is False


# ----------------------------------------------------------------- the report end to end


def _chain(iv):  # noqa: ANN001, ANN202
    from tests.test_pipeline import AS_OF

    q = AtmQuote(expiry=date(2026, 9, 18), strike=350.0, call_mid=9.0, put_mid=8.5, call_iv=iv, put_iv=iv, n_strikes=12)
    return OptionsChain(ticker="TSLA", spot=350.0, quote_ts=AS_OF - timedelta(hours=20), fetched_at=AS_OF, iv30=iv, expiries=[q])


class _NoCboe:
    def get_chain(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
        raise AssertionError("never fetched")


class FakePerp:
    def __init__(self, contracts):  # noqa: ANN001
        self.contracts = contracts

    def get_open_interest(self, symbol):  # noqa: ANN001, ANN201
        from tests.test_pipeline import AS_OF

        return self.contracts, AS_OF


def _analyse(path, monkeypatch, *, chain_value=None, perp=None, leverage=None, notional=60_000.0):  # noqa: ANN001, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF

    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    ctx = _ctx(path)
    ctx.options_client = _NoCboe()
    ctx._options["TSLA"] = (AS_OF, chain_value if chain_value is not None else "none")
    if perp is not None:
        ctx.perp_client = perp
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=notional, account_equity_quote=200_000.0, leverage=leverage,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    return analyze(ctx, ticket, as_of=AS_OF, record=False).to_dict()


def test_a_huge_implied_move_sizes_the_stress_limit_and_the_report_says_so(seeded_store, monkeypatch):  # noqa: F811
    plain = _analyse(seeded_store, monkeypatch, chain_value="none")
    r = _analyse(seeded_store, monkeypatch, chain_value=_chain(2.5))
    ids = {p["id"] for p in r["stress"]["presets"]}
    assert "options_implied_move" in ids and "options_implied_move" not in {p["id"] for p in plain["stress"]["presets"]}
    o = r["options"]
    assert o["sizing_binding"] and o["sizing_line"].startswith("The options market expects more than history")
    stress_cap = lambda rep: next(c["notional"] for c in rep["sizing"]["caps"] if c["name"] == "stress")  # noqa: E731
    assert stress_cap(r) < stress_cap(plain)
    # Never less cautious than without the options market.
    assert (r["verdict"]["recommended_notional"] or 0) <= (plain["verdict"]["recommended_notional"] or 0) + 1e-6


def test_a_mild_implied_move_changes_nothing_in_the_size(seeded_store, monkeypatch):  # noqa: F811
    plain = _analyse(seeded_store, monkeypatch, chain_value="none")
    r = _analyse(seeded_store, monkeypatch, chain_value=_chain(0.05))
    assert r["options"]["sizing_binding"] is False and r["options"]["sizing_line"] is None
    assert r["verdict"]["recommended_notional"] == plain["verdict"]["recommended_notional"]
    assert r["sizing"]["binding_cap"] == plain["sizing"]["binding_cap"]


# ------------------------------------------------------------------- 2. open interest


def tick(store, ts, value):  # noqa: ANN001, ANN202
    store.insert_tickers([Ticker(venue=Venue.BITGET_UMCBL, symbol="TSLAUSDT", ts=ts, last=370.0, bid=369.9, ask=370.1, open_interest=value, observed_at=ts)])


NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path):  # noqa: ANN001, ANN201
    with Store(tmp_path / "oi.sqlite") as s:
        yield s


def _history(store, hours=24 * 12, wobble=0.01, seed=5):  # noqa: ANN001, ANN202
    rng = np.random.default_rng(seed)
    v = 30_000.0
    for h in range(hours, 0, -1):
        v *= 1.0 + rng.normal(0, wobble)
        tick(store, NOW - timedelta(hours=h), v)
    return v


def test_changes_are_measured_against_the_reading_a_day_earlier():
    series = [(NOW - timedelta(hours=h), 100.0 + (48 - h)) for h in range(48, 0, -1)]
    ch = oi.changes_24h(series, tolerance=timedelta(minutes=30))
    assert ch.size == 24 and ch[0] == pytest.approx((124.0 / 100.0 - 1) * 100)


def test_a_fresh_install_flags_nothing(store):  # noqa: ANN001
    tick(store, NOW - timedelta(hours=24), 10_000.0)
    b = oi.build("TSLAUSDT", 20_000.0, NOW, store)
    assert b["change_24h_pct"] == pytest.approx(100.0) and b["crowded"] is False and b["threshold_pct"] is None and b["crowded_line"] is None


def test_a_jump_above_the_top_decile_of_its_own_history_is_crowded(store):  # noqa: ANN001
    last = _history(store)
    b = oi.build("TSLAUSDT", last * 1.5, NOW, store)
    assert b["n_history"] >= oi.MIN_OBS and b["threshold_pct"] >= oi.FLOOR_PCT
    assert b["crowded"] is True and b["crowded_line"].startswith("crowded: OI +")
    assert "in 24h" in b["crowded_line"]


def test_a_move_inside_the_usual_range_is_not_and_neither_is_a_fall(store):  # noqa: ANN001
    last = _history(store)
    assert oi.build("TSLAUSDT", last * 1.0005, NOW, store)["crowded"] is False
    assert oi.build("TSLAUSDT", last * 0.6, NOW, store)["crowded"] is False


def test_a_quiet_history_still_needs_the_floor(store):  # noqa: ANN001
    last = _history(store, wobble=0.0005)
    b = oi.build("TSLAUSDT", last * 1.02, NOW, store)
    assert b["threshold_pct"] == pytest.approx(oi.FLOOR_PCT) and b["crowded"] is False


def test_a_crowded_perp_is_a_warning_and_a_leverage_line_and_leaves_the_size_alone(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    with Store(seeded_store) as s:
        v = 30_000.0
        rng = np.random.default_rng(9)
        for h in range(24 * 10, 0, -1):
            v *= 1.0 + rng.normal(0, 0.01)
            tick(s, AS_OF - timedelta(hours=h), v)
        flat = v
    quiet = _analyse(seeded_store, monkeypatch, perp=FakePerp(flat), leverage=3.0)
    crowded = _analyse(seeded_store, monkeypatch, perp=FakePerp(flat * 1.6), leverage=3.0)
    assert crowded["open_interest"]["crowded"] and not quiet["open_interest"]["crowded"]
    assert crowded["leverage"]["open_interest_crowded_line"].startswith("crowded: OI +")
    assert any("looks crowded" in w for w in crowded["warnings"]) and not any("looks crowded" in w for w in quiet["warnings"])
    assert crowded["verdict"]["recommended_notional"] == quiet["verdict"]["recommended_notional"]


# --------------------------------------------------------- 3. what each source did


def test_every_source_gets_a_row_and_an_effect_from_the_decisions(seeded_store, monkeypatch):  # noqa: F811
    r = _analyse(seeded_store, monkeypatch, chain_value=_chain(2.5), perp=FakePerp(1_000.0))
    rows = {x["kind"]: x for x in r["source_effects"]}
    assert set(rows) == {s["kind"] for s in r["sources"]}
    assert all(x["effect"] in ("moved_size", "set_preset", "raised_flag", "context") and x["supplied"] and x["supplied_zh"] for x in rows.values())
    assert rows["cboe_options"]["effect"] in ("moved_size", "set_preset")
    # The cut here is the trader's own concentration limit: no data source is credited with it.
    assert r["sizing"]["binding_cap"] == "concentration" and r["verdict"]["recommended_notional"] < r["ticket"]["notional_quote"]
    assert not {k for k, x in rows.items() if x["effect"] == "moved_size"}
    assert rows["bitget_open_interest"]["effect"] == "context"


def test_the_options_source_is_credited_with_the_size_only_when_it_set_it(seeded_store, monkeypatch):  # noqa: F811
    big = _analyse(seeded_store, monkeypatch, chain_value=_chain(2.5), notional=150_000.0)
    mild = _analyse(seeded_store, monkeypatch, chain_value=_chain(0.05), notional=150_000.0)
    eff = lambda rep: next(x["effect"] for x in rep["source_effects"] if x["kind"] == "cboe_options")  # noqa: E731
    assert eff(mild) == "context"
    if big["sizing"]["binding_cap"] == "stress":
        assert eff(big) == "moved_size"
    else:
        assert eff(big) == "set_preset"


def test_a_crowded_perp_is_a_raised_flag(seeded_store, monkeypatch):  # noqa: F811
    from tests.test_pipeline import AS_OF

    with Store(seeded_store) as s:
        v = 30_000.0
        rng = np.random.default_rng(11)
        for h in range(24 * 10, 0, -1):
            v *= 1.0 + rng.normal(0, 0.01)
            tick(s, AS_OF - timedelta(hours=h), v)
    r = _analyse(seeded_store, monkeypatch, perp=FakePerp(v * 1.7))
    assert next(x for x in r["source_effects"] if x["kind"] == "bitget_open_interest")["effect"] == "raised_flag"


def _stub(binding, worst_id, rec, requested=100_000.0, options=None):  # noqa: ANN001, ANN202
    from types import SimpleNamespace

    NS = SimpleNamespace

    def sc(i, sev):  # noqa: ANN001, ANN202
        return NS(id=i, severity=NS(value=sev))

    presets = [sc("closed_window_gap_p5", "severe"), sc("options_implied_move", "severe")]
    pct = {"closed_window_gap_p5": -2.0, "options_implied_move": -2.0}
    pct[worst_id] = -9.0
    return NS(
        ticket=NS(notional_quote=requested), verdict=NS(recommended_notional=rec), sizing=NS(binding_cap=binding),
        stress=NS(presets=presets, impacts=[NS(total_pct_of_notional=pct[p.id]) for p in presets], inputs_summary={}),
        sources=[{"kind": "cboe_options", "label": "Cboe", "rows_used": 12}, {"kind": "bitget_candles", "label": "Candles", "rows_used": 900}, {"kind": "orderbook", "label": "Book", "levels": 40}],
        execution=NS(exit_quote=None), options=options or {"implied_move_pct": 9.0, "sizing_binding": True}, leverage=None, street=None,
        signal=None, open_interest=None, corporate_events=None, filings=[], warnings=[],
    )


def test_effects_credit_the_source_the_binding_cap_is_built_on():
    from nightwatch.pipeline.effects import build

    rows = {x["kind"]: x["effect"] for x in build(_stub("stress", "options_implied_move", 40_000.0))}
    assert rows["cboe_options"] == "moved_size" and rows["bitget_candles"] == "set_preset"
    rows = {x["kind"]: x["effect"] for x in build(_stub("stress", "closed_window_gap_p5", 40_000.0, options={"implied_move_pct": 1.0, "sizing_binding": False}))}
    assert rows["cboe_options"] == "context" and rows["bitget_candles"] == "moved_size"
    rows = {x["kind"]: x["effect"] for x in build(_stub("exit_liquidity", "closed_window_gap_p5", 40_000.0))}
    assert rows["orderbook"] == "moved_size" and rows["bitget_candles"] == "set_preset"


def test_effects_never_credit_a_source_when_the_size_was_not_cut():
    from nightwatch.pipeline.effects import build

    rows = {x["kind"]: x["effect"] for x in build(_stub("stress", "options_implied_move", 98_000.0))}
    assert "moved_size" not in rows.values() and rows["cboe_options"] == "set_preset"
