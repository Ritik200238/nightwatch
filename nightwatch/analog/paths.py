"""The retrieved scenarios as paths, not as a number.

The cohort already answers "what followed moments like this" with percentiles, and the
report already lists the forty moments with their dates and features. Neither shows the
one thing a person actually pictures when they hear "past moments like now": the shape
of how each one went.

That matters here beyond decoration. Two cohorts with the same 5th percentile can be a
slow bleed and a violent round trip, and only one of those takes out a stop on the way
to an unremarkable close. A path carries that; an endpoint does not.

Method
------
Every analog is measured over the *ticket's* horizon, so they share an x-axis: hours
from entry. Each is resampled onto one grid of at most ``GRID_POINTS`` points, carried
forward from the last completed bar, and expressed as the token's percentage move from
its own entry close - the same convention the cohort table and histogram already use, so
a short reads consistently across the page rather than being flipped in one place.

The stop is judged on the high and the low, not on the drawn line. A close-to-close path
understates how often a stop is hit, and "nine of these forty would have taken you out"
is only worth printing if it is the number a real stop would have produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

# How many points each path is drawn with. Enough that an overnight round trip is
# visible, few enough that forty of them are a few kilobytes rather than a hundred.
GRID_POINTS = 25
PCTS = (5, 25, 50, 75, 95)


@dataclass(frozen=True)
class ScenarioPath:
    ts: datetime
    ticker: str
    distance: float
    # How far this match sat among *every* candidate hour searched: 0 is the closest of
    # hundreds of thousands, 100 the furthest. Every retrieved analog is near the bottom
    # of that scale by construction, so it says how good the cohort is - not which half
    # of the cohort this one is in.
    distance_percentile: float
    # Where it sits among the forty drawn here: 0 the closest, 1 the furthest. This is
    # the one to colour by; the percentile above puts all forty in the same bucket.
    rank: float
    values: tuple[float, ...]  # token move from entry, %, one per grid point
    stopped_at_h: float | None  # hours into the window the stop would have triggered

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(), "ticker": self.ticker,
            "distance": round(self.distance, 4), "distance_percentile": round(self.distance_percentile, 1),
            "rank": round(self.rank, 4),
            "values": [round(v, 3) for v in self.values],
            "stopped_at_h": self.stopped_at_h,
        }


@dataclass(frozen=True)
class ScenarioPaths:
    hours: tuple[float, ...]
    paths: list[ScenarioPath]
    fan: dict[str, tuple[float, ...]]  # "p5".."p95" across the paths at each grid point
    stop_pct: float | None  # signed distance of the stop from entry, in %
    stopped: int  # how many of these scenarios would have hit it
    n_dropped: int  # analogs with too little data to draw

    def to_dict(self) -> dict[str, Any]:
        return {
            "hours": [round(h, 3) for h in self.hours],
            "paths": [p.to_dict() for p in self.paths],
            "fan": {k: [round(v, 3) for v in vals] for k, vals in self.fan.items()},
            "stop_pct": self.stop_pct,
            "stopped": self.stopped,
            "n_dropped": self.n_dropped,
        }


def _grid(hours: float) -> np.ndarray:
    """Hours from entry, shared by every path so they can be drawn on one axis."""
    n = int(min(GRID_POINTS, max(2, round(hours) + 1)))
    return np.linspace(0.0, float(hours), n)


def _one_path(frame: pd.DataFrame, ts: datetime, grid: np.ndarray) -> np.ndarray | None:
    """One analog resampled onto the shared grid, or None if it cannot be drawn.

    Values are carried forward from the last completed bar: between hourly prints the
    honest thing to draw is the last price there was, not a line invented between two.
    """
    t0 = pd.Timestamp(ts)
    if t0 not in frame.index:
        return None
    entry = float(frame.at[t0, "spot_close"])
    if not np.isfinite(entry) or entry <= 0:
        return None
    end = t0 + pd.Timedelta(hours=float(grid[-1]))
    if end > frame.index[-1]:
        return None
    window = frame.loc[t0:end, "spot_close"].ffill()
    if window.empty or window.isna().all():
        return None
    targets = pd.DatetimeIndex([t0 + pd.Timedelta(hours=float(h)) for h in grid])
    closes = window.reindex(window.index.union(targets)).ffill().reindex(targets)
    if closes.isna().any():
        return None
    return (closes.to_numpy(dtype=float) / entry - 1.0) * 100.0


def _stop_hit(frame: pd.DataFrame, ts: datetime, hours: float, stop_pct: float, side: str) -> float | None:
    """When a stop this far from entry would have triggered, in hours from entry.

    Judged on the bar's low for a long and its high for a short, because that is what a
    resting stop is filled against. Returns the *start* of the bar that breached, which
    is the earliest moment it could have gone; the bar it happened in is the resolution
    the stored data has.
    """
    t0 = pd.Timestamp(ts)
    if t0 not in frame.index or stop_pct == 0:
        return None
    entry = float(frame.at[t0, "spot_close"])
    if not np.isfinite(entry) or entry <= 0:
        return None
    level = entry * (1.0 + stop_pct / 100.0)
    window = frame.loc[t0 + pd.Timedelta(hours=1): t0 + pd.Timedelta(hours=float(hours))]
    if window.empty:
        return None
    col = "spot_low" if side == "long" else "spot_high"
    if col not in window:
        return None
    series = window[col].to_numpy(dtype=float)
    breached = series <= level if side == "long" else series >= level
    breached &= np.isfinite(series)
    if not breached.any():
        return None
    return float((window.index[int(np.argmax(breached))] - t0).total_seconds() / 3600.0)


def build(
    matches: list[Any],
    frames: dict[str, pd.DataFrame],
    *,
    horizon_h: float,
    side: str = "long",
    stop_price: float | None = None,
    entry_price: float | None = None,
) -> ScenarioPaths | None:
    """Draw every retrieved analog over the ticket's horizon.

    ``matches`` are ``AnalogMatch`` objects; ``frames`` maps ticker to its feature
    frame. An analog whose window runs past the stored data is dropped and counted
    rather than drawn short, because a path that stops early reads as a flat ending.
    """
    if not matches or horizon_h <= 0:
        return None
    grid = _grid(horizon_h)
    stop_pct = None
    if stop_price and entry_price and entry_price > 0:
        stop_pct = (stop_price / entry_price - 1.0) * 100.0

    drawn: list[ScenarioPath] = []
    dropped = 0
    for m in matches:
        frame = frames.get(m.ticker)
        if frame is None:
            dropped += 1
            continue
        values = _one_path(frame, m.ts, grid)
        if values is None:
            dropped += 1
            continue
        drawn.append(ScenarioPath(
            ts=m.ts, ticker=m.ticker, distance=float(m.distance),
            distance_percentile=float(m.distance_percentile), rank=0.0, values=tuple(values),
            stopped_at_h=_stop_hit(frame, m.ts, horizon_h, stop_pct, side) if stop_pct is not None else None,
        ))
    if not drawn:
        return None

    # Rank within the drawn set. The engine's own percentile is against every candidate
    # hour searched, so all forty retrieved analogs land in its bottom fraction and are
    # indistinguishable from each other - useless for telling the near half from the far.
    order = np.argsort([p.distance for p in drawn], kind="stable")
    denom = max(1, len(drawn) - 1)
    ranked = list(drawn)
    for position, idx in enumerate(order):
        ranked[int(idx)] = ScenarioPath(**{**drawn[int(idx)].__dict__, "rank": position / denom})
    drawn = ranked

    stacked = np.vstack([p.values for p in drawn])
    fan = {f"p{p}": tuple(np.percentile(stacked, p, axis=0)) for p in PCTS}
    return ScenarioPaths(
        hours=tuple(float(h) for h in grid),
        paths=drawn,
        fan=fan,
        stop_pct=stop_pct,
        stopped=sum(1 for p in drawn if p.stopped_at_h is not None),
        n_dropped=dropped,
    )
