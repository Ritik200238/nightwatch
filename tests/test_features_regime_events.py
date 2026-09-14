from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nightwatch.data.models import EarningsEvent, MacroRelease, NewsItem
from nightwatch.data.store import Store
from nightwatch.features.events import add_event_columns, earnings_instant
from nightwatch.features.regime import add_regime_columns
from nightwatch.features.snapshot import FEATURE_COLUMNS, InsufficientData, build_snapshot
from nightwatch.time_utils import ET
from tests.test_features_series import END, SPEC, START, seed

UTC = UTC


def synthetic_frame(hours: int, *, vol_late: bool = False, seed_: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed_)
    idx = pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=hours, freq="1h", tz="UTC", name="ts")
    sigma = np.full(hours, 0.002)
    if vol_late:
        sigma[-48:] = 0.02
    rets = rng.normal(0, sigma)
    close = 100 * np.exp(np.cumsum(rets))
    f = pd.DataFrame(index=idx)
    f["spot_close"] = close
    f["spot_filled"] = False
    f["spot_vol_quote"] = 1000.0
    return f


def test_regime_flags_turbulence_and_states():
    f = add_regime_columns(synthetic_frame(24 * 120, vol_late=True))
    last = f.iloc[-1]
    assert last["vol_state"] == "turbulent" and last["vol_pctl_90d"] > 90
    assert last["risk_multiplier"] <= 0.5
    earlier = f.iloc[-100]
    assert earlier["vol_state"] in ("calm", "normal")
    assert set(f["trend_state"].unique()) <= {"unknown", "up", "down", "sideways"}


def test_regime_liquidity_thinning_from_no_trade_share():
    f = synthetic_frame(24 * 60)
    f.loc[f.index[-24:], "spot_filled"] = True  # last day: no trades at all
    f.loc[f.index[-24:], "spot_vol_quote"] = 0.0
    f = add_regime_columns(f)
    assert f.iloc[-1]["liq_state"] == "thinning"
    assert f.iloc[-1]["no_trade_share_24h"] == 1.0


def test_weekend_that_is_normal_for_a_weekend_is_not_thinning():
    """A tokenized stock trades every hour, but not equally. Eight quiet weekends in a
    row make the ninth ordinary, not a liquidity crisis."""
    f = synthetic_frame(24 * 74)  # ends on a Sunday
    weekend = f.index.dayofweek >= 5
    f.loc[weekend, "spot_vol_quote"] = 100.0  # a tenth of a weekday hour, every weekend
    f = add_regime_columns(f)
    last = f.iloc[-1]
    assert f.index[-1].dayofweek >= 5  # the frame ends on a weekend
    assert last["liq_state"] == "normal"
    assert 0.8 < last["liq_ratio"] < 1.25
    # The same data against a flat all-hours baseline would have called it thin.
    flat = f["spot_vol_quote"].rolling(24, min_periods=24).sum() / (f["spot_vol_quote"].rolling(720, min_periods=360).mean().shift(24) * 24)
    assert flat.iloc[-1] < 0.7


def test_liquidity_thinning_when_a_weekend_is_quiet_for_a_weekend():
    f = synthetic_frame(24 * 74)  # ends on a Sunday
    weekend = f.index.dayofweek >= 5
    f.loc[weekend, "spot_vol_quote"] = 100.0
    f.loc[f.index[-24:], "spot_vol_quote"] = 20.0  # this weekend is a fifth of a normal one
    f = add_regime_columns(f)
    assert f.iloc[-1]["liq_state"] == "thinning"


def test_seasonal_norm_is_trailing_and_excludes_the_present():
    from nightwatch.features.regime import _seasonal_norm

    idx = pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=24 * 42, freq="1h", tz="UTC")
    v = pd.Series(range(len(idx)), index=idx, dtype=float)
    norm = _seasonal_norm(v, 4)
    # The value at t is the median of the same hour of week in the four weeks before it.
    ts_pos = len(idx) - 1
    same_hour = [ts_pos - 168 * k for k in (1, 2, 3, 4)]
    assert norm.iloc[ts_pos] == np.median([v.iloc[i] for i in same_hour])
    assert np.isnan(norm.iloc[:168]).all()  # nothing to compare the first week against


def test_regime_uses_only_trailing_windows():
    base = synthetic_frame(24 * 100)
    f_all = add_regime_columns(base)
    f_cut = add_regime_columns(base.iloc[: 24 * 80])
    # Values at the cut point must be identical: nothing after it may influence them.
    ts = base.index[24 * 80 - 1]
    for col in ("rv_24h", "vol_pctl_90d", "trend_sma_pct", "liq_ratio"):
        a, b = f_all.loc[ts, col], f_cut.loc[ts, col]
        assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-12


def test_earnings_instants_and_event_columns(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        report = datetime(2026, 9, 10, tzinfo=ET)  # Thursday, after close
        s.upsert_earnings([EarningsEvent(ticker="TSLA", report_date=report.astimezone(UTC), timing="amc", source="nasdaq_calendar", observed_at=START)])
        s.upsert_macro([MacroRelease(series_id="FOMC", name="FOMC", release_ts=datetime(2026, 9, 16, 14, tzinfo=ET).astimezone(UTC), source="fed", observed_at=START)])
        s.upsert_news([NewsItem(source="t", id="1", published_at=START + timedelta(hours=30), title="Tesla news", tickers=("TSLA",), observed_at=START + timedelta(hours=30))])
        idx = pd.date_range(START, END, freq="1h", tz="UTC", inclusive="left", name="ts")
        f = add_event_columns(pd.DataFrame(index=idx), s, "TSLA")
    inst = earnings_instant(EarningsEvent(ticker="TSLA", report_date=report.astimezone(UTC), timing="amc", source="x", observed_at=START))
    assert inst.astimezone(ET).hour == 16 and inst.astimezone(ET).minute == 30
    before = START + timedelta(hours=10)
    assert abs(f.loc[before, "hours_to_earnings"] - (inst - before).total_seconds() / 3600) < 1e-9
    after = START + timedelta(days=3)
    assert np.isnan(f.loc[after, "hours_to_earnings"]) and f.loc[after, "hours_since_earnings"] > 0
    assert f.loc[before, "earnings_within_72h"] == 1.0
    assert f["hours_to_fomc"].notna().all() and f["hours_to_fomc"].iloc[0] > f["hours_to_fomc"].iloc[-1]
    assert f.loc[START + timedelta(hours=30), "news_count_24h"] == 1.0
    assert f.loc[START + timedelta(hours=60), "news_count_24h"] == 0.0


def test_snapshot_is_point_in_time_and_hashed(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        as_of = START + timedelta(days=2, hours=12, minutes=20)
        snap = build_snapshot(s, SPEC, as_of)
        assert snap.bar_ts == START + timedelta(days=2, hours=11)  # last *completed* bar
        assert set(snap.features) == set(FEATURE_COLUMNS)
        assert snap.prices["spot_close"] == 100.0 + 0.01 * (2 * 24 + 11)
        assert "vol_percentile_needs_more_history" in snap.quality_flags  # only 4 days seeded
        assert len(snap.content_hash) == 16
        again = build_snapshot(s, SPEC, as_of + timedelta(minutes=5))
        assert again.content_hash == snap.content_hash  # same last bar -> same inputs


def test_snapshot_refuses_stale_data(tmp_path):
    with Store(tmp_path / "t.sqlite") as s:
        seed(s)
        try:
            build_snapshot(s, SPEC, END + timedelta(days=2))
        except InsufficientData:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected InsufficientData for stale bars")


def test_filing_columns_are_point_in_time(tmp_path):
    from nightwatch.data.models import Filing
    from nightwatch.data.store import Store
    from nightwatch.features.events import add_event_columns

    store = Store(tmp_path / "f.sqlite")
    idx = pd.date_range("2026-03-02", periods=24 * 5, freq="h", tz="UTC")
    seen = datetime(2026, 3, 3, 12, tzinfo=UTC)
    store.upsert_filings([
        Filing(ticker="TSLA", cik="1", form="8-K", accepted_at=datetime(2026, 3, 2, 21, 5, tzinfo=UTC), filed_date=datetime(2026, 3, 2, tzinfo=UTC), accession="a1", observed_at=seen),
        Filing(ticker="TSLA", cik="1", form="10-Q", accepted_at=datetime(2026, 3, 4, 21, 5, tzinfo=UTC), filed_date=datetime(2026, 3, 4, tzinfo=UTC), accession="a2", observed_at=seen + timedelta(days=2)),
    ])
    f = add_event_columns(pd.DataFrame(index=idx), store, "TSLA")
    assert np.isnan(f.loc["2026-03-02 20:00", "hours_since_filing"])
    assert f.loc["2026-03-02 22:00", "hours_since_filing"] == pytest.approx(55 / 60)
    assert f.loc["2026-03-04 22:00", "filings_72h"] == 2.0  # the 8-K is 49h old, still inside the window
    assert f.loc["2026-03-05 22:00", "filings_72h"] == 1.0  # now it has aged out
    # As of before the second filing was observed, it does not exist yet.
    g = add_event_columns(pd.DataFrame(index=idx), store, "TSLA", as_of=seen)
    assert g.loc["2026-03-04 22:00", "hours_since_filing"] == pytest.approx(48 + 55 / 60)
    assert g["filings_72h"].max() == 1.0
    store.close()
