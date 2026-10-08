"""The two ways a night goes wrong at once: a bad move, and a book too thin to leave through.

The report already says how far the position could fall (the one-in-twenty line) and how
much it costs to leave on the book right now. Those are two separate numbers, but the
nights that hurt are the ones where they arrive together: the price gaps and the order
book is at its thinnest. This puts them side by side for the part of the week the hold
runs through, from what the recorder has actually stored about that book.

What it claims, and what it does not:

* The move is the report's own one-in-twenty loss for the hold, not a new estimate.
* The book is the thinnest-twentieth of recorded snapshots for the time-of-week bucket
  the hold passes through (the worst of them, if it spans several).
* Spread cost is a floor: crossing half of the 95th-percentile spread. Beyond the depth the
  archive stores (inside 25 bps of the mid) nothing is measured, so when the position is
  bigger than that depth the extra cost is said to be unmeasured and higher, never
  guessed at a number.
* It does not say the two happen together on any given night. It says what the night
  looks like if they do.

Built from the serialised report like provenance, so it can be rebuilt for a stored one.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from nightwatch.time_utils import hour_of_week_bucket

MAX_HOURS_SAMPLED = 24 * 5
BUCKET_EN = {
    "us_regular": "US regular hours", "us_pre": "US pre-market", "us_post": "US after-hours", "weeknight": "a weeknight",
    "friday_night": "Friday night", "weekend": "the weekend", "sunday_night": "Sunday night", "holiday": "a US holiday",
}
BUCKET_ZH = {
    "us_regular": "美股常规交易时段", "us_pre": "美股盘前", "us_post": "美股盘后", "weeknight": "工作日夜间",
    "friday_night": "周五夜间", "weekend": "周末", "sunday_night": "周日夜间", "holiday": "美国节假日",
}


def _spanned_buckets(as_of: datetime, hours: float) -> list[str]:
    """The time-of-week buckets the hold passes through, in order, from hourly samples."""
    n = min(MAX_HOURS_SAMPLED, max(1, math.ceil(hours)))
    seen: list[str] = []
    for k in range(n + 1):
        b = hour_of_week_bucket(as_of + timedelta(hours=k)).value
        if b not in seen:
            seen.append(b)
    return seen


def build(payload: dict[str, Any]) -> dict[str, Any] | None:
    ex = payload.get("execution") or {}
    lh = ex.get("liquidity_history") or {}
    an = payload.get("analog") or {}
    tk = payload.get("ticket") or {}
    hz = (an.get("horizons") or {}).get(payload.get("primary_horizon") or "")
    notional = tk.get("notional_quote")
    try:
        as_of = datetime.fromisoformat(str(payload.get("as_of")))
        hours = float(payload.get("horizon_h"))
    except (TypeError, ValueError):
        return None
    if not hz or hz.get("loss_p5_pct") is None or not notional or not lh.get("buckets"):
        return None

    spanned = _spanned_buckets(as_of, hours)
    usable = [b for b in lh["buckets"] if b["bucket"] in spanned and not b.get("thin") and b.get("depth_25bps_p5") is not None]
    if not usable:
        return {"available": False, "buckets": spanned,
                "reason": "the recorder has not yet stored enough of this book across the hours the hold runs through"}
    b = min(usable, key=lambda x: x["depth_25bps_p5"])

    notional = float(notional)
    move_pct = float(hz["loss_p5_pct"])
    depth = float(b["depth_25bps_p5"])
    half_spread_bps = float(b["spread_p95_bps"]) / 2.0 if b.get("spread_p95_bps") is not None else None
    beyond = max(0.0, notional - depth)
    floor_extra_pct = (half_spread_bps or 0.0) / 100.0
    total_floor_pct = move_pct - floor_extra_pct

    if beyond <= 0:
        reach_en = f"The thin book still shows {depth:,.0f} USDT sellable inside 25 bps, enough for this size."
        reach_zh = f"即使盘口最薄时，25 bps 以内仍可卖出约 {depth:,.0f} USDT，足够承接这个仓位。"
    else:
        reach_en = (f"In its thinnest twentieth only {depth:,.0f} USDT was sellable inside 25 bps, so about {beyond:,.0f} of the "
                    f"{notional:,.0f} would have to be sold more than 25 bps from the mid. That extra cost is higher than shown and is not measured.")
        reach_zh = (f"在最薄的二十分之一时刻，25 bps 以内只能卖出约 {depth:,.0f} USDT，所以 {notional:,.0f} 中约 {beyond:,.0f} 要在偏离中间价超过 25 bps 的位置成交。"
                    "这部分额外成本比这里显示的更高，且没有被测量。")
    name = BUCKET_EN.get(b["bucket"], b["bucket"].replace("_", " "))
    name_zh = BUCKET_ZH.get(b["bucket"], name)
    return {
        "available": True,
        "bucket": b["bucket"],
        "buckets": spanned,
        "n_snapshots": b["n_snapshots"],
        "notional": notional,
        "move_pct": move_pct,
        "move_quote": notional * move_pct / 100.0,
        "depth_p5": depth,
        "spread_p95_bps": b.get("spread_p95_bps"),
        "half_spread_floor_bps": half_spread_bps,
        "total_floor_pct": total_floor_pct,
        "total_floor_quote": notional * total_floor_pct / 100.0,
        "unclearable_quote": beyond,
        "clears_inside_25bps": beyond <= 0,
        "plain": (f"If the one-in-twenty bad move for this hold ({move_pct:+.1f}%) arrives during {name}, when the book is at its thinnest twentieth, "
                  f"the loss is about {abs(notional * move_pct / 100.0):,.0f} USDT on the move alone, and leaving costs at least "
                  f"{(half_spread_bps or 0.0):.0f} bps more to cross the spread, so {total_floor_pct:+.1f}% at the least. {reach_en}"),
        "plain_zh": (f"如果这次持有期内一次二十分之一的不利波动（{move_pct:+.1f}%）发生在{name_zh}、盘口处于最薄的二十分之一时，"
                     f"仅价格波动就亏约 {abs(notional * move_pct / 100.0):,.0f} USDT，平仓时越过买卖价差至少再多 {(half_spread_bps or 0.0):.0f} bps，合计至少 {total_floor_pct:+.1f}%。{reach_zh}"),
    }
