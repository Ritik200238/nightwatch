from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from nightwatch.data.models import Bar, Interval, Venue
from nightwatch.data.store import Store
from nightwatch.journal.calibration import (
    calibrate,
    independence_test,
    proportion_of_failures,
    render_calibration,
    tail_test,
    wilson_interval,
)
from nightwatch.journal.journal import Journal

UTC = timezone.utc
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def test_wilson_interval_brackets_known_case():
    lo, hi = wilson_interval(5, 100)
    assert 0.02 < lo < 0.05 < hi < 0.12


def test_pof_test_zero_and_matching_rates():
    # Exactly 5 breaches in 100 at 5% expected: statistic ~0, p ~1.
    b = np.zeros(100, dtype=int)
    b[:5] = 1
    stat, p = proportion_of_failures(b, 0.05)
    assert abs(stat) < 1e-9 and p > 0.99
    # 20 breaches in 100 is a clear rejection.
    b[:20] = 1
    stat, p = proportion_of_failures(b, 0.05)
    assert stat > 20 and p < 1e-4
    # Zero breaches: closed-form branch.
    stat0, p0 = proportion_of_failures(np.zeros(100, dtype=int), 0.05)
    assert stat0 > 0 and 0 < p0 < 1


def test_independence_test_detects_clustering():
    rng = np.random.default_rng(7)
    independent = (rng.random(400) < 0.05).astype(int)  # Bernoulli breaches
    clustered = np.zeros(400, dtype=int)
    clustered[:20] = 1  # all breaches in one run
    s1, p1 = independence_test(independent)
    s2, p2 = independence_test(clustered)
    assert p1 > 0.05 and p2 < 0.01 and s2 > s1
    # Hand-checked case: transitions 00=189, 01=0, 10=1, 11=9 (first 10 of 200 are breaches).
    small = np.zeros(200, dtype=int)
    small[:10] = 1
    s3, _ = independence_test(small)
    assert abs(s3 - 66.8) < 1.0


def test_tail_test_bands():
    rng = np.random.default_rng(3)
    realised = rng.normal(0, 1, 400)
    good_p5 = np.full(400, np.percentile(realised, 5))
    t = tail_test(realised, good_p5)
    assert t.band == "green" and t.pof_p_value > 0.05
    narrow_p5 = np.full(400, np.percentile(realised, 20))  # forecasts too narrow: breaches 4x expected
    t2 = tail_test(realised, narrow_p5)
    assert t2.band == "red" and t2.pof_p_value < 1e-6
    assert tail_test(realised[:10], good_p5[:10]).band == "insufficient"


def _seed_bars(store: Store, symbol: str, hours: int, price_fn):
    store.upsert_bars([
        Bar(venue=Venue.BITGET_SPOT, symbol=symbol, interval=Interval.H1, ts=T0 + timedelta(hours=i), open=price_fn(i), high=price_fn(i) * 1.01, low=price_fn(i) * 0.99, close=price_fn(i), observed_at=T0)
        for i in range(hours)
    ])


def test_journal_records_matures_and_calibrates(tmp_path):
    with Store(tmp_path / "j.sqlite") as s:
        _seed_bars(s, "RTSLAUSDT", 200, lambda i: 100.0 + i * 0.1)  # +0.1/h drift
        j = Journal(s)
        ids = []
        rng = np.random.default_rng(0)
        for k in range(60):
            as_of = T0 + timedelta(hours=2 * k)
            entry = 100.0 + 2 * k * 0.1
            # Forecast quantiles around the true +2.4% 24h drift with noise.
            base = 2.4 + rng.normal(0, 0.3)
            q = {"p5": base - 2.0, "p25": base - 0.8, "p50": base, "p75": base + 0.8, "p95": base + 2.0}
            ids.append(j.record_forecast(kind="replay", ticker="TSLA", side="long", notional=1000, as_of=as_of, bar_ts=as_of - timedelta(hours=1), horizon_h=24, entry_price=entry,
                                         snapshot_hash="h", analog_n=40, analog_scope="same_ticker", quantiles=q, es5=None, mc_p5=None, mc_p95=None, verdict="GO", recommended_notional=1000, payload={}))
        # Nothing matured before horizons pass.
        assert j.mature(spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0) == 0
        n = j.mature(spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0 + timedelta(hours=400))
        assert n == 60
        df = j.forecasts(matured_only=True)
        assert len(df) == 60 and df["ret_pct"].notna().all()
        # Realised 24h drift is ~2.4%, so the forecasts are well calibrated.
        rep = calibrate(df)
        assert rep.n_matured == 60
        assert rep.tail.band in ("green", "amber")
        assert rep.mean_width_p5_p95 is not None and abs(rep.mean_width_p5_p95 - 4.0) < 0.5
        text = render_calibration(rep)
        assert "CALIBRATION" in text and "5% tail" in text
        # Re-maturing is idempotent.
        assert j.mature(spot_symbol_for={"TSLA": "RTSLAUSDT"}, now=T0 + timedelta(hours=400)) == 0


def test_trade_log_and_revenge_lookup(tmp_path):
    with Store(tmp_path / "j.sqlite") as s:
        j = Journal(s)
        tid = j.log_trade(forecast_id=None, ticker="TSLA", side="long", opened_at=T0, notional=1000, entry_price=100.0)
        j.close_trade(tid, closed_at=T0 + timedelta(hours=5), exit_price=97.0)
        losses = j.recent_losing_exits(since=T0)
        assert losses == (T0 + timedelta(hours=5),)
        tid2 = j.log_trade(forecast_id=None, ticker="TSLA", side="short", opened_at=T0, notional=1000, entry_price=100.0)
        j.close_trade(tid2, closed_at=T0 + timedelta(hours=6), exit_price=97.0)  # short profits
        assert j.recent_losing_exits(since=T0) == (T0 + timedelta(hours=5),)
