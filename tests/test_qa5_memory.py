"""QA round 5, speed: the API on a 900 MB box slowed to a crawl because it swapped. These pin the
memory the request path no longer holds, and that the answers did not change."""

from datetime import timedelta

import pandas as pd

from nightwatch.analog.engine import AnalogConfig, AnalogEngine, _pooled_history_by_copy, pooled_history
from tests.test_analog_engine import FEATS, history
from tests.test_pipeline import AS_OF, _ctx, seeded_store  # noqa: F401 - fixture


def test_the_column_wise_stack_is_the_copy_and_sort_stack():
    parts = [("TSLA", history(24 * 40, seed=1)), ("NVDA", history(24 * 40, seed=2)), ("AAPL", history(24 * 25, seed=3))]
    pd.testing.assert_frame_equal(pooled_history(parts), _pooled_history_by_copy(parts))
    assert pooled_history([]).empty


def test_frames_with_different_columns_still_stack():
    a, b = history(24 * 10, seed=1), history(24 * 10, seed=2).assign(extra=1.0)
    pd.testing.assert_frame_equal(pooled_history([("A", a), ("B", b)]), _pooled_history_by_copy([("A", a), ("B", b)]))


def test_the_search_reads_the_same_matches_from_the_columns_it_needs():
    h = history()
    wide = h.assign(**{f"unused_{i}": 0.0 for i in range(30)})
    q = {"a": 1.0, "b": 0.9, "c": 5.0, "d": 0.0}
    ts = h.index[-1] + timedelta(hours=1)
    cfg = AnalogConfig(features=FEATS, k=10, min_matches=5, min_separation_h=36, min_age_h=96, whiten=True)
    a, b = AnalogEngine(cfg).search(h, q, query_ts=ts), AnalogEngine(cfg).search(wide, q, query_ts=ts)
    assert a.ok and [(m.ts, m.distance) for m in a.matches] == [(m.ts, m.distance) for m in b.matches]
    assert "unused_0" in wide.columns  # the caller's frame is not touched


def test_an_old_hour_never_pushes_a_current_frame_out_of_the_cache(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.frame_cache_size = 3
    for t in ("TSLA", "NVDA", "AAPL"):
        ctx.feature_frame(t, AS_OF)
    ctx.feature_frame("TSLA", AS_OF - timedelta(hours=3))  # a what-if on a report from earlier in the day
    assert sorted(k.split("|")[0] for k in ctx._frames) == ["AAPL", "NVDA", "TSLA"]
    assert all(k.split("|")[1] == AS_OF.replace(minute=0, second=0, microsecond=0).isoformat() for k in ctx._frames)
    assert len(ctx._older_frames) == 1
    ctx.store.close()


def test_a_new_hour_replaces_the_old_one_instead_of_sitting_beside_it(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.feature_frame("TSLA", AS_OF)
    ctx.feature_frame("TSLA", AS_OF + timedelta(hours=1))
    assert [k for k in ctx._frames if k.startswith("TSLA|")] == [f"TSLA|{(AS_OF + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()}"]
    ctx.store.close()


def test_older_frames_are_few(seeded_store):  # noqa: F811
    ctx = _ctx(seeded_store)
    ctx.feature_frame("TSLA", AS_OF)
    for h in range(1, 9):
        ctx.feature_frame("TSLA", AS_OF - timedelta(hours=h))
    from nightwatch.pipeline.analyze import OLDER_FRAMES_KEPT

    assert len(ctx._older_frames) == OLDER_FRAMES_KEPT
    ctx.store.close()


def test_fee_rates_are_read_once_not_per_analysis(seeded_store, monkeypatch):  # noqa: F811
    from nightwatch.pipeline import analyze as an

    ctx = _ctx(seeded_store)
    spec = ctx.spec("TSLA")
    calls = []
    real = ctx.store.list_instruments
    monkeypatch.setattr(ctx.store, "list_instruments", lambda *a, **k: calls.append(1) or real(*a, **k))
    first, second = an._fees(ctx, spec), an._fees(ctx, spec)
    assert first == second and len(calls) == 2  # both venues, once
    first["spot_taker"] = 9.0
    assert an._fees(ctx, spec)["spot_taker"] != 9.0  # a caller cannot change the cached copy
    ctx.store.close()
