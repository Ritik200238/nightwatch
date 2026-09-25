"""Does the engine disagreeing with itself warn of a breach?

The desk answers with one search: forty neighbours over twenty-one features. Change the
recipe a little - thirty neighbours, sixty, drop the volatility features, drop the
macro ones - and the 5th percentile moves. It is tempting to report how much it moves as
a confidence: "the verdict holds in eleven of twelve versions of the model". That is a
claim about the future, and claims about the future can be scored.

Two questions, written down before the sweep was run. First, when the versions disagree
more, does the real outcome break the shipped 5th percentile more often? If yes, the
spread is information and belongs on the report. Second, is a 5th percentile pooled
across the versions truer than the single one the desk ships?

The first question has a trap in it. A narrow 5th percentile is breached more often
than a wide one whatever the versions say, and the versions disagree more, in relative
terms, exactly when the shipped number is small. So the spread is tested twice: on its
own, and again holding the size of the shipped number fixed. Only the second counts.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.journal.studies import NO, T_CONVINCING, UNCLEAR, YES, Study, _pinball, _t
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

KEY = "disagreement_warns_of_a_breach"
TITLE = "Does the engine disagreeing with itself warn of a breach?"

# The recipe changes. Neighbour counts around the shipped forty, and each feature group
# left out in turn; a group is dropped whole because its members stand in for each other.
K_VARIANTS = (25, 30, 60)
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "basis": ("basis_index_bps", "basis_index_z", "basis_index_d6h_bps", "basis_native_bps"),
    "volatility": ("rv_24h", "rv_168h", "vol_pctl_90d"),
    "trend": ("trend_sma_pct", "sma_slope_5d_pct"),
    "liquidity": ("liq_ratio", "no_trade_share_24h", "native_close_age_h"),
    "events": ("hours_to_earnings", "hours_since_earnings", "macro_events_72h", "hours_to_fomc", "news_count_24h"),
    "macro": ("vix_pctl_1y", "curve_pctl_1y", "dollar_20d_chg_pct", "ten_year_20d_chg_bps"),
}
SHIPPED = "shipped"
MIN_MOMENTS = 200
MIN_TOKENS = 5
MIN_PER_TOKEN = 12  # a within-token slope on fewer moments than this is noise


def variants(config: Any) -> dict[str, Any]:  # noqa: ANN401
    """The shipped config and every one-step change to it."""
    out = {SHIPPED: config}
    for k in K_VARIANTS:
        out[f"k{k}"] = replace(config, k=k)
    for name, cols in FEATURE_GROUPS.items():
        kept = tuple(f for f in config.features if f not in cols)
        if len(kept) < len(config.features):
            out[f"no_{name}"] = replace(config, features=kept)
    return out


def collect(ctx: Any, *, max_points_per_ticker: int = 40, lookback_days: int = 240, min_history_days: int = 120) -> pd.DataFrame:  # noqa: ANN401
    """One row per replay moment: what happened, and the raw 5th percentile from every
    version of the engine, each searched on the pooled history strictly before it."""
    from nightwatch.analog.engine import AnalogEngine, pooled_history
    from nightwatch.analog.outcomes import compute_match_outcomes, structural_horizons
    from nightwatch.features.snapshot import InsufficientData, build_snapshot
    from nightwatch.journal.replay import closed_window_starts

    end_all = utc_now()
    frames: dict[str, pd.DataFrame] = {}
    for t in ctx.tickers_with_data():
        try:
            frames[t] = ctx.feature_frame(t, end_all)
        except InsufficientData as exc:
            log.info("robust study: no frame for %s (%s)", t, exc)
    if not frames:
        return pd.DataFrame()
    pooled = pooled_history(list(frames.items()))
    pooled_ns = pooled.index.values.astype("datetime64[ns]")
    engines = {name: AnalogEngine(cfg) for name, cfg in variants(ctx.analog_config).items()}
    min_n = ctx.analog_config.min_matches

    rows: list[dict[str, Any]] = []
    for ticker, frame in frames.items():
        start = max(frame.index[0].to_pydatetime() + timedelta(days=min_history_days), end_all - timedelta(days=lookback_days))
        points = closed_window_starts(frame, start=start, end=end_all - timedelta(days=4))
        if len(points) > max_points_per_ticker:
            idx = np.linspace(0, len(points) - 1, max_points_per_ticker).round().astype(int)
            points = [points[i] for i in idx]
        spec = ctx.spec(ticker)
        for at in points:
            try:
                snap = build_snapshot(ctx.store, spec, at + timedelta(minutes=5))
            except InsufficientData:
                continue
            hz = structural_horizons(at)["next_open"]
            if hz <= 0:
                continue
            h = max(1, int(round(hz)))
            try:
                truth = compute_match_outcomes(frame, snap.bar_ts, fixed_h=(h,)).outcomes[f"{h}h"]
            except (KeyError, ValueError):
                continue
            if truth.status != "MATURED" or truth.ret_pct is None:
                continue
            cut = int(np.searchsorted(pooled_ns, np.datetime64(pd.Timestamp(snap.bar_ts).tz_localize(None)), side="left"))
            hist = pooled.iloc[:cut]
            row: dict[str, Any] = {"ticker": ticker, "as_of": at.isoformat(), "horizon_h": h, "truth": float(truth.ret_pct)}
            outcome_cache: dict[tuple[str, Any], float | None] = {}
            for name, eng in engines.items():
                res = eng.search(hist, snap.features, query_ts=snap.bar_ts, query_bucket=snap.labels.get("bucket"), query_ticker=ticker)
                rets: list[float] = []
                if res.ok:
                    for m in res.matches:
                        key = (m.ticker, m.ts)
                        if key not in outcome_cache:
                            mf = frames.get(m.ticker)
                            try:
                                o = compute_match_outcomes(mf, m.ts, fixed_h=(h,)).outcomes[f"{h}h"] if mf is not None else None
                            except (KeyError, ValueError):
                                o = None
                            outcome_cache[key] = o.ret_pct if o is not None and o.status == "MATURED" else None
                        if outcome_cache[key] is not None:
                            rets.append(outcome_cache[key])  # type: ignore[arg-type]
                row[f"p5_{name}"] = float(np.percentile(rets, 5)) if len(rets) >= min_n else None
            rows.append(row)
    return pd.DataFrame(rows)


def _within_token_slopes(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Least-squares slope of breach on each column, per token, columns standardised
    within the token so the slopes are comparable across tokens."""
    out: dict[str, np.ndarray] = {}
    for tk, g in df.groupby("ticker"):
        if len(g) < MIN_PER_TOKEN:
            continue
        cols_std = []
        for c in cols:
            v = g[c].to_numpy(float)
            sd = v.std()
            cols_std.append((v - v.mean()) / sd if sd > 0 else np.zeros_like(v))
        x = np.column_stack([np.ones(len(g)), *cols_std])
        beta, *_ = np.linalg.lstsq(x, g["breach"].to_numpy(float), rcond=None)
        out[str(tk)] = beta[1:]
    return pd.DataFrame(out, index=cols).T


def score(rows: pd.DataFrame) -> dict[str, Any]:
    names = [c[3:] for c in rows.columns if c.startswith("p5_")]
    df = rows.dropna(subset=[f"p5_{n}" for n in names] + ["truth"]).copy()
    if df.empty:
        return {"n": 0}
    p = df[[f"p5_{n}" for n in names]].to_numpy(float)
    shipped = df[f"p5_{SHIPPED}"].to_numpy(float)
    df["breach"] = (df["truth"].to_numpy(float) < shipped).astype(float)
    df["size"] = np.abs(shipped).clip(min=0.05)
    df["spread"] = (p.max(axis=1) - p.min(axis=1)) / df["size"]
    df["inv_size"] = 1.0 / df["size"]
    df["ensemble"] = np.median(p, axis=1)

    # Question 1, uncontrolled: within each token, breach rate in the most-disagreed
    # third minus the least-disagreed third.
    diffs = {}
    for tk, g in df.groupby("ticker"):
        if len(g) < MIN_PER_TOKEN:
            continue
        lo, hi = g["spread"].quantile([1 / 3, 2 / 3])
        diffs[str(tk)] = g.loc[g["spread"] >= hi, "breach"].mean() - g.loc[g["spread"] <= lo, "breach"].mean()
    raw = pd.Series(diffs)
    # Question 1, controlled: the same slope with the size of the shipped number held fixed.
    alone = _within_token_slopes(df, ["spread"])
    both = _within_token_slopes(df, ["inv_size", "spread"])
    # Question 2: the pooled 5th percentile against the shipped one, pinball at 0.05.
    y = df["truth"].to_numpy(float)
    gain = pd.Series(_pinball(y, shipped) - _pinball(y, df["ensemble"].to_numpy(float)), index=df["ticker"].to_numpy()).groupby(level=0).mean()

    thirds = pd.qcut(df["size"].rank(method="first"), 3, labels=["narrow", "mid", "wide"])
    by_size = df.groupby(thirds, observed=True)["breach"].mean()
    return {
        "n": int(len(df)), "tokens": int(len(raw)), "versions": len(names),
        "raw_diff": float(raw.mean()) if len(raw) else float("nan"), "raw_t": _t(raw.to_numpy()) if len(raw) > 1 else float("nan"),
        "alone_t": _t(alone["spread"].to_numpy()) if len(alone) > 1 else float("nan"),
        "controlled_t": _t(both["spread"].to_numpy()) if len(both) > 1 else float("nan"),
        "size_t": _t(both["inv_size"].to_numpy()) if len(both) > 1 else float("nan"),
        "controlled_up": int((both["spread"] > 0).sum()) if len(both) else 0,
        "ensemble_t": _t(gain.to_numpy()) if len(gain) > 1 else float("nan"), "ensemble_up": int((gain > 0).sum()),
        "breach_shipped": float(df["breach"].mean()), "breach_ensemble": float((y < df["ensemble"]).mean()),
        "breach_narrow": float(by_size.get("narrow", np.nan)), "breach_wide": float(by_size.get("wide", np.nan)),
        "median_spread": float(df["spread"].median()),
    }


def study(rows: pd.DataFrame) -> Study:
    r = score(rows)
    question = (
        "Run the search a dozen slightly different ways - fewer neighbours, more, one feature group left out at a time - and the "
        "5th percentile moves. Is how much it moves a warning worth showing, and is the average of the versions truer than the one we ship?"
    )
    method = (
        "Every closed-market moment the calibration replay scores, searched on the pooled history before it by the shipped recipe and "
        f"{max(r.get('versions', 1) - 1, 0)} one-step changes to it. Two pre-registered tests. One: within each token, does the real outcome breach the "
        "shipped 5th percentile more often when the versions disagree more - first on its own, then with the size of the shipped number "
        "held fixed, because a narrow tail is breached more often whatever the versions say. Two: is the median of the versions a better "
        "5th percentile than the shipped one, on pinball loss at 0.05. Both clustered by token."
    )
    if r["n"] < MIN_MOMENTS or r["tokens"] < MIN_TOKENS:
        return Study(key=KEY, title=TITLE, question=question, method=method, finding="Too few scored moments to decide.",
                     consequence="Nothing changes until there is enough to judge.", verdict=UNCLEAR, n=int(r["n"]), stats={})

    controlled = r["controlled_t"] > T_CONVINCING
    looked_true = r["raw_t"] > T_CONVINCING or r["alone_t"] > T_CONVINCING
    ensemble_better = r["ensemble_t"] > T_CONVINCING
    verdict = YES if controlled else NO if (looked_true or abs(r["controlled_t"]) < T_CONVINCING) else UNCLEAR

    bits = []
    if controlled:
        bits.append(
            f"Yes. Where the versions disagreed most the shipped tail was breached {r['raw_diff']:+.1%} more often than where they agreed "
            f"(t={r['raw_t']:+.1f}), and the effect survives holding the size of the shipped number fixed "
            f"({r['controlled_up']} of {r['tokens']} tokens, t={r['controlled_t']:+.1f})."
        )
    elif looked_true:
        bits.append(
            f"It looks true and it is not. Where the versions disagreed most the shipped tail was breached {r['raw_diff']:+.1%} more often "
            f"than where they agreed (t={r['raw_t']:+.1f}), which would be a publishable confidence score. Hold the size of the shipped "
            f"number fixed and the effect goes away (t={r['controlled_t']:+.1f}); the size itself is what predicts a breach "
            f"(t={r['size_t']:+.1f}: {r['breach_narrow']:.1%} of the narrowest third breached against {r['breach_wide']:.1%} of the widest). "
            "The disagreement was a proxy for a small number, not a measure of doubt."
        )
    else:
        bits.append(f"No. Disagreement between the versions does not predict a breach, on its own or controlled (t={r['alone_t']:+.1f}, {r['controlled_t']:+.1f}).")
    if ensemble_better:
        bits.append(f"Pooling the versions does help: the median 5th percentile beats the shipped one on {r['ensemble_up']} of {r['tokens']} tokens (t={r['ensemble_t']:+.1f}).")
    else:
        bits.append(
            f"Pooling the versions does not help either: the median 5th percentile is not separable from the shipped one "
            f"({r['ensemble_up']} of {r['tokens']} tokens better, t={r['ensemble_t']:+.1f}; breach {r['breach_ensemble']:.1%} against {r['breach_shipped']:.1%})."
        )
    finding = " ".join(bits)

    if controlled:
        consequence = "Worth showing next to the verdict as a measure of how settled the answer is."
    else:
        consequence = (
            "No 'the verdict holds in eleven of twelve versions' line is shown, because it would read as confidence and carry none. "
            "The single shipped search stands"
            + (", and pooling the versions is not adopted either." if not ensemble_better else ".")
        )
        if looked_true:
            consequence += (
                " What the sweep did find - that a small 5th percentile is breached far more often than a wide one - is fixed "
                "where it belongs: the tail widening now carries an absolute floor under narrow forecasts, tested out of sample."
            )
    stats = {k: float(v) for k, v in r.items() if k != "n" and isinstance(v, (int, float, np.floating)) and not (isinstance(v, float) and np.isnan(v))}
    return Study(key=KEY, title=TITLE, question=question, method=method, finding=finding, consequence=consequence, verdict=verdict, n=int(r["n"]), stats=stats)
