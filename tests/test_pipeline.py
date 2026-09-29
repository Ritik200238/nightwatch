"""End-to-end pipeline on synthetic data: no network, deterministic."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from nightwatch.analog.engine import AnalogConfig
from nightwatch.data.models import (
    Bar,
    EarningsEvent,
    FundingRate,
    Instrument,
    InstrumentType,
    Interval,
    MacroRelease,
    OrderBookLevel,
    OrderBookSnapshot,
    PriceKind,
    Venue,
)
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.decision.sizing import Verdict
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.pipeline.analyze import AnalysisContext, analyze
from nightwatch.pipeline.render import render_text
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import ET, classify_session

UTC = UTC
START = datetime(2026, 3, 1, tzinfo=UTC)
AS_OF = datetime(2026, 9, 12, 14, 10, tzinfo=UTC)  # Saturday


def _seed_ticker(store: Store, ticker: str, seed: int, price0: float) -> None:
    rng = np.random.default_rng(seed)
    hours = int((AS_OF - START).total_seconds() // 3600) + 1
    ts_index = [START + timedelta(hours=i) for i in range(hours)]
    rets = rng.normal(0, 0.004, hours)
    closes = price0 * np.exp(np.cumsum(rets))
    spot, perp_t, perp_i, perp_m = [], [], [], []
    for i, ts in enumerate(ts_index):
        c = float(closes[i])
        info = classify_session(ts)
        # Token drifts a little from the index while the US market is shut.
        basis = rng.normal(0, 0.0015) if info.is_closed else rng.normal(0, 0.0005)
        spot_c = c * (1 + basis)
        if rng.random() < 0.03:  # ~3% of hours have no trades (omitted upstream)
            pass
        else:
            spot.append(Bar(venue=Venue.BITGET_SPOT, symbol=f"R{ticker}USDT", interval=Interval.H1, ts=ts, open=spot_c, high=spot_c * 1.002, low=spot_c * 0.998, close=spot_c, volume_quote=50_000.0, observed_at=ts))
        for kind, lst in ((PriceKind.TRADE, perp_t), (PriceKind.INDEX, perp_i), (PriceKind.MARK, perp_m)):
            lst.append(Bar(venue=Venue.BITGET_UMCBL, symbol=f"{ticker}USDT", interval=Interval.H1, kind=kind, ts=ts, open=c, high=c * 1.002, low=c * 0.998, close=c, volume_quote=100_000.0, observed_at=ts))
    for lst in (spot, perp_t, perp_i, perp_m):
        store.upsert_bars(lst)
    # Native: regular-session hourly bars at :30 and daily bars.
    native_h, native_d = [], []
    day = START
    while day < AS_OF:
        info = classify_session(day.replace(hour=15))
        if not info.is_closed or classify_session(day.replace(hour=16)).session.value == "regular":
            base = float(closes[min(int((day - START).total_seconds() // 3600), hours - 1)])
            for k in range(7):
                t = day.replace(hour=13, minute=30) + timedelta(hours=k)
                if classify_session(t).session.value == "regular":
                    native_h.append(Bar(venue=Venue.YAHOO, symbol=ticker, interval=Interval.H1, ts=t, open=base, high=base * 1.003, low=base * 0.997, close=base * (1 + rng.normal(0, 0.001)), observed_at=t))
            native_d.append(Bar(venue=Venue.YAHOO, symbol=ticker, interval=Interval.D1, ts=day.replace(hour=13, minute=30), open=base * (1 + rng.normal(0, 0.01)), high=base * 1.02, low=base * 0.98, close=base, volume_base=1e6, observed_at=day))
        day += timedelta(days=1)
    store.upsert_bars(native_h)
    store.upsert_bars(native_d)
    # Earnings every ~91 days, after close; funding every 8h.
    ev = []
    d = datetime(2026, 4, 22, tzinfo=ET)
    while d.astimezone(UTC) < AS_OF + timedelta(days=60):
        ev.append(EarningsEvent(ticker=ticker, report_date=d.astimezone(UTC), timing="amc", source="nasdaq_calendar", observed_at=START))
        d += timedelta(days=91)
    store.upsert_earnings(ev)
    store.upsert_funding([FundingRate(venue=Venue.BITGET_UMCBL, symbol=f"{ticker}USDT", ts=START + timedelta(hours=8 * i), rate=float(rng.normal(0, 0.0001)), observed_at=START) for i in range(hours // 8)])


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "pipeline.sqlite"
    with Store(path) as s:
        for ticker, seed, p0 in (("TSLA", 1, 350.0), ("NVDA", 2, 180.0), ("AAPL", 3, 230.0)):
            _seed_ticker(s, ticker, seed, p0)
            s.upsert_instruments([
                Instrument(venue=Venue.BITGET_SPOT, symbol=f"R{ticker}USDT", type=InstrumentType.SPOT, base=f"r{ticker}", quote="USDT", underlying_ticker=ticker, is_tokenized_stock=True, status="online", taker_fee=0.001, maker_fee=0.001, observed_at=START),
                Instrument(venue=Venue.BITGET_UMCBL, symbol=f"{ticker}USDT", type=InstrumentType.PERP, base=ticker, quote="USDT", underlying_ticker=ticker, is_tokenized_stock=True, status="normal", taker_fee=0.0006, maker_fee=0.0002, funding_interval_hours=8, observed_at=START),
            ])
        s.upsert_macro([MacroRelease(series_id="FOMC", name="FOMC", release_ts=datetime(2026, 9, 16, 14, tzinfo=ET).astimezone(UTC), source="fed", observed_at=START)])
        # A live-ish book for TSLA at as_of.
        mid = float(s.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)["close"].iloc[-1])
        bids = tuple(OrderBookLevel(price=mid * (1 - 0.0004 * (i + 0.5)), size=30.0) for i in range(40))
        asks = tuple(OrderBookLevel(price=mid * (1 + 0.0004 * (i + 0.5)), size=30.0) for i in range(40))
        s.insert_orderbook(OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=AS_OF - timedelta(minutes=2), observed_at=AS_OF, bids=bids, asks=asks))
    yield path


def _ctx(path) -> AnalysisContext:
    store = Store(path)
    entries = [UniverseEntry(t, f"R{t}USDT", f"{t}USDT", t, True) for t in ("TSLA", "NVDA", "AAPL")]
    return AnalysisContext(store=store, entries=entries, analog_config=AnalogConfig(k=30, min_matches=10, min_separation_h=36, min_age_h=96))


def test_pipeline_end_to_end_produces_verdict_and_serialises(seeded_store):
    ctx = _ctx(seeded_store)
    entry = float(ctx.store.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)["close"].iloc[-1])
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0, stop_price=entry * 0.96, thesis="t", invalidation="i")
    report = analyze(ctx, ticket, as_of=AS_OF)
    assert report.verdict.verdict in set(Verdict)
    assert report.analog is not None and report.analog.result.ok
    primary = report.primary_horizon
    assert primary in report.analog.horizons and report.analog.horizons[primary].hours == report.horizon_h or abs(report.analog.horizons[primary].hours - round(report.horizon_h)) < 1
    assert not report.analog.horizons[primary].cohort.insufficient
    assert report.execution.exit_quote is not None and report.execution.exit_quote.fully_filled
    assert report.execution.hedge_quote is not None
    assert len(report.stress.presets) >= 5 and report.stress.monte_carlo is not None
    assert report.gate.decision.value in ("GO", "REVIEW_REQUIRED", "NO_GO")
    assert any(c.name == "exit_liquidity" and c.notional for c in report.sizing.caps)
    # Serialisable and renderable.
    payload = json.dumps(report.to_dict(), default=str)
    assert '"verdict"' in payload
    text = render_text(report)
    assert "VERDICT:" in text and "ANALOGS:" in text and "STRESS" in text
    assert report.timings_ms["total"] < 60_000
    ctx.store.close()


def test_pipeline_is_point_in_time(seeded_store):
    """Two analyses at different as_of use different last bars and hashes."""
    ctx = _ctx(seeded_store)
    ticket = TradeTicket(ticker="NVDA", side=Side.SHORT, notional_quote=5_000.0, account_equity_quote=50_000.0, horizon_kind=HorizonKind.HOURS, horizon_hours=12, thesis="t", invalidation="i")
    a = analyze(ctx, ticket, as_of=AS_OF - timedelta(days=30))
    b = analyze(ctx, ticket, as_of=AS_OF - timedelta(days=29))
    assert a.snapshot.bar_ts < b.snapshot.bar_ts and a.snapshot.content_hash != b.snapshot.content_hash
    assert a.primary_horizon == "12h"
    assert "no order book available" in " ".join(a.warnings)  # book only exists for TSLA at AS_OF
    ctx.store.close()


def test_feature_frame_cache_is_bounded_and_lru(seeded_store):
    ctx = _ctx(seeded_store)
    ctx.frame_cache_size = 2
    t0 = AS_OF - timedelta(days=40)
    ctx.feature_frame("TSLA", t0)
    ctx.feature_frame("NVDA", t0)
    ctx.feature_frame("TSLA", t0)  # touch: TSLA becomes most recent
    ctx.feature_frame("AAPL", t0)  # evicts NVDA, the least recently used
    keys = [k.split("|")[0] for k in ctx._frames]
    assert keys == ["TSLA", "AAPL"]
    ctx.store.close()


def test_touching_the_frame_cache_reads_every_frame_and_changes_nothing(seeded_store):
    """The idle API re-reads its cached frames so the kernel keeps them in memory. It
    must visit every one, and it must not alter a value the search then reads."""
    ctx = _ctx(seeded_store)
    for t in ("TSLA", "NVDA"):
        ctx.feature_frame(t, AS_OF)
    import pandas as pd

    before = {k: v.copy() for k, v in ctx._frames.items()}
    assert ctx.touch_frames() == 2
    for k, v in ctx._frames.items():
        pd.testing.assert_frame_equal(v, before[k])


def test_a_build_with_sudden_new_gaps_is_rebuilt_then_flagged(seeded_store):
    """A frame missing a search feature for far more of the history than the build
    before it is rebuilt once; if the gaps persist the token is marked, and the report
    says so rather than answering quietly from a damaged history."""
    import numpy as np

    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side

    ctx = _ctx(seeded_store)
    good = ctx.feature_frame("TSLA", AS_OF)
    broken = good.copy()
    broken.loc[broken.index[: len(broken) // 2], "rv_24h"] = np.nan
    calls = []

    def rebuild_fixes():
        calls.append(1)
        return good

    assert ctx._checked("TSLA", AS_OF, broken, rebuild_fixes) is good and calls == [1]
    assert "TSLA" not in ctx._degraded

    assert ctx._checked("TSLA", AS_OF, broken, lambda: broken) is broken
    assert "rv_24h" in ctx._degraded["TSLA"]
    ctx._frames.clear()
    ctx._frames[f"TSLA|{AS_OF.replace(minute=0, second=0, microsecond=0).isoformat()}"] = broken
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=10_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.NEXT_OPEN, thesis="t", invalidation="i")
    warnings = analyze(ctx, ticket, as_of=AS_OF, record=False).warnings
    assert any("incomplete when this ran" in w and "rv_24h" in w for w in warnings)


def test_an_ordinary_new_build_is_not_mistaken_for_a_broken_one(seeded_store):
    ctx = _ctx(seeded_store)
    frame = ctx.feature_frame("TSLA", AS_OF)
    assert ctx._checked("TSLA", AS_OF, frame, lambda: frame) is frame and not ctx._degraded


def test_the_text_report_renders_when_book_and_tail_numbers_are_missing(seeded_store):
    """Live QA: a 5,000,000 USDT SMCI ticket returned a 500 because one recorded-book
    bucket had no spread or depth, and the text report formatted None as a number."""
    from dataclasses import replace

    from nightwatch.execution.liquidity_history import BucketLiquidity, LiquidityHistory

    ctx = _ctx(seeded_store)
    ticket = TradeTicket(ticker="TSLA", side=Side.SHORT, notional_quote=5_000_000.0, account_equity_quote=200_000.0, thesis="t", invalidation="i")
    report = analyze(ctx, ticket, as_of=AS_OF)
    empty = BucketLiquidity("weekend", 500, False, 40.0, None, None, None, None, None)
    object.__setattr__(report.execution, "liquidity_history", LiquidityHistory("RSMCIUSDT", AS_OF, AS_OF, 500, [empty]))
    for h in report.analog.horizons.values():
        object.__setattr__(h, "cohort", replace(h.cohort, es5_pct=None, mae_p5_pct=None))
    text = render_text(report)
    assert "spread   n/a bps" in text and "ES5 n/a%" in text
    ctx.store.close()


def _book(mid: float, half_spread: float, ts: datetime) -> OrderBookSnapshot:
    bids = tuple(OrderBookLevel(price=mid * (1 - half_spread - 0.0004 * i), size=30.0) for i in range(40))
    asks = tuple(OrderBookLevel(price=mid * (1 + half_spread + 0.0004 * i), size=30.0) for i in range(40))
    return OrderBookSnapshot(venue=Venue.BITGET_SPOT, symbol="RTSLAUSDT", ts=ts, observed_at=ts, bids=bids, asks=asks)


def test_one_wide_book_does_not_set_the_size_and_a_what_if_uses_its_own_moment(seeded_store, tmp_path):  # noqa: F811
    """Live: the same ticket read NO GO with "nothing to size" at a 37 bps exit and GO ten
    minutes later at 11 bps; and a what-if "against the same moment" read a newer book."""
    import shutil

    path = tmp_path / "copy.sqlite"
    shutil.copy(seeded_store, path)
    ctx = _ctx(path)
    mid = float(ctx.store.get_bars(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)["close"].iloc[-1])
    for m in range(110, 10, -10):  # two hours of an ordinary book, then one blown-out snapshot
        ctx.store.insert_orderbook(_book(mid, 0.0002, AS_OF - timedelta(minutes=m)))
    ctx.store.insert_orderbook(_book(mid, 0.004, AS_OF - timedelta(minutes=1)))
    ctx.store.insert_orderbook(_book(mid, 0.02, AS_OF + timedelta(minutes=5)))  # after the moment: must not be used
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0, thesis="t", invalidation="i")
    report = analyze(ctx, ticket, as_of=AS_OF, record=False)
    assert report.execution.book_ts == AS_OF - timedelta(minutes=1)  # the moment's book, not the later one
    assert report.execution.book_note and "unusually wide" in report.execution.book_note
    assert any("unusually wide" in w for w in report.warnings)
    assert report.execution.max_notional_within_budget and report.execution.max_notional_within_budget > 0
    ctx.store.close()


def test_a_longer_hold_is_never_shown_milder_than_a_shorter_one():
    """A re-test found a 5-hour hold at -4.5% beside a 173-hour hold at -4.4%."""
    from types import SimpleNamespace

    from nightwatch.pipeline.analyze import HorizonReport, _floor_longer_holds

    def h(name, hours, p5):  # noqa: ANN001, ANN202
        return HorizonReport(horizon=name, hours=hours, cohort=SimpleNamespace(insufficient=False, p5=p5), baseline=None, p5_adjusted=p5, adjustment={"k_lo": 1.0})

    hs = {"5h": h("5h", 5, -4.5), "24h": h("24h", 24, -3.0), "173h": h("173h", 173, -4.4), "240h": h("240h", 240, -6.0)}
    _floor_longer_holds(hs)
    assert hs["24h"].p5_adjusted == -4.5 and hs["24h"].adjustment["floored_by"] == "5h"
    assert hs["173h"].p5_adjusted == -4.5 and hs["240h"].p5_adjusted == -6.0 and "floored_by" not in hs["240h"].adjustment


def test_no_calibration_is_applied_past_the_longest_scored_hold(seeded_store):  # noqa: F811
    """The multi-day factor was fitted on weekends; applied to a trading week it shrank a
    -6.4% tail to -4.9% beside a base rate of 13% falling 5%."""
    from nightwatch.pipeline.analyze import CALIBRATED_MAX_H

    ctx = _ctx(seeded_store)
    ticket = TradeTicket(ticker="TSLA", side=Side.LONG, notional_quote=20_000.0, account_equity_quote=200_000.0,
                         horizon_kind=HorizonKind.HOURS, horizon_hours=170.0, thesis="t", invalidation="i")
    report = analyze(ctx, ticket, as_of=AS_OF, record=False)
    long_ = [h for h in report.analog.horizons.values() if h.hours > CALIBRATED_MAX_H]
    assert long_ and all((h.adjustment or {}).get("uncalibrated") for h in long_)
    ctx.store.close()


def test_a_short_is_sized_on_the_token_rising_not_falling(seeded_store):  # noqa: F811
    """A short loses when the token rises. Its one-in-twenty loss is the token's 95th
    percentile turned over; sizing it on the 5th - the short's gain - is what the desk
    used to do, and 'short it instead' came back with the long's loss unchanged."""
    ctx = _ctx(seeded_store)
    base = dict(ticker="TSLA", notional_quote=20_000.0, account_equity_quote=200_000.0, thesis="t", invalidation="i")
    long_ = analyze(ctx, TradeTicket(side=Side.LONG, **base), as_of=AS_OF, record=False)
    short = analyze(ctx, TradeTicket(side=Side.SHORT, **base), as_of=AS_OF, record=False)
    hl, hs = long_.analog.horizons[long_.primary_horizon], short.analog.horizons[short.primary_horizon]
    assert hl.loss_p5_pct == (hl.p5_adjusted if hl.p5_adjusted is not None else hl.cohort.p5)
    up = hs.p95_adjusted if hs.p95_adjusted is not None else hs.cohort.p95
    assert hs.loss_p5_pct == -up and hs.loss_p5_pct < 0
    assert hs.pnl_median_pct == -hs.cohort.median_pct


def test_the_upper_tail_is_floored_for_longer_holds_too():
    from types import SimpleNamespace

    from nightwatch.pipeline.analyze import HorizonReport, _floor_longer_holds

    def h(name, hours, p95):  # noqa: ANN001, ANN202
        return HorizonReport(horizon=name, hours=hours, cohort=SimpleNamespace(insufficient=False, p5=-1.0, p95=p95), baseline=None,
                             p5_adjusted=-1.0, p95_adjusted=p95, adjustment={})

    hs = {"5h": h("5h", 5, 4.5), "24h": h("24h", 24, 3.0), "72h": h("72h", 72, 6.0)}
    _floor_longer_holds(hs)
    assert hs["24h"].p95_adjusted == 4.5 and hs["24h"].adjustment["floored_up_by"] == "5h" and hs["72h"].p95_adjusted == 6.0


def test_a_narrowing_the_desk_chose_never_makes_the_loss_line_milder():
    """The narrowing evidence does not survive the multiple-testing correction, so an
    automatic narrowing may only make the answer more cautious."""
    from types import SimpleNamespace

    from nightwatch.pipeline.analyze import HorizonReport, _cautious_of

    def h(loss):  # noqa: ANN001, ANN202
        return HorizonReport(horizon="x", hours=12, cohort=SimpleNamespace(insufficient=False), baseline=None, loss_p5_pct=loss)

    narrowed = SimpleNamespace(horizons={"12h": h(-2.0), "24h": h(-5.0), "72h": h(None)})
    plain = SimpleNamespace(horizons={"12h": h(-3.0), "24h": h(-4.0), "72h": h(-6.0)})
    used = _cautious_of(narrowed, plain)
    assert narrowed.horizons["12h"].loss_p5_pct == -3.0 and narrowed.horizons["24h"].loss_p5_pct == -5.0
    assert narrowed.horizons["72h"].loss_p5_pct == -6.0 and used == ["12h", "72h"]
    assert narrowed.horizons["12h"].adjustment["cautious_of_two"] == "unfiltered"
