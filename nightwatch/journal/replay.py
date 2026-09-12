"""Historical replay: forecasts the system *would* have made, judged by what happened.

For a ticker, walk back through stored history and, at each chosen instant, build the
point-in-time snapshot, run the analog search on history strictly before it, and
record the predicted distribution for the given horizon. Because the future bars
exist in the store, every replay forecast matures immediately, so the calibration
page has hundreds of scored predictions on day one — and every one of them is
reproducible from the stored data and the snapshot hash.

Replay points default to the start of each closed-market window (the moment the
product is built for), thinned to at most one per ``min_gap_h``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.analog.cohort import sample_baseline_times, summarize
from nightwatch.analog.engine import AnalogEngine
from nightwatch.analog.outcomes import compute_match_outcomes, outcomes_table, structural_horizons
from nightwatch.features.snapshot import InsufficientData, build_snapshot
from nightwatch.journal.journal import Journal
from nightwatch.pipeline.analyze import AnalysisContext
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)


def closed_window_starts(frame: pd.DataFrame, *, start: datetime, end: datetime, min_gap_h: int = 24) -> list[datetime]:
    """First closed hour after each regular session inside [start, end)."""
    f = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index < pd.Timestamp(end))]
    closed = f["is_closed"].astype(bool).to_numpy()
    out: list[datetime] = []
    last: datetime | None = None
    for i in range(1, len(f)):
        if closed[i] and not closed[i - 1]:
            ts = f.index[i].to_pydatetime()
            if last is None or (ts - last) >= timedelta(hours=min_gap_h):
                out.append(ts)
                last = ts
    return out


def replay_ticker(
    ctx: AnalysisContext,
    journal: Journal,
    ticker: str,
    *,
    points: list[datetime] | None = None,
    lookback_days: int = 180,
    max_points: int = 150,
    horizon: str = "next_open",
    side: str = "long",
    min_history_days: int = 120,
) -> int:
    """Record one forecast per replay point; returns the number recorded."""
    spec = ctx.spec(ticker)
    end_all = utc_now()
    frame = ctx.feature_frame(ticker, end_all)
    if points is None:
        start = max(frame.index[0].to_pydatetime() + timedelta(days=min_history_days), end_all - timedelta(days=lookback_days))
        points = closed_window_starts(frame, start=start, end=end_all - timedelta(days=4))
        if len(points) > max_points:
            idx = np.linspace(0, len(points) - 1, max_points).round().astype(int)
            points = [points[i] for i in idx]
    engine = AnalogEngine(ctx.analog_config)
    recorded = 0
    for i, at in enumerate(points, 1):
        try:
            snap = build_snapshot(ctx.store, spec, at + timedelta(minutes=5))
        except InsufficientData as exc:
            log.info("replay %s @%s skipped: %s", ticker, at, exc)
            continue
        hist = frame.loc[frame.index < pd.Timestamp(snap.bar_ts)]
        hz = structural_horizons(at)[horizon] if horizon in ("next_open", "window_end") else float(horizon.rstrip("h"))
        if hz <= 0:
            continue
        ticket_h = max(1, int(round(hz)))
        res = engine.search(hist.assign(ticker=ticker), snap.features, query_ts=snap.bar_ts, query_bucket=snap.labels.get("bucket"), query_ticker=ticker)
        scope = "same_ticker"
        if (not res.ok or res.n < ctx.analog_config.k) and ctx.tickers_with_data():
            from nightwatch.analog.engine import pooled_history

            parts = [(ticker, hist)]
            for t in ctx.tickers_with_data():
                if t == ticker:
                    continue
                try:
                    f = ctx.feature_frame(t, end_all)
                except InsufficientData:
                    continue
                parts.append((t, f.loc[f.index < pd.Timestamp(snap.bar_ts)]))
            pooled = pooled_history(parts)
            pres = engine.search(pooled, snap.features, query_ts=snap.bar_ts, query_bucket=snap.labels.get("bucket"), query_ticker=ticker)
            if pres.ok and (not res.ok or pres.n > res.n):
                res, scope = pres, "pooled"
        quantiles: dict[str, float | None] = {k: None for k in ("p5", "p25", "p50", "p75", "p95")}
        es5 = None
        if res.ok:
            frames = {ticker: frame}
            outs = []
            for m in res.matches:
                f = frames.get(m.ticker)
                if f is None:
                    f = ctx.feature_frame(m.ticker, end_all)
                    frames[m.ticker] = f
                try:
                    outs.append(compute_match_outcomes(f, m.ts, fixed_h=(ticket_h,)))
                except (KeyError, ValueError):
                    continue
            table = outcomes_table(outs, f"{ticket_h}h")
            stats = summarize(table, weights=np.array([m.similarity for m in res.matches[: len(outs)]]), min_sample=ctx.analog_config.min_matches)
            if not stats.insufficient:
                sign = 1.0 if side == "long" else -1.0
                # Quantiles of the *position's* return: a short flips and reorders them.
                qs = [stats.p5, stats.p25, stats.median_pct, stats.p75, stats.p95]
                qs = sorted(sign * q for q in qs)
                quantiles = dict(zip(("p5", "p25", "p50", "p75", "p95"), qs, strict=True))
                es5 = None
        # Same-bucket random baseline from history strictly before the point, so the
        # journal can later say whether the analogs carried any information at all.
        base_q: dict[str, float | None] = {k: None for k in ("p5", "p25", "p50", "p75", "p95")}
        try:
            cut = hist.index <= pd.Timestamp(snap.bar_ts) - pd.Timedelta(hours=ctx.analog_config.min_age_h)
            same_bucket = (hist["bucket"] == snap.labels.get("bucket"))[cut]
            closed_mask = hist["is_closed"].astype(bool)[cut]
            exclude = pd.DatetimeIndex([m.ts for m in res.matches if m.ticker == ticker]) if res.ok else None
            base_ts = sample_baseline_times(hist.index[cut], n=120, bucket_mask=same_bucket, fallback_mask=closed_mask, exclude=exclude, min_separation_h=ctx.analog_config.min_separation_h)
            base_outs = []
            for t in base_ts:
                try:
                    base_outs.append(compute_match_outcomes(frame, t.to_pydatetime(), fixed_h=(ticket_h,)))
                except (KeyError, ValueError):
                    continue
            bstats = summarize(outcomes_table(base_outs, f"{ticket_h}h"), min_sample=ctx.analog_config.min_matches)
            if not bstats.insufficient:
                sign = 1.0 if side == "long" else -1.0
                bq = sorted(sign * q for q in (bstats.p5, bstats.p25, bstats.median_pct, bstats.p75, bstats.p95))
                base_q = dict(zip(("p5", "p25", "p50", "p75", "p95"), bq, strict=True))
        except Exception:  # noqa: BLE001
            log.exception("replay %s @%s: baseline failed", ticker, at)
        entry = snap.prices["spot_close"] or 0.0
        journal.record_forecast(
            kind="replay", ticker=ticker, side=side, notional=10_000.0, as_of=at, bar_ts=snap.bar_ts, horizon_h=float(ticket_h), entry_price=float(entry),
            snapshot_hash=snap.content_hash, analog_n=res.n if res.ok else 0, analog_scope=scope, quantiles=quantiles, es5=es5, mc_p5=None, mc_p95=None,
            verdict=None, recommended_notional=None, payload={"labels": snap.labels, "quality_flags": snap.quality_flags, "reason": res.reason},
            baseline_quantiles=base_q,
        )
        recorded += 1
        if i % 25 == 0:
            log.info("replay %s: %d/%d", ticker, i, len(points))
    return recorded
