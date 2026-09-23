"""Does narrowing the search give a truer loss tail?

The desk lets a trader say "only earnings nights", and the answer that comes back is
often much worse than the unfiltered one: on TSLA, -10.7% against -3.3% for the 5th
percentile. That is a striking number, and a striking number is a claim. It could be
right - earnings nights are different, and averaging them in with ordinary nights hides
it - or it could be a small, noisy cohort producing a tail that is merely wider.

The two are separable, because a 5th percentile is a forecast and forecasts can be
scored. Take every past overnight hold where a condition was true. For each, compute the
5th percentile the desk would have given with and without narrowing, strictly from the
history before that moment, and see which one the real outcome respected. A tail that is
right is breached about 5% of the time; the pinball loss at 0.05 rewards being right
without being needlessly wide.

Both arms search the same pooled history with the same engine, so the only difference
between them is the condition. Significance is clustered by token, because forty nights
on one token are not forty independent facts.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.journal.calibration import wilson_interval
from nightwatch.journal.studies import NO, T_CONVINCING, UNCLEAR, YES, Study, _pinball, _t
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

KEY = "narrowing_gives_a_truer_tail"

# Conditions the study is run on. The rare ones are the ones a trader would actually ask
# for, and the ones where a small cohort could mislead; every qualifying moment is kept.
RARE = ("earnings_soon", "just_after_earnings", "earnings_this_week", "fomc_soon", "basis_stretched", "fresh_filing")
# Common ones are sampled, because they hold on a large share of nights and the question
# for them is whether narrowing changes anything at all.
COMMON = ("weekend", "high_volatility", "low_volatility", "thin_liquidity", "risk_off")

MIN_PAIRS = 30  # below this a condition is reported, not judged
MIN_TOKENS = 5  # a clustered t over fewer tokens than this is not a statistic


def collect(ctx: Any, *, common_per_ticker: int = 15, min_history_days: int = 120, lenses: tuple[str, ...] = RARE + COMMON) -> pd.DataFrame:  # noqa: ANN401
    """One row per (moment, condition) where the condition held, with both forecasts.

    Strictly point-in-time: the snapshot and both searched histories end before the
    moment; only the outcome looks forward. Moments are the first closed hour after
    each session, the same moments the calibration replay scores, so the horizon is the
    overnight hold the product is built around.
    """
    from nightwatch.analog import lens as lens_mod
    from nightwatch.analog.engine import AnalogEngine, pooled_history
    from nightwatch.analog.outcomes import compute_match_outcomes, structural_horizons
    from nightwatch.features.snapshot import InsufficientData, build_snapshot
    from nightwatch.journal.replay import closed_window_starts

    wanted = [x for x in lens_mod.resolve(list(lenses))]
    end_all = utc_now()
    frames: dict[str, pd.DataFrame] = {}
    for t in ctx.tickers_with_data():
        try:
            frames[t] = ctx.feature_frame(t, end_all)
        except InsufficientData as exc:
            log.info("lens study: no frame for %s (%s)", t, exc)
    if not frames:
        return pd.DataFrame()

    pooled = pooled_history(list(frames.items()))
    pooled_ns = pooled.index.values.astype("datetime64[ns]")
    engine = AnalogEngine(ctx.analog_config)
    floor = ctx.analog_config.min_matches * ctx.analog_config.min_separation_h
    rare_names = {x.name for x in wanted if x.name in RARE}

    def p5_of(res: Any, h: int) -> tuple[float | None, int]:  # noqa: ANN401
        rets = []
        for m in res.matches:
            mf = frames.get(m.ticker)
            if mf is None:
                continue
            try:
                o = compute_match_outcomes(mf, m.ts, fixed_h=(h,)).outcomes[f"{h}h"]
            except (KeyError, ValueError):
                continue
            if o.status == "MATURED" and o.ret_pct is not None:
                rets.append(o.ret_pct)
        if len(rets) < 15:
            return None, len(rets)
        return float(np.percentile(rets, 5)), len(rets)

    rows: list[dict] = []
    for ticker, frame in frames.items():
        start = frame.index[0].to_pydatetime() + timedelta(days=min_history_days)
        points = closed_window_starts(frame, start=start, end=end_all - timedelta(days=4))
        if not points:
            continue
        at_rows = frame.loc[[pd.Timestamp(p) for p in points if pd.Timestamp(p) in frame.index]]
        holds = {x.name: x.mask(at_rows).to_numpy() for x in wanted}
        rare_mask = np.zeros(len(at_rows), dtype=bool)
        for name in rare_names:
            rare_mask |= holds[name]
        common_idx = np.flatnonzero(~rare_mask)
        if len(common_idx) > common_per_ticker:
            common_idx = common_idx[np.linspace(0, len(common_idx) - 1, common_per_ticker).round().astype(int)]
        chosen = sorted(set(np.flatnonzero(rare_mask).tolist()) | set(common_idx.tolist()))

        spec = ctx.spec(ticker)
        for i in chosen:
            at = at_rows.index[i].to_pydatetime()
            names = [x for x in wanted if holds[x.name][i]]
            if not names:
                continue
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
            kw = {"query_ts": snap.bar_ts, "query_bucket": snap.labels.get("bucket"), "query_ticker": ticker}
            base = engine.search(hist, snap.features, **kw)
            if not base.ok:
                continue
            p5_all, n_all = p5_of(base, h)
            if p5_all is None:
                continue

            for x in names:
                narrowed, result = lens_mod.apply(hist, [x.name], min_rows=floor)
                row = {
                    "lens": x.name, "ticker": ticker, "as_of": at.isoformat(), "horizon_h": h,
                    "truth": float(truth.ret_pct), "p5_all": p5_all, "n_all": n_all,
                    "hours_left": result.n_after, "applied": bool(result.applied), "searched": False,
                    "p5_lens": None, "n_lens": 0,
                }
                if result.applied:
                    res = engine.search(narrowed, snap.features, **kw)
                    # Enough hours is not enough episodes. FOMC nights fall on the same
                    # dates for every token, so a thousand pooled hours can still be a
                    # dozen distinct events, and the engine refuses those as it should.
                    row["searched"] = bool(res.ok)
                    if res.ok:
                        row["p5_lens"], row["n_lens"] = p5_of(res, h)
                rows.append(row)
        log.info("lens study: %s done, %d rows so far", ticker, len(rows))
    return pd.DataFrame(rows)


def score(rows: pd.DataFrame) -> pd.DataFrame:
    """Per condition: how often each tail was breached, and whether narrowing scored better."""
    out = []
    if rows.empty:
        return pd.DataFrame()
    for name, g in rows.groupby("lens"):
        g = g.dropna(subset=["p5_lens"])
        n = len(g)
        all_rows = rows[rows["lens"] == name]
        rec: dict[str, Any] = {
            "lens": name, "n": n, "tokens": int(g["ticker"].nunique()) if n else 0,
            "asked": int(len(all_rows)),
            "too_few_hours": int((~all_rows["applied"]).sum()),
            "too_few_episodes": int((all_rows["applied"] & ~all_rows["searched"]).sum()),
        }
        if n:
            y = g["truth"].to_numpy()
            a, b = g["p5_all"].to_numpy(), g["p5_lens"].to_numpy()
            d = _pinball(y, a) - _pinball(y, b)  # positive = narrowing scored better
            per_token = pd.Series(d, index=g["ticker"].to_numpy()).groupby(level=0).mean()
            rec.update({
                "breach_all": float((y < a).mean()), "breach_lens": float((y < b).mean()),
                "p5_all_median": float(np.median(a)), "p5_lens_median": float(np.median(b)),
                "pinball_all": float(_pinball(y, a).mean()), "pinball_lens": float(_pinball(y, b).mean()),
                "t_clustered": _t(per_token.to_numpy()) if len(per_token) >= MIN_TOKENS else float("nan"),
                "better_tokens": int((per_token > 0).sum()),
            })
        out.append(rec)
    return pd.DataFrame(out).sort_values("n", ascending=False).reset_index(drop=True)


def _judge(r: pd.Series) -> str:
    if r["n"] < MIN_PAIRS or r["tokens"] < MIN_TOKENS or not np.isfinite(r.get("t_clustered", np.nan)):
        return UNCLEAR
    if r["t_clustered"] > T_CONVINCING:
        return YES
    if r["t_clustered"] < -T_CONVINCING:
        return NO
    return UNCLEAR


def study(rows: pd.DataFrame) -> Study:
    from nightwatch.analog.lens import BY_NAME

    table = score(rows)
    method = (
        "Every overnight hold since each token had 120 days of history where a condition was true at the close: the desk's "
        "5th percentile computed twice from the history before that moment, once from all past hours and once from only the "
        "hours where the condition also held, both from the same pooled engine. Scored against what the token actually did "
        "by the next open, on breach rate (target 5%) and pinball loss at 0.05, with significance clustered by token. Both arms "
        "are the raw retrieval, before the tail widening the desk applies, so they are compared on equal terms. Weekend and "
        "weeknight are not tested: every decision moment here is the close of a session."
    )
    if table.empty or int(table["n"].sum()) < MIN_PAIRS:
        return Study(
            key=KEY, title="Does narrowing the search give a truer loss tail?",
            question="When a trader asks for only the nights that look like tonight, is the tail that comes back more right, or only more dramatic?",
            method=method, finding="Too few scored moments to decide.", consequence="Nothing changes until there is enough to judge.",
            verdict=UNCLEAR, n=int(table["n"].sum()) if not table.empty else 0, stats={},
        )

    table["verdict"] = table.apply(_judge, axis=1)
    label = {n: BY_NAME[n].label for n in table["lens"]}
    better = table[table["verdict"] == YES]
    worse = table[table["verdict"] == NO]
    decided = len(better) + len(worse)

    def line(r: pd.Series) -> str:
        return (
            f"{label[r['lens']]}: breached {r['breach_lens']:.1%} narrowed against {r['breach_all']:.1%} unfiltered "
            f"(n={int(r['n'])}, {int(r['better_tokens'])} of {int(r['tokens'])} tokens better, t={r['t_clustered']:+.1f})"
        )

    if decided and len(worse) == 0:
        verdict = YES
    elif decided and len(better) == 0:
        verdict = NO
    else:
        verdict = UNCLEAR

    bits = []
    if len(better):
        bits.append("Narrowing scored better for " + "; ".join(line(r) for _, r in better.iterrows()) + ".")
    if len(worse):
        bits.append("It scored worse for " + "; ".join(line(r) for _, r in worse.iterrows()) + ".")
    undecided = table[table["verdict"] == UNCLEAR]
    # "Too few to judge" and "judged, no difference" are different answers. Folding a
    # 24-night result with t=+3.0 into "not separable" would understate it; calling it
    # a yes would be choosing the threshold after seeing the number. So it is named for
    # what it is, with its numbers, and left undecided.
    thin = undecided[(undecided["n"] < MIN_PAIRS) | (undecided["tokens"] < MIN_TOKENS)]
    flat = undecided.drop(thin.index)
    if len(flat):
        bits.append("No separable difference for " + ", ".join(
            f"{label[r['lens']]} (n={int(r['n'])}, t={r['t_clustered']:+.1f})" for _, r in flat.iterrows()
        ) + ".")
    shown_thin = thin[thin["n"] > 0]
    if len(shown_thin):
        bits.append(f"Too few nights to judge (under {MIN_PAIRS}) for " + "; ".join(
            f"{label[r['lens']]}: breached {r['breach_lens']:.1%} narrowed against {r['breach_all']:.1%} unfiltered, n={int(r['n'])}"
            for _, r in shown_thin.iterrows()
        ) + ".")
    finding = {YES: "Yes, where it could be decided. ", NO: "No. ", UNCLEAR: "Mixed. "}[verdict] + " ".join(bits)

    if len(worse):
        consequence = (
            "The conditions where narrowing scored worse are marked on the desk as making the tail less reliable, so a trader "
            "who asks for them sees that next to the answer: " + ", ".join(label[n] for n in worse["lens"]) + "."
        )
    elif len(better):
        consequence = (
            "The narrowed answer stands as the desk's answer when a trader asks for it. The conditions it could not be judged "
            "on are still offered, with the hour count beside them, because not having the evidence is not evidence against."
        )
    else:
        consequence = "Nothing is claimed for narrowing either way; the desk shows the narrowed answer only when asked for it."

    # The sweep also measured how often a condition could not be narrowed at all, and
    # one of those reasons was a bug: enough hours on too few separate dates used to
    # return no history section. That is fixed, and the count is why.
    episodes = table[table["too_few_episodes"] > 0].sort_values("too_few_episodes", ascending=False)
    if len(episodes):
        worst = episodes.iloc[0]
        consequence += (
            f" The sweep also found that {label[worst['lens']]} had enough past hours but too few separate dates on "
            f"{int(worst['too_few_episodes'])} of {int(worst['asked'])} nights, and the desk used to answer those with no history "
            f"at all. It now gives the unfiltered answer and says why."
        )

    stats: dict[str, float] = {"conditions_judged": float(decided), "conditions_better": float(len(better)), "conditions_worse": float(len(worse))}
    for _, r in table.iterrows():
        p = r["lens"]
        stats[f"{p}.n"] = float(r["n"])
        for k in ("breach_all", "breach_lens", "p5_all_median", "p5_lens_median", "t_clustered"):
            if k in r and pd.notna(r[k]):
                stats[f"{p}.{k}"] = float(r[k])
        if r["n"]:
            lo, hi = wilson_interval(int(round(r["breach_lens"] * r["n"])), int(r["n"]))
            stats[f"{p}.breach_lens_lo"], stats[f"{p}.breach_lens_hi"] = float(lo), float(hi)

    return Study(
        key=KEY,
        title="Does narrowing the search give a truer loss tail?",
        question=(
            "When a trader asks for only the nights that look like tonight - earnings nights, stretched basis, a fresh filing - "
            "the tail that comes back is often much worse than the unfiltered one. Is it more right, or only more dramatic?"
        ),
        method=method,
        finding=finding,
        consequence=consequence,
        verdict=verdict,
        n=int(table["n"].sum()),
        stats=stats,
    )
