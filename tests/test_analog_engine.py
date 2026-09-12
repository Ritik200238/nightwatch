from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from nightwatch.analog.engine import AnalogConfig, AnalogEngine, matches_frame, pooled_history

UTC = timezone.utc
FEATS = ("a", "b", "c", "d")


def history(n_hours: int = 24 * 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(datetime(2025, 1, 1, tzinfo=UTC), periods=n_hours, freq="1h", tz="UTC", name="ts")
    a = rng.normal(0, 1, n_hours)
    b = a * 0.9 + rng.normal(0, 0.3, n_hours)  # strongly correlated with a
    c = rng.normal(5, 2, n_hours)
    d = rng.normal(0, 1, n_hours)
    f = pd.DataFrame({"a": a, "b": b, "c": c, "d": d}, index=idx)
    f["bucket"] = np.where(idx.dayofweek >= 5, "weekend", "weekday")
    return f


def cfg(**kw) -> AnalogConfig:
    base = dict(features=FEATS, k=10, min_matches=5, min_separation_h=36, min_age_h=96, whiten=True)
    base.update(kw)
    return AnalogConfig(**base)


def test_finds_planted_episodes_and_dedupes_neighbouring_hours():
    h = history()
    # Plant three distinct episodes (each 3 hours long) that exactly match the query.
    q = {"a": 3.0, "b": 2.7, "c": 12.0, "d": -2.5}
    planted = [h.index[1000], h.index[3000], h.index[4000]]
    for t in planted:
        for k in range(3):
            h.loc[t + pd.Timedelta(hours=k), list(FEATS)] = [q[f] for f in FEATS]
    res = AnalogEngine(cfg()).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert res.ok
    top3 = {m.ts for m in res.matches[:3]}
    # Each planted episode appears once (its neighbours are suppressed by min_separation).
    assert len(top3) == 3
    for t in planted:
        assert any(abs((m - t.to_pydatetime()).total_seconds()) <= 2 * 3600 for m in top3)
    assert res.matches[0].distance < res.matches[3].distance
    assert 0 < res.matches[0].similarity <= 1.0
    assert res.matches[0].distance_percentile < 1.0
    assert res.n_candidates < res.n_history_rows  # min_age cut applied


def test_min_age_excludes_recent_rows():
    h = history(24 * 30)
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    query_ts = h.index[-1] + timedelta(hours=1)
    res = AnalogEngine(cfg(min_age_h=120)).search(h, q, query_ts=query_ts)
    assert res.ok
    assert all(m.ts <= query_ts - timedelta(hours=120) for m in res.matches)


def test_refuses_when_too_few_candidates():
    h = history(24 * 5)
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    res = AnalogEngine(cfg(min_matches=50, min_age_h=0)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert not res.ok and "distinct episodes" in res.reason or "candidate rows" in res.reason
    assert res.matches == []


def test_missing_query_features_are_dropped_and_reported():
    h = history(24 * 60)
    q = {"a": 0.5, "b": None, "c": float("nan"), "d": 0.1}
    res = AnalogEngine(cfg(min_matches=3)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert res.features_used == ("a", "d") and set(res.features_dropped) == {"b", "c"}


def test_constant_history_feature_is_dropped_not_exploded():
    h = history(24 * 60)
    h["d"] = 0.0  # constant in history
    q = {"a": 0.5, "b": 0.4, "c": 5.0, "d": 1.0}
    res = AnalogEngine(cfg(min_matches=3)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert res.ok and res.features_used == ("a", "b", "c")
    assert any("d (constant" in x for x in res.features_dropped)
    assert all(np.isfinite(m.distance) and m.distance < 1e3 for m in res.matches)


def test_refuses_with_fewer_than_three_features():
    h = history(24 * 60)
    res = AnalogEngine(cfg()).search(h, {"a": 0.5, "d": 0.1}, query_ts=h.index[-1] + timedelta(hours=1))
    assert not res.ok and "usable features" in res.reason


def test_same_bucket_filter():
    h = history()
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    res = AnalogEngine(cfg(same_bucket=True)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1), query_bucket="weekend")
    assert res.ok and all(m.bucket == "weekend" for m in res.matches)


def test_whitening_discounts_redundant_feature():
    """a and b carry nearly the same information; with whitening, moving both together
    should not count twice compared to moving an independent feature by the same z."""
    h = history(24 * 300, seed=3)
    base = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    eng = AnalogEngine(cfg(k=5, min_matches=3))
    ts = h.index[-1] + timedelta(hours=1)
    d_corr = eng.search(h, {**base, "a": 2.0, "b": 1.8}, query_ts=ts).matches[0].distance
    d_indep = eng.search(h, {**base, "c": 5 + 2 * 2.0, "d": 2.0}, query_ts=ts).matches[0].distance
    # Two independent 2σ moves are "farther" from the cloud than two correlated 2σ moves.
    assert d_indep > d_corr


def test_pooled_history_and_same_ticker_filter():
    h1, h2 = history(24 * 60, seed=1), history(24 * 60, seed=2)
    pooled = pooled_history([("TSLA", h1), ("NVDA", h2)])
    assert set(pooled["ticker"]) == {"TSLA", "NVDA"} and len(pooled) == len(h1) + len(h2)
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    res = AnalogEngine(cfg(same_ticker=True)).search(pooled, q, query_ts=pooled.index[-1] + timedelta(hours=1), query_ticker="NVDA")
    assert res.ok and all(m.ticker == "NVDA" for m in res.matches)
    df = matches_frame(res)
    assert list(df.columns[:5]) == ["ticker", "bucket", "distance", "similarity", "distance_pct"]
