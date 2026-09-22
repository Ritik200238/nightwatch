"""Universe resolution, backfill/refresh planning and the recorder loop, with fakes."""

from datetime import UTC, datetime, timedelta

from nightwatch.data.models import (
    Bar,
    Instrument,
    InstrumentType,
    Interval,
    OrderBookLevel,
    OrderBookSnapshot,
    PriceKind,
    Ticker,
    Venue,
)
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry, backfill_bars, build_universe, refresh_bars
from nightwatch.recorder.orderbook_recorder import OrderBookRecorder

UTC = UTC
T0 = datetime(2026, 8, 1, tzinfo=UTC)


def ins(venue, symbol, base, *, tokenized, status="online", underlying=None):
    return Instrument(venue=venue, symbol=symbol, type=InstrumentType.SPOT if venue == Venue.BITGET_SPOT else InstrumentType.PERP,
                      base=base, quote="USDT", underlying_ticker=underlying, is_tokenized_stock=tokenized, status=status, observed_at=T0)


def test_build_universe_cross_references_perps_and_orders_core_first():
    spot = [
        ins(Venue.BITGET_SPOT, "RTSLAUSDT", "rTSLA", tokenized=True, underlying="TSLA"),
        ins(Venue.BITGET_SPOT, "RAAPLUSDT", "rAAPL", tokenized=True, underlying="AAPL"),
        ins(Venue.BITGET_SPOT, "RBRKBUSDT", "rBRKB", tokenized=True, underlying="BRKB"),
        ins(Venue.BITGET_SPOT, "RDEADUSDT", "rDEAD", tokenized=True, underlying="DEAD", status="offline"),
        ins(Venue.BITGET_SPOT, "BTCUSDT", "BTC", tokenized=False),
    ]
    perp = [
        ins(Venue.BITGET_UMCBL, "TSLAUSDT", "TSLA", tokenized=True, underlying="TSLA", status="normal"),
        ins(Venue.BITGET_UMCBL, "XAUUSDT", "XAU", tokenized=True, underlying="XAU", status="normal"),  # isRwa but not a stock
        ins(Venue.BITGET_UMCBL, "AAPLUSDT", "AAPL", tokenized=True, underlying="AAPL", status="maintain"),
    ]
    u = build_universe(spot, perp, core=["aapl"])
    assert [e.ticker for e in u] == ["AAPL", "BRKB", "TSLA"]
    by = {e.ticker: e for e in u}
    assert by["TSLA"].perp_symbol == "TSLAUSDT"
    assert by["AAPL"].perp_symbol is None and by["AAPL"].is_core  # perp not tradeable -> excluded
    assert by["BRKB"].yahoo_ticker == "BRK-B"


class FakeBitget:
    """Serves hourly bars from an in-memory 24/7 series and counts calls."""

    def __init__(self, venue: Venue, first: datetime, last: datetime):
        self.venue = venue
        self.first, self.last = first, last
        self.calls: list[tuple[datetime, datetime]] = []
        self.recent_calls = 0

    def get_bars(self, symbol, interval, start, end, *, kind=PriceKind.TRADE):
        self.calls.append((start, end))
        out = []
        t = max(start, self.first)
        while t < min(end, self.last + timedelta(hours=1)):
            out.append(Bar(venue=self.venue, symbol=symbol, interval=interval, kind=kind, ts=t, open=1, high=1, low=1, close=1, observed_at=T0))
            t += timedelta(hours=1)
        return out

    def get_recent_bars(self, symbol, interval, limit=1000, *, kind=PriceKind.TRADE):
        self.recent_calls += 1
        end = self.last + timedelta(hours=1)
        return self.get_bars(symbol, interval, end - timedelta(hours=limit), end, kind=kind)


def test_backfill_only_fetches_missing_ranges(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        fake = FakeBitget(Venue.BITGET_SPOT, T0, T0 + timedelta(days=9, hours=23))
        n1 = backfill_bars(s, fake, "RTSLAUSDT", Interval.H1, start=T0 + timedelta(days=3), end=T0 + timedelta(days=6), chunk=timedelta(days=2))
        assert n1 == 72 and len(fake.calls) == 2  # 3 days in 2-day chunks
        # Extend both sides: only [0,3) and [6,10) should be requested.
        fake.calls.clear()
        n2 = backfill_bars(s, fake, "RTSLAUSDT", Interval.H1, start=T0, end=T0 + timedelta(days=10), chunk=timedelta(days=10))
        assert n2 == 72 + 96
        assert fake.calls == [
            (T0 + timedelta(days=6), T0 + timedelta(days=10)),
            (T0, T0 + timedelta(days=3)),
        ] or sorted(fake.calls) == sorted([(T0, T0 + timedelta(days=3)), (T0 + timedelta(days=6), T0 + timedelta(days=10))])
        assert s.bar_coverage(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)[2] == 240
        # Nothing missing now -> no calls.
        fake.calls.clear()
        assert backfill_bars(s, fake, "RTSLAUSDT", Interval.H1, start=T0, end=T0 + timedelta(days=10)) == 0
        assert fake.calls == []


def test_refresh_uses_recent_endpoint_for_small_deltas(tmp_path, monkeypatch):
    import nightwatch.data.sync as sync_mod

    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    monkeypatch.setattr(sync_mod, "utc_now", lambda: now)
    with Store(tmp_path / "t.sqlite") as s:
        fake = FakeBitget(Venue.BITGET_SPOT, T0, now - timedelta(hours=1))
        backfill_bars(s, fake, "RTSLAUSDT", Interval.H1, start=T0, end=now - timedelta(hours=30))
        added = refresh_bars(s, fake, "RTSLAUSDT", Interval.H1)
        assert added > 0 and fake.recent_calls == 1
        cov = s.bar_coverage(Venue.BITGET_SPOT, "RTSLAUSDT", Interval.H1)
        assert cov[1] == now - timedelta(hours=1)


class FakeBookClient:
    def __init__(self, venue):
        self.venue = venue
        self.fail_symbols = set()

    def get_orderbook(self, symbol, depth=150):
        if symbol in self.fail_symbols:
            raise RuntimeError("boom")
        return OrderBookSnapshot(venue=self.venue, symbol=symbol, ts=T0, observed_at=T0,
                                 bids=(OrderBookLevel(price=99, size=1),), asks=(OrderBookLevel(price=101, size=1),))

    def list_tickers(self):
        return [Ticker(venue=self.venue, symbol="RTSLAUSDT" if self.venue == Venue.BITGET_SPOT else "TSLAUSDT", ts=T0, last=100, bid=99, ask=101, observed_at=T0),
                Ticker(venue=self.venue, symbol="OTHER", ts=T0, last=1, bid=1, ask=1, observed_at=T0)]


def test_recorder_tick_records_books_and_tickers_and_survives_errors(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        spot, perp = FakeBookClient(Venue.BITGET_SPOT), FakeBookClient(Venue.BITGET_UMCBL)
        perp.fail_symbols.add("TSLAUSDT")
        entries = [UniverseEntry("TSLA", "RTSLAUSDT", "TSLAUSDT", "TSLA", True)]
        rec = OrderBookRecorder(s, spot=spot, perp=perp, entries=entries, interval_sec=5, refresh_bars_every_sec=None)
        rec.tick()
        assert rec.stats.snapshots == 1 and rec.stats.errors == 1
        assert rec.stats.ticker_rows == 2  # only wanted symbols, one per venue
        assert s.latest_orderbook(Venue.BITGET_SPOT, "RTSLAUSDT") is not None


def test_recorder_runs_periodic_jobs_on_their_own_cadence_and_isolates_failures(tmp_path):
    from nightwatch.recorder.orderbook_recorder import PeriodicJob

    with Store(tmp_path / "t.sqlite") as s:
        spot, perp = FakeBookClient(Venue.BITGET_SPOT), FakeBookClient(Venue.BITGET_UMCBL)
        entries = [UniverseEntry("TSLA", "RTSLAUSDT", "TSLAUSDT", "TSLA", True)]
        calls = {"a": 0, "b": 0}

        def a():
            calls["a"] += 1
            return calls["a"]

        def b():
            calls["b"] += 1
            raise RuntimeError("feed down")

        jobs = [PeriodicJob("a", 3600, a), PeriodicJob("b", 3600, b), PeriodicJob("later", 3600, a, run_at_start=False)]
        rec = OrderBookRecorder(s, spot=spot, perp=perp, entries=entries, interval_sec=5, refresh_bars_every_sec=None, jobs=jobs)
        rec.tick()
        rec.tick()  # same hour: nothing re-runs
        assert calls == {"a": 1, "b": 1}
        assert jobs[1].failures == 1 and rec.stats.errors == 1
        assert jobs[2].runs == 0  # deferred job waits a full period
        jobs[0].last_run -= 3601
        jobs[2].last_run -= 3601
        rec.tick()
        assert calls["a"] == 3 and jobs[2].runs == 1


# --------------------------------------------------- deferred jobs across a restart


def test_a_deferred_job_that_is_overdue_on_disk_runs_at_once():
    """A four-hourly job measuring its wait from process start gets another four hours
    of silence on every deploy. On a box that redeploys per commit that is how a feed
    goes days stale while every health check stays green."""
    from nightwatch.recorder.orderbook_recorder import PeriodicJob

    overdue = PeriodicJob("filings", 4 * 3600, lambda: None, run_at_start=False, age_at_start=9 * 3600)
    assert overdue.due(50_000.0) is True


def test_a_deferred_job_part_way_through_its_period_waits_out_the_remainder():
    from nightwatch.recorder.orderbook_recorder import PeriodicJob

    j = PeriodicJob("filings", 4 * 3600, lambda: None, run_at_start=False, age_at_start=3600)
    now = 50_000.0
    assert j.due(now) is False
    # It has one hour of credit, so it is due three hours from now, not four.
    assert j.due(now + 3 * 3600 - 5) is False
    assert j.due(now + 3 * 3600 + 5) is True


def test_a_deferred_job_with_no_history_still_waits_a_full_period():
    """First ever start: nothing on disk, so the old behaviour is the right one."""
    from nightwatch.recorder.orderbook_recorder import PeriodicJob

    j = PeriodicJob("filings", 4 * 3600, lambda: None, run_at_start=False, age_at_start=None)
    now = 50_000.0
    assert j.due(now) is False
    assert j.due(now + 4 * 3600 - 5) is False
    assert j.due(now + 4 * 3600 + 5) is True


def test_a_run_at_start_job_is_unaffected():
    """`now` is a monotonic clock, already large when the recorder starts."""
    from nightwatch.recorder.orderbook_recorder import PeriodicJob

    assert PeriodicJob("mature", 900, lambda: None).due(50_000.0) is True
