"""Does adding a feature to the analog search actually help?

The temptation with a similarity engine is to keep adding inputs because each one sounds
sensible. This answers the question with a measurement instead: run the same past moments
through two configurations, score both forecasts against what really happened with the
pinball (quantile) loss, and compare them pair by pair.

Nothing here is fitted. Each point uses only history strictly before it, exactly as the
live pipeline does, so the comparison is out of sample by construction.

    python research/feature_ab.py --tickers TSLA NVDA AAPL MSFT AMZN GOOGL --points 60

Prints, per quantile and overall, how much the extra features change the loss, with a
paired bootstrap interval. A gain whose interval includes zero has not been shown to help.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from nightwatch.analog.cohort import summarize  # noqa: E402
from nightwatch.analog.engine import AnalogConfig, AnalogEngine  # noqa: E402
from nightwatch.analog.outcomes import compute_match_outcomes, outcomes_table  # noqa: E402
from nightwatch.config import load_settings  # noqa: E402
from nightwatch.data.store import Store  # noqa: E402
from nightwatch.features.macro import MACRO_COLUMNS  # noqa: E402
from nightwatch.features.snapshot import SEARCH_COLUMNS, InsufficientData, build_snapshot  # noqa: E402
from nightwatch.journal.replay import closed_window_starts  # noqa: E402
from nightwatch.journal.skill import QUANTILES, pinball  # noqa: E402
from nightwatch.pipeline.analyze import AnalysisContext  # noqa: E402
from nightwatch.time_utils import utc_now  # noqa: E402


def quantiles_at(ctx: AnalysisContext, engine: AnalogEngine, ticker: str, frame: pd.DataFrame, at, horizon_h: int) -> dict[str, float] | None:
    """The cohort's stated distribution at one past instant, using only earlier history."""
    try:
        snap = build_snapshot(ctx.store, ctx.spec(ticker), at + timedelta(minutes=5))
    except InsufficientData:
        return None
    hist = frame.loc[frame.index < pd.Timestamp(snap.bar_ts)]
    res = engine.search(hist.assign(ticker=ticker), snap.features, query_ts=snap.bar_ts, query_bucket=snap.labels.get("bucket"), query_ticker=ticker)
    if not res.ok:
        return None
    outs = []
    for m in res.matches:
        try:
            outs.append(compute_match_outcomes(frame, m.ts, fixed_h=(horizon_h,)))
        except (KeyError, ValueError):
            continue
    stats = summarize(outcomes_table(outs, f"{horizon_h}h"), min_sample=engine.config.min_matches)
    if stats.insufficient:
        return None
    return {"p5": stats.p5, "p25": stats.p25, "p50": stats.median_pct, "p75": stats.p75, "p95": stats.p95}


def realised(frame: pd.DataFrame, at, horizon_h: int) -> float | None:
    try:
        out = compute_match_outcomes(frame, at, fixed_h=(horizon_h,))
    except (KeyError, ValueError):
        return None
    o = out.outcomes.get(f"{horizon_h}h")
    return None if (o is None or o.status != "MATURED" or o.ret_pct is None) else float(o.ret_pct)


def paired_ci(diff: np.ndarray, n_boot: int = 4000, seed: int = 23) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", nargs="+", default=["TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"])
    ap.add_argument("--points", type=int, default=60, help="closed-market windows per ticker")
    ap.add_argument("--horizon", type=int, default=24, help="hours held")
    ap.add_argument("--extra", nargs="*", default=list(MACRO_COLUMNS), help="features to add in the B configuration")
    args = ap.parse_args()

    settings = load_settings()
    with Store(settings.db_path) as store:
        from nightwatch.cli import _entries_from_store

        ctx = AnalysisContext(store=store, entries=_entries_from_store(store, settings))
        base_cfg = AnalogConfig()
        with_cfg = replace(base_cfg, features=tuple(SEARCH_COLUMNS) + tuple(args.extra))
        a_engine, b_engine = AnalogEngine(base_cfg), AnalogEngine(with_cfg)
        end = utc_now()

        rows = []
        for ticker in args.tickers:
            try:
                frame = ctx.feature_frame(ticker, end)
            except InsufficientData as exc:
                print(f"{ticker}: skipped ({exc})")
                continue
            start = frame.index[0].to_pydatetime() + timedelta(days=120)
            points = closed_window_starts(frame, start=start, end=end - timedelta(days=4))
            if len(points) > args.points:
                points = [points[i] for i in np.linspace(0, len(points) - 1, args.points).round().astype(int)]
            kept = 0
            for at in points:
                r = realised(frame, at, args.horizon)
                if r is None:
                    continue
                qa = quantiles_at(ctx, a_engine, ticker, frame, at, args.horizon)
                qb = quantiles_at(ctx, b_engine, ticker, frame, at, args.horizon)
                if qa is None or qb is None:
                    continue
                rows.append({"ticker": ticker, "at": at, "r": r, **{f"a_{k}": v for k, v in qa.items()}, **{f"b_{k}": v for k, v in qb.items()}})
                kept += 1
            print(f"{ticker}: {kept} scored points")

    if len(rows) < 30:
        print(f"\nonly {len(rows)} paired points; not enough to conclude anything")
        return 1

    df = pd.DataFrame(rows)
    y = df["r"].to_numpy(float)
    print(f"\n{len(df)} paired forecasts across {df['ticker'].nunique()} tokens, {args.horizon}h horizon")
    print(f"A = {len(SEARCH_COLUMNS)} features; B = A + {', '.join(args.extra)}\n")
    print("  quantile      A loss    B loss     change   95% CI of the gain")
    total_a = np.zeros(len(df))
    total_b = np.zeros(len(df))
    for q, tau in QUANTILES:
        la = pinball(y, df[f"a_{q}"].to_numpy(float), tau)
        lb = pinball(y, df[f"b_{q}"].to_numpy(float), tau)
        total_a += la
        total_b += lb
        lo, hi = paired_ci(la - lb)  # positive = B is better
        print(f"  {q:>8}    {la.mean():8.4f}  {lb.mean():8.4f}   {1 - lb.mean() / la.mean():+7.2%}   [{lo:+.4f}, {hi:+.4f}]")
    lo, hi = paired_ci((total_a - total_b) / len(QUANTILES))
    ma, mb = total_a.mean() / len(QUANTILES), total_b.mean() / len(QUANTILES)
    print(f"  {'all':>8}    {ma:8.4f}  {mb:8.4f}   {1 - mb / ma:+7.2%}   [{lo:+.4f}, {hi:+.4f}]")
    verdict = "B is better" if lo > 0 else ("A is better" if hi < 0 else "no difference that the data can show")
    print(f"\n  {verdict}")
    print(f"  below p5: A {np.mean(y < df['a_p5']):.1%}, B {np.mean(y < df['b_p5']):.1%} (target 5%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
