from collections import Counter
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.analog.engine import AnalogConfig, AnalogEngine, matches_frame, pooled_history

UTC = UTC
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
    assert 0.5 < res.matches[0].similarity <= 1.0  # an exact planted match must score high
    assert res.matches[0].similarity >= res.matches[-1].similarity
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


def test_each_match_says_what_it_shares_with_now_and_where_it_does_not():
    """A reader should be able to argue with a match: its closest features and the ones
    more than one robust standard deviation away are named, from the search's own scaling."""
    h = history()
    now = h.index[-1] + timedelta(hours=200)
    res = AnalogEngine(cfg()).search(h, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}, query_ts=now)
    assert res.ok
    for m in res.matches:
        assert len(m.alike_on) == 3 and set(m.alike_on) <= set(FEATS)
        assert not set(m.alike_on) & set(m.differs_on)
    # A query far out on one feature: every match must differ on it.
    far = AnalogEngine(cfg()).search(h, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 25.0}, query_ts=now)
    assert far.ok and all("d" in m.differs_on for m in far.matches)


def test_a_value_most_of_history_shares_is_not_offered_as_the_resemblance():
    """ "Alike on time to earnings" named a value capped at 30 days that almost every hour has."""
    h = history()
    h["cap"] = 720.0
    h.loc[h.index[::5], "cap"] = np.linspace(1, 700, len(h.index[::5]))  # a fifth of hours differ
    now = h.index[-1] + timedelta(hours=200)
    res = AnalogEngine(cfg(features=("a", "b", "c", "cap"))).search(h, {"a": 0.0, "b": 0.0, "c": 5.0, "cap": 720.0}, query_ts=now)
    assert res.ok and all("cap" not in m.alike_on for m in res.matches)


def test_a_slow_macro_field_is_not_offered_as_the_resemblance():
    """VIX percentile and the like are identical for any two hours of one fortnight, so
    "alike on VIX" says when a match happened, not why it resembles now."""
    h = history()
    wk = h.index.isocalendar().week.to_numpy() + 53 * (h.index.year.to_numpy() - 2025)
    h["vix"] = pd.Series(wk).map(dict(zip(np.unique(wk), np.random.default_rng(3).normal(50, 20, len(np.unique(wk))), strict=True))).to_numpy()  # moves weekly
    now = h.index[-1] + timedelta(hours=200)
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "vix": float(h["vix"].iloc[100])}
    res = AnalogEngine(cfg(features=("a", "b", "c", "vix"))).search(h, q, query_ts=now)
    assert res.ok and res.broad_features == ("vix",)
    assert all("vix" not in m.alike_on for m in res.matches)
    assert all(len(m.alike_on) == 3 for m in res.matches)


def test_matches_are_separate_episodes_and_no_week_is_most_of_the_sample():
    """A burst of look-alike hours in one week counts once or a few times, never forty."""
    h = history()
    q = {"a": 3.0, "b": 2.7, "c": 12.0, "d": -2.5}
    burst = h.index[2000]  # plant an exact match every 6 hours for a week
    for k in range(0, 168, 6):
        h.loc[burst + pd.Timedelta(hours=k), list(FEATS)] = [q[f] for f in FEATS]
    res = AnalogEngine(cfg(k=30)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert res.ok
    ts = sorted(m.ts for m in res.matches)
    assert all((b - a).total_seconds() >= 36 * 3600 for a, b in zip(ts, ts[1:], strict=False))  # the final cohort, not a draft
    weeks = Counter(pd.Timestamp(t).isocalendar()[:2] for t in ts)
    assert max(weeks.values()) <= 3
    assert res.n_weeks == len(weeks)
    loose = AnalogEngine(cfg(k=30, max_per_week=0)).search(h, q, query_ts=h.index[-1] + timedelta(hours=1))
    assert max(Counter(pd.Timestamp(m.ts).isocalendar()[:2] for m in loose.matches).values()) > 3


def test_hold_shape_keeps_only_moments_the_same_distance_from_their_next_open():
    """An overnight asked at the 4pm close is matched to past 4pm closes, not to any hour that
    looks alike; a hold that does not end at the open is left unrestricted."""
    from nightwatch.analog.lens import hours_to_open

    h = history(24 * 400)
    q = {"a": 0.0, "b": 0.0, "c": 5.0, "d": 0.0}
    query_ts = h.index[-1] + timedelta(hours=1)
    at = pd.DatetimeIndex([query_ts + timedelta(hours=1)])
    hold = float(hours_to_open(at)[0])
    on = AnalogEngine(cfg(hold_shape_tol_h=1.5, k=20)).search(h, q, query_ts=query_ts, hold_h=hold)
    assert on.ok
    gaps = np.abs(hours_to_open(pd.DatetimeIndex([m.ts for m in on.matches])) - hold)
    assert (gaps <= 1.5).all()
    off = AnalogEngine(cfg(k=20)).search(h, q, query_ts=query_ts, hold_h=hold)
    assert (np.abs(hours_to_open(pd.DatetimeIndex([m.ts for m in off.matches])) - hold) > 1.5).any()
    odd = AnalogEngine(cfg(hold_shape_tol_h=1.5, k=20)).search(h, q, query_ts=query_ts, hold_h=hold + 7.0)
    assert odd.ok and odd.n_candidates == off.n_candidates  # not an open-to-open hold: no restriction


def test_vol_focused_config_is_the_validated_one():
    c = AnalogConfig.vol_focused()
    assert c.features == ("rv_24h", "rv_168h", "vol_pctl_90d") and c.k == 80 and not c.whiten and c.hold_shape_tol_h == 1.5
