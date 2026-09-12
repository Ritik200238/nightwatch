"""End-to-end pipeline on synthetic data: no network, deterministic."""

import json
from datetime import datetime, timedelta, timezone

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

UTC = timezone.utc
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
