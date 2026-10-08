"""The bad move and the thin book at once: only what the report and the archive say."""

from __future__ import annotations

from nightwatch.execution import joint_break as jb

FRI_NIGHT = "2026-10-09T22:00:00+00:00"  # a Friday, US market shut


def payload(notional=50_000.0, depth=30_000.0, thin=False, hold=60.0):
    def b(name, d, spread=40.0):
        return {"bucket": name, "n_snapshots": 900, "thin": thin, "depth_25bps_p5": d, "spread_p95_bps": spread}

    return {
        "as_of": FRI_NIGHT, "horizon_h": hold, "primary_horizon": "60h",
        "ticket": {"notional_quote": notional, "side": "long"},
        "analog": {"horizons": {"60h": {"loss_p5_pct": -6.0}}},
        "execution": {"liquidity_history": {"buckets": [b("weekend", depth), b("friday_night", depth * 2), b("us_regular", 1e9)]}},
    }


def test_it_takes_the_thinnest_bucket_the_hold_passes_through_and_ignores_the_ones_it_does_not():
    r = jb.build(payload())
    assert r["available"] and r["bucket"] == "weekend"
    assert {"friday_night", "weekend"} <= set(r["buckets"]) and "us_regular" not in r["buckets"]


def test_the_move_is_the_reports_own_line_and_the_spread_is_only_a_floor():
    r = jb.build(payload())
    assert r["move_pct"] == -6.0 and r["move_quote"] == -3_000.0
    assert r["half_spread_floor_bps"] == 20.0 and abs(r["total_floor_pct"] - (-6.2)) < 1e-9


def test_a_position_bigger_than_the_thin_depth_says_the_rest_is_unmeasured_not_a_number():
    r = jb.build(payload(notional=50_000, depth=30_000))
    assert r["unclearable_quote"] == 20_000 and not r["clears_inside_25bps"]
    assert "not measured" in r["plain"] and "没有被测量" in r["plain_zh"]
    ok = jb.build(payload(notional=10_000, depth=30_000))
    assert ok["clears_inside_25bps"] and ok["unclearable_quote"] == 0


def test_thin_archive_buckets_are_not_used_and_it_says_so():
    r = jb.build(payload(thin=True))
    assert r["available"] is False and "recorder" in r["reason"]


def test_no_loss_line_or_no_archive_means_no_panel_not_a_made_up_one():
    p = payload()
    p["analog"] = {"horizons": {}}
    assert jb.build(p) is None
    q = payload()
    q["execution"]["liquidity_history"] = {}
    assert jb.build(q) is None
