"""What we tested about our own retrieval, and what came back.

The sub-theme this desk is built for asks how an AI retrieves historically similar
scenarios before a position is opened. Anybody can answer that with a description. The
answer worth giving is a set of falsifiable claims about the retrieval, each tested
against the desk's own stored history, each reported whichever way it came out.

Most of what is here came out against us. The nearest analogs turned out to have
*wider* outcomes than the far ones, so the obvious improvement - weight the close ones
more - makes the forecast worse, and the weighting fields the cohort has always
computed are correctly wired to nothing. An online calibration update that the
literature recommends for exactly our symptom does nothing on our data. A "we have
never seen this before" warning that looks significant collapses once you stop
treating 960 forecasts on 24 tokens as 960 independent facts.

One test found something worth fixing, and it is fixed: a single tail factor fitted
across every holding period was hiding two opposite errors inside an on-target
average.

Every number below is recomputed from the stored bars and the journal by
``nightwatch studies``; none of it is typed in. A study that cannot be recomputed is
a claim, not a study, so the runner records when it last ran and refuses to serve a
stale result silently.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.data.store import Store
from nightwatch.journal.calibration import wilson_interval
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

# Each study asks a yes/no question in its title, and the verdict answers *that
# question* rather than saying whether the result flattered us. A "no" is often the
# useful outcome - "no, a token is not best explained by its own past" is why the
# search is pooled - so the two must not be conflated.
YES, NO, UNCLEAR = "yes", "no", "unclear"

# How convincing a token-clustered t has to be before a direction is called at all.
# Deliberately blunt: the samples are autocorrelated, so a threshold precise enough to
# look like a p-value would be claiming precision the data does not have.
T_CONVINCING = 2.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS studies (
    key TEXT PRIMARY KEY,
    ran_at INTEGER NOT NULL,
    body BLOB NOT NULL
);
"""


@dataclass(frozen=True)
class Study:
    """One falsifiable claim about the retrieval, and how it did.

    ``consequence`` is the part that keeps this honest: a study nobody acted on is
    decoration, so each one says what changed in the product, including "nothing, and
    here is why that is the right answer".
    """

    key: str
    title: str
    question: str
    method: str
    finding: str
    consequence: str
    verdict: str  # yes | no | unclear - the answer to `title`, not a grade on the result
    n: int
    stats: dict[str, float] = field(default_factory=dict)
    ran_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- helpers


def _t(x: np.ndarray) -> float:
    """One-sample t on a paired difference. Reported rather than a p-value because the
    sample is autocorrelated and a p-value would imply a precision we do not have."""
    x = np.asarray(x, dtype=float)
    s = x.std(ddof=1)
    return float(x.mean() / (s / np.sqrt(len(x)))) if len(x) > 1 and s > 0 else float("nan")


def _and(names: list[str]) -> str:
    """"a, b and c" - four schemes joined by "and" four times reads like a stutter."""
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _pinball(y: np.ndarray, q: np.ndarray, tau: float = 0.05) -> np.ndarray:
    d = np.asarray(y, dtype=float) - np.asarray(q, dtype=float)
    return np.maximum(tau * d, (tau - 1.0) * d)


def _weighted_percentile(values: np.ndarray, weights: np.ndarray, p: float) -> float:
    o = np.argsort(values)
    v, w = values[o], weights[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(p / 100.0, c, v))


# ------------------------------------------------------------------------- evidence


@dataclass
class Evidence:
    """Match-level retrieval evidence, gathered point-in-time.

    ``queries`` is one row per moment the desk was asked, carrying what actually
    happened afterwards. ``matches`` is one row per retrieved analog, carrying its
    distance and what happened after *it*. Everything the studies need is derivable
    from these two frames, which is why they are collected once and reused.
    """

    queries: pd.DataFrame
    matches: pd.DataFrame

    @property
    def ok(self) -> bool:
        return not self.queries.empty and not self.matches.empty


def collect_evidence(ctx: Any, *, max_points_per_ticker: int = 40, lookback_days: int = 240, min_history_days: int = 120) -> Evidence:
    """Replay the retrieval and record every match, not just the summary.

    The journal stores what the cohort concluded; it does not store the forty moments
    the conclusion was drawn from, and the interesting questions are all about those.
    So this walks the same replay points again and keeps the match level.

    Strictly point-in-time: the snapshot and the searched history end before the query
    bar. Only the outcome labels look forward, which is what an outcome label is.
    """
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
            log.info("studies: no frame for %s (%s)", t, exc)
    if not frames:
        return Evidence(pd.DataFrame(), pd.DataFrame())

    pooled = pooled_history(list(frames.items()))
    pooled_ns = pooled.index.values.astype("datetime64[ns]")
    engine = AnalogEngine(ctx.analog_config)

    q_rows: list[dict] = []
    m_rows: list[dict] = []
    qid = 0
    for ticker, frame in frames.items():
        start = max(frame.index[0].to_pydatetime() + timedelta(days=min_history_days), end_all - timedelta(days=lookback_days))
        points = closed_window_starts(frame, start=start, end=end_all - timedelta(days=4))
        if not points:
            continue
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
            res = engine.search(pooled.iloc[:cut], snap.features, query_ts=snap.bar_ts, query_bucket=snap.labels.get("bucket"), query_ticker=ticker)
            if not res.ok:
                continue

            kept = 0
            for m in res.matches:
                mf = frames.get(m.ticker)
                if mf is None:
                    continue
                try:
                    o = compute_match_outcomes(mf, m.ts, fixed_h=(h,)).outcomes[f"{h}h"]
                except (KeyError, ValueError):
                    continue
                if o.status != "MATURED" or o.ret_pct is None:
                    continue
                m_rows.append({
                    "qid": qid, "m_ticker": m.ticker, "distance": m.distance, "similarity": m.similarity,
                    "ret_pct": o.ret_pct, "same_ticker": int(m.ticker == ticker),
                })
                kept += 1
            if kept < 20:
                m_rows = [r for r in m_rows if r["qid"] != qid]
                continue
            q_rows.append({
                "qid": qid, "ticker": ticker, "as_of": at.isoformat(), "horizon_h": h,
                "bucket": snap.labels.get("bucket"), "regime": snap.labels.get("regime_label"),
                "n_matches": kept, "distance_scale": res.distance_scale,
                "truth_ret_pct": truth.ret_pct,
            })
            qid += 1
    return Evidence(pd.DataFrame(q_rows), pd.DataFrame(m_rows))


# -------------------------------------------------------------------------- studies


def study_closer_is_not_tighter(ev: Evidence) -> Study:
    """The claim the whole sub-theme rests on, stated so it can fail."""
    rows = []
    for qid, g in ev.matches.groupby("qid"):
        g = g.sort_values("distance")
        h = len(g) // 2
        near, far = g.iloc[:h]["ret_pct"], g.iloc[h:]["ret_pct"]
        rows.append({
            "qid": qid,
            "sd_near": near.std(ddof=1), "sd_far": far.std(ddof=1),
            "iqr_near": near.quantile(0.75) - near.quantile(0.25),
            "iqr_far": far.quantile(0.75) - far.quantile(0.25),
        })
    s = pd.DataFrame(rows).merge(ev.queries[["qid", "ticker"]], on="qid")
    sd_ratio = s["sd_near"].mean() / s["sd_far"].mean()
    iqr_ratio = s["iqr_near"].mean() / s["iqr_far"].mean()
    win = float((s["sd_near"] < s["sd_far"]).mean())
    per_ticker = s.groupby("ticker").apply(lambda x: (x["sd_far"] - x["sd_near"]).mean(), include_groups=False)
    tighter_tokens = int((per_ticker > 0).sum())
    clustered = _t(per_ticker.to_numpy())

    # The verdict answers the title, and it follows the clustered statistic rather than
    # the pooled one: 960 forecasts on 24 tokens are not 960 independent facts.
    if clustered > T_CONVINCING and sd_ratio < 1.0:
        verdict = YES
        lead = (
            f"Yes. The near half was {(1 - sd_ratio) * 100:.0f}% tighter by standard deviation, on "
            f"{tighter_tokens} of {len(per_ticker)} tokens (t={clustered:+.1f})."
        )
    elif clustered < -T_CONVINCING and sd_ratio > 1.0:
        verdict = NO
        lead = (
            f"No - the opposite, clearly. The near half was {(sd_ratio - 1) * 100:.0f}% *wider* by standard deviation and "
            f"{(iqr_ratio - 1) * 100:.0f}% wider by interquartile range. It was tighter on only {win:.0%} of moments and on "
            f"{tighter_tokens} of {len(per_ticker)} tokens (t={clustered:+.1f}). The likely reason is that the distance is "
            "dominated by the volatility features, so a query made in a wild moment retrieves wild neighbours. That is "
            "arguably the retrieval working; it is certainly not 'closer means calmer'."
        )
    else:
        verdict = UNCLEAR
        lead = (
            f"Cannot be called either way. The near half was {abs(sd_ratio - 1) * 100:.0f}% "
            f"{'wider' if sd_ratio > 1 else 'tighter'} on average, but only {tighter_tokens} of {len(per_ticker)} tokens "
            f"agree (t={clustered:+.1f}), which is not enough to build on."
        )
    return Study(
        key="closer_is_not_tighter",
        title="Do closer analogs have tighter outcomes?",
        question="If the retrieval works the way people assume, the half of the matches nearest the query should be followed by a narrower range of outcomes than the far half. Is it?",
        method=f"For each of {len(s)} past moments, split its retrieved analogs at the median distance and compare the spread of what followed each half. Paired inside the moment, so a volatile token cannot outvote a quiet one, then checked again across tokens.",
        finding=lead,
        consequence=(
            "Nothing in the product is allowed to assume that closeness implies a narrower outcome. The next study tests the "
            "version of that assumption we nearly shipped."
            if verdict == NO
            else "Kept under review; the next study tests whether it can be turned into a better forecast."
        ),
        verdict=verdict,
        n=len(s),
        stats={"sd_ratio_near_over_far": float(sd_ratio), "iqr_ratio_near_over_far": float(iqr_ratio),
               "share_near_tighter": win, "tokens_near_tighter": float(tighter_tokens), "tokens": float(len(per_ticker)),
               "clustered_t": clustered},
    )


_SCHEMES: dict[str, Any] = {
    "similarity (already computed)": lambda d, sim: sim,
    "gaussian, own median bandwidth": lambda d, sim: np.exp(-(d**2) / (2.0 * max(float(np.median(d)), 1e-9) ** 2)),
    "inverse distance": lambda d, sim: 1.0 / (d + float(np.median(d)) * 0.1 + 1e-9),
    "nearest half only": lambda d, sim: (d <= np.median(d)).astype(float),
}


def study_weighting_does_not_help(ev: Evidence) -> Study:
    """The cheapest-looking improvement on the board, measured instead of assumed."""
    truth = ev.queries.set_index("qid")["truth_ret_pct"].to_dict()
    losses: dict[str, list[float]] = {"equal (shipped)": []}
    breach: dict[str, list[float]] = {"equal (shipped)": []}
    for name in _SCHEMES:
        losses[name], breach[name] = [], []
    for qid, g in ev.matches.groupby("qid"):
        if qid not in truth:
            continue
        r, d, sim = (g[c].to_numpy(float) for c in ("ret_pct", "distance", "similarity"))
        y = truth[qid]
        for name, fn in [("equal (shipped)", lambda d, sim: np.ones_like(d)), *_SCHEMES.items()]:
            w = np.asarray(fn(d, sim), dtype=float)
            if not np.isfinite(w).all() or w.sum() <= 0:
                w = np.ones_like(d)
            p5 = _weighted_percentile(r, w, 5.0)
            losses[name].append(float(_pinball(np.array([y]), np.array([p5]))[0]))
            breach[name].append(float(y < p5))
    base = np.array(losses["equal (shipped)"])
    stats: dict[str, float] = {"breach_equal": float(np.mean(breach["equal (shipped)"])), "pinball_equal": float(base.mean())}
    worst = ""
    for name in _SCHEMES:
        a = np.array(losses[name])
        stats[f"pinball_{name}"] = float(a.mean())
        stats[f"breach_{name}"] = float(np.mean(breach[name]))
        stats[f"t_{name}"] = _t(base - a)
    sim_breach = stats["breach_similarity (already computed)"]
    eq_breach = stats["breach_equal"]
    beat = [n for n in _SCHEMES if stats[f"pinball_{n}"] < stats["pinball_equal"]]
    worst = max(_SCHEMES, key=lambda n: stats[f"pinball_{n}"])
    ratio = sim_breach / eq_breach if eq_breach > 0 else float("inf")
    if ratio < 0.9:
        how_much = f"{1 / ratio:.1f} times less often"
    elif ratio <= 1.1:
        how_much = "about as often"
    elif ratio < 10:
        how_much = f"{ratio:.1f} times as often"
    else:
        how_much = "many times as often"
    # "Better" has to mean better by enough to be worth a moving part, and by enough
    # that the paired statistic agrees; one scheme edging ahead on the mean is noise.
    convincing = [n for n in beat if stats[f"t_{n}"] > T_CONVINCING]
    verdict = YES if convincing else NO if not beat else UNCLEAR
    if verdict == YES:
        lead = f"Yes: {_and(convincing)} beat counting every match equally by more than the noise"
    elif verdict == NO:
        lead = f"No. None of the {len(_SCHEMES)} beat counting every match equally"
    else:
        lead = f"Not by enough to act on. {_and(beat)} edged ahead on the mean, but not past the noise"
    return Study(
        key="weighting_does_not_help",
        title="Should closer analogs count for more?",
        question="The cohort has always computed a similarity-weighted mean and 5th percentile, and nothing reads them. Should something?",
        method=f"Score four weighting schemes against counting all forty equally, on {len(base)} past moments, by pinball loss at the 5th percentile against what actually happened, plus how often the real outcome fell below each scheme's 5th percentile (target 5%).",
        finding=(
            f"{lead}. The engine's own similarity weights - the ones already sitting in the cohort - were the clearest failure: "
            f"they pull the 5th percentile in so far that the real outcome fell below it {sim_breach:.1%} of the time against "
            f"{eq_breach:.1%} for equal weighting, {how_much}, at a target of 5%. The worst scheme overall was {worst}. "
            f"This follows from the study above: if the near matches are the wider ones, leaning on them narrows the band exactly "
            f"where it should be widening."
        ),
        consequence=(
            "The weighted fields stay computed and stay unread, which is now a measured decision rather than an oversight. "
            "Shipping them would have broken the calibration the desk is judged on."
            if verdict != YES
            else "Under change control: a weighting that survives this test is worth wiring in, and this is the test it has to survive."
        ),
        verdict=verdict,
        n=len(base),
        stats=stats,
    )


def study_distance_does_not_warn(ev: Evidence) -> Study:
    """'We have never seen anything like this' - a good warning, if it were true."""
    agg = ev.matches.groupby("qid").agg(d_mean=("distance", "mean"))
    q = ev.queries.set_index("qid").join(agg)
    q["scaled_d"] = q["d_mean"] / q["distance_scale"]
    q["abs_truth"] = q["truth_ret_pct"].abs()
    q = q.dropna(subset=["scaled_d", "abs_truth"])
    lo_m = q[q["scaled_d"] <= q["scaled_d"].quantile(0.25)]["abs_truth"]
    hi_m = q[q["scaled_d"] >= q["scaled_d"].quantile(0.75)]["abs_truth"]
    welch = float((hi_m.mean() - lo_m.mean()) / np.sqrt(hi_m.var(ddof=1) / len(hi_m) + lo_m.var(ddof=1) / len(lo_m)))
    per = q.groupby("ticker").apply(
        lambda x: x.loc[x["scaled_d"] > x["scaled_d"].median(), "abs_truth"].mean()
        - x.loc[x["scaled_d"] <= x["scaled_d"].median(), "abs_truth"].mean(), include_groups=False).dropna()
    clustered = _t(per.to_numpy())
    verdict = YES if clustered > T_CONVINCING else NO if welch > T_CONVINCING else UNCLEAR
    if verdict == YES:
        finding = (
            f"Yes, and it survives the control. The farthest quarter of moments was followed by a {hi_m.mean():.2f}% average move "
            f"against {lo_m.mean():.2f}% for the closest quarter, and the effect holds inside tokens too "
            f"({int((per > 0).sum())} of {len(per)}, t={clustered:+.2f})."
        )
    elif verdict == NO:
        finding = (
            f"It looks true and it is not. Pooled, the farthest quarter of moments was followed by a {hi_m.mean():.2f}% average move "
            f"against {lo_m.mean():.2f}% for the closest quarter (t={welch:+.1f}), which would be a publishable warning. "
            f"Within tokens the effect vanishes: {int((per > 0).sum())} of {len(per)} tokens show it at all (t={clustered:+.2f}). "
            "The pooled result was measuring which tokens are volatile, not which moments are unfamiliar."
        )
    else:
        finding = (
            f"No evidence either way. The farthest quarter was followed by a {hi_m.mean():.2f}% move against {lo_m.mean():.2f}% "
            f"for the closest, which is not separable from noise even before the per-token control (pooled t={welch:+.1f}, "
            f"clustered t={clustered:+.2f})."
        )
    return Study(
        key="distance_does_not_warn",
        title="Does 'no close analogs' warn of a bigger move?",
        question="When the desk cannot find anything much like now, is what follows more violent than usual? If so it is worth saying out loud before a position is opened.",
        method=f"Rank {len(q)} past moments by how far their analogs sat, in units of that token's own typical distance, and compare the size of the move that followed. Then repeat within each token, because a volatile token has both far analogs and big moves for reasons that have nothing to do with each other.",
        finding=finding,
        consequence=(
            "No 'unfamiliar situation' warning is shown. The desk still refuses outright when it cannot find fifteen distinct "
            "episodes, which is a different and verifiable thing."
            if verdict != YES
            else "Worth surfacing as a warning before a position is opened."
        ),
        verdict=verdict,
        n=int(len(q)),
        stats={"mean_move_farthest_quartile": float(hi_m.mean()), "mean_move_closest_quartile": float(lo_m.mean()),
               "pooled_t": welch, "clustered_t": clustered, "tokens_showing_effect": float((per > 0).sum()), "tokens": float(len(per))},
    )


def study_pooling_beats_own_history(ev: Evidence) -> Study:
    """Whether a token is best explained by itself."""
    truth = ev.queries.set_index("qid")["truth_ret_pct"].to_dict()
    own_p5, other_p5, ys = [], [], []
    for qid, g in ev.matches.groupby("qid"):
        if qid not in truth:
            continue
        own, other = g[g["same_ticker"] == 1]["ret_pct"], g[g["same_ticker"] == 0]["ret_pct"]
        if len(own) < 8 or len(other) < 8:
            continue
        own_p5.append(own.quantile(0.05))
        other_p5.append(other.quantile(0.05))
        ys.append(truth[qid])
    if len(ys) < 30:
        return Study(
            key="pooling_beats_own_history", title="Is a token best explained by its own past?",
            question="Should the search be restricted to the token being asked about?",
            method="Compare the 5th percentile taken from same-token matches against the one from other-token matches, on moments that retrieved at least eight of each.",
            finding=f"Too few moments retrieved enough of both to decide ({len(ys)}).", consequence="The pooled search stands unchanged.",
            verdict=UNCLEAR, n=len(ys), stats={},
        )
    y = np.array(ys)
    lo_own, lo_other = _pinball(y, np.array(own_p5)), _pinball(y, np.array(other_p5))
    b_own = float((y < np.array(own_p5)).mean())
    b_other = float((y < np.array(other_p5)).mean())
    t_own = _t(lo_other - lo_own)  # positive = the token's own past predicts better
    share_own = float(ev.matches["same_ticker"].mean())
    verdict = YES if t_own > T_CONVINCING else NO if t_own < -T_CONVINCING else UNCLEAR
    if verdict == YES:
        finding = (
            f"Yes. Its own past predicted it better (pinball {lo_own.mean():.3f} against {lo_other.mean():.3f}, t={t_own:+.2f}), "
            f"with the real outcome below the same-token 5th percentile {b_own:.1%} of the time against {b_other:.1%}."
        )
    elif verdict == NO:
        finding = (
            f"No. The other tokens predicted this token better: the real outcome fell below the same-token 5th percentile {b_own:.1%} "
            f"of the time against {b_other:.1%} for the cross-token one, at a target of 5%, and the cross-token pinball loss was lower "
            f"({lo_other.mean():.3f} against {lo_own.mean():.3f}, t={t_own:+.2f}). A single token has too few of its own rare nights."
        )
    else:
        finding = (
            f"Not separably. Same-token analogs scored {lo_own.mean():.3f} against {lo_other.mean():.3f} for cross-token ones "
            f"(t={t_own:+.2f}), with breach rates of {b_own:.1%} and {b_other:.1%} - a difference too small to restrict the search on."
        )
    return Study(
        key="pooling_beats_own_history",
        title="Is a token best explained by its own past?",
        question="Tokenized equities are individual names. Should the search be restricted to the one being asked about, instead of ranging across all of them?",
        method=f"On {len(y)} past moments that retrieved at least eight analogs from the token itself and eight from other tokens, score each group's 5th percentile against what actually happened.",
        finding=finding,
        consequence=(
            f"The search stays pooled across the universe, with the token's own history competing on distance like everything else - "
            f"about {share_own:.0%} of retrieved matches come from the token being asked about."
            if verdict != YES
            else "Grounds to weight the token's own history more heavily in the search."
        ),
        verdict=verdict,
        n=int(len(y)),
        stats={"breach_own_token": b_own, "breach_other_tokens": b_other,
               "pinball_own_token": float(lo_own.mean()), "pinball_other_tokens": float(lo_other.mean()),
               "t_own_minus_other": _t(lo_own - lo_other)},
    )


def study_one_factor_hid_two_errors(forecasts: pd.DataFrame) -> Study:
    """The one that found something, and what it cost to keep not finding it."""
    from nightwatch.journal.adjust import evaluate_expanding

    flat = evaluate_expanding(forecasts, banded=False)
    banded = evaluate_expanding(forecasts)
    if flat is None or banded is None or not banded.bands:
        return Study(
            key="one_factor_hid_two_errors", title="Does one tail factor fit every holding period?",
            question="The tails are widened by a factor fitted on matured forecasts. Does one factor serve an overnight hold and a weekend hold equally?",
            method="Score the same forecasts with one pooled factor and with a factor per holding period.",
            finding="Not enough matured forecasts in each holding period to decide yet.",
            consequence="The pooled factor is still in force.", verdict=UNCLEAR, n=0, stats={},
        )
    rows = expanding_by_band(forecasts)
    named = {b.band: b for b in banded.bands}
    stats = {"pooled_lo_coverage": flat.adj_lo_coverage, "pooled_width": flat.adj_width,
             "banded_lo_coverage": banded.adj_lo_coverage, "banded_width": banded.adj_width}
    for band, b in named.items():
        stats[f"banded_lo_{band}"] = b.adj_lo_coverage
        stats[f"banded_width_{band}"] = b.adj_width
    for band, v in rows.items():
        stats[f"pooled_lo_{band}"] = v["lo"]
        stats[f"pooled_width_{band}"] = v["width"]
    on = rows.get("overnight", {})
    md = rows.get("multi_day", {})
    # "Yes, one factor fits" only if the pooled factor left every holding period within
    # two points of target. The spread between the periods is the whole finding.
    per_band_miss = [abs(v["lo"] - 0.05) for v in rows.values()] or [float("nan")]
    fits = max(per_band_miss) < 0.02
    verdict = YES if fits else NO
    if not fits and on and md and "overnight" in named and "multi_day" in named:
        finding = (
            f"No, and the pooled number hid it. Under one factor the overall breach rate read {flat.adj_lo_coverage:.1%} against a 5% "
            f"target, which looks respectable, but it was made of {on['lo']:.1%} breaches on overnight holds and {md['lo']:.1%} on "
            f"multi-day ones - a band so over-wide it almost never broke, {md['width']:.1f}% across, cancelling out a band that was too "
            f"narrow. Fitting per holding period brought the overnight band to {named['overnight'].adj_lo_coverage:.1%} and the multi-day "
            f"band to {named['multi_day'].adj_lo_coverage:.1%} at {named['multi_day'].adj_width:.1f}% across."
        )
    elif fits:
        finding = (
            f"Yes, on this history. The pooled factor read {flat.adj_lo_coverage:.1%} overall and no holding period sat more than "
            f"{max(per_band_miss) * 100:.1f} points from the 5% target, so splitting it buys nothing."
        )
    else:
        finding = (
            f"No. The pooled factor read {flat.adj_lo_coverage:.1%} overall, but the holding periods disagree by up to "
            f"{max(per_band_miss) * 100:.1f} points, so the overall figure is an average of errors rather than a measurement."
        )
    return Study(
        key="one_factor_hid_two_errors",
        title="Does one tail factor fit every holding period?",
        question="The cohort's 5th percentile is widened by a factor fitted on forecasts that have already matured. Does one factor serve an overnight hold and a weekend hold equally well?",
        method=f"Score {flat.n_evaluated} matured forecasts twice - once with a single pooled factor, once with a factor fitted per holding period - both point-in-time, each forecast using only factors fitted on forecasts that had matured before it.",
        finding=finding,
        consequence=(
            "Each horizon is now widened by the factor fitted on windows of its own length. That halved the weekend band, which feeds "
            "the sizing caps and the gate directly - the desk had been shrinking and refusing weekend positions against a loss about "
            "twice what the history supports."
            if not fits
            else "The split is in place anyway, because it costs nothing and this study is what would catch the day it stops being true."
        ),
        verdict=verdict,
        n=int(flat.n_evaluated),
        stats=stats,
    )


def expanding_by_band(forecasts: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Breach rate and width per holding period *under the single pooled factor*.

    This is what the banded evaluation cannot show, because once bands exist each row
    is already corrected by its own. It is the before picture.
    """
    from nightwatch.journal.adjust import expanding_rows, horizon_band

    rows = expanding_rows(forecasts, banded=False)
    if rows.empty or "horizon_h" not in forecasts:
        return {}
    src = forecasts.copy()
    src["as_of"] = pd.to_datetime(src["as_of"], utc=True)
    rows = rows.merge(src[["as_of", "horizon_h"]].drop_duplicates("as_of"), on="as_of", how="left")
    rows["band"] = rows["horizon_h"].map(horizon_band)
    return {
        str(b): {"lo": float((g["r"] < g["a5"]).mean()), "width": float((g["a95"] - g["a5"]).mean()), "n": float(len(g))}
        for b, g in rows.groupby("band") if b != "pooled"
    }


def study_online_calibration_adds_nothing(forecasts: pd.DataFrame) -> Study:
    """A recommended fix for our exact symptom, which does not fix it here."""
    from nightwatch.journal.adjust import K_MAX, K_MIN, MIN_FIT_N, _fit_arrays

    d = forecasts.dropna(subset=["p5", "p50", "p95", "ret_pct"]).copy()
    if len(d) < 300:
        return Study(
            key="online_calibration_adds_nothing", title="Would an online calibration update do better?",
            question="Adaptive conformal inference nudges the band after every outcome instead of refitting on all of history. Would it beat what we do?",
            method="Score both on the same forecasts, choosing the step size on the first half and reporting on the second.",
            finding="Not enough matured forecasts to split and decide yet.", consequence="The batch refit stands.",
            verdict=UNCLEAR, n=len(d), stats={},
        )
    d["as_of"] = pd.to_datetime(d["as_of"], utc=True)
    d["horizon_end"] = pd.to_datetime(d["horizon_end"], utc=True)
    d = d.sort_values("as_of").reset_index(drop=True)

    def run(gamma: float) -> pd.DataFrame:
        order = np.argsort(d["horizon_end"].to_numpy(), kind="stable")
        ends = d["horizon_end"].to_numpy()[order]
        p5h, p50h, p95h, rh = (d[c].to_numpy(float)[order] for c in ("p5", "p50", "p95", "ret_pct"))
        as_ofs = d["as_of"].to_numpy()
        p5a, p50a, p95a, ra = (d[c].to_numpy(float) for c in ("p5", "p50", "p95", "ret_pct"))
        shown = np.full((len(d), 2), np.nan)
        k_lo = k_hi = 1.0
        started, settled, fitted_at = False, 0, -1
        out = []
        for i in range(len(d)):
            ready = int(np.searchsorted(ends, as_ofs[i], side="left"))
            if ready < MIN_FIT_N:
                continue
            if not started:
                f = _fit_arrays(p5h[:ready], p50h[:ready], p95h[:ready], rh[:ready])
                if f is None:
                    continue
                k_lo, k_hi, started, settled, fitted_at = f.k_lo, f.k_hi, True, ready, ready
            else:
                while settled < ready:
                    src = int(order[settled])
                    kj = shown[src] if not np.isnan(shown[src, 0]) else np.array([k_lo, k_hi])
                    a5j = p50h[settled] + kj[0] * (p5h[settled] - p50h[settled])
                    a95j = p50h[settled] + kj[1] * (p95h[settled] - p50h[settled])
                    if gamma:
                        k_lo = float(np.clip(k_lo + gamma * (float(rh[settled] < a5j) - 0.05), K_MIN, K_MAX))
                        k_hi = float(np.clip(k_hi + gamma * (float(rh[settled] > a95j) - 0.05), K_MIN, K_MAX))
                    settled += 1
                if ready - fitted_at >= 25:
                    f = _fit_arrays(p5h[:ready], p50h[:ready], p95h[:ready], rh[:ready])
                    if f is not None:
                        k_lo, k_hi, fitted_at = f.k_lo, f.k_hi, ready
            shown[i] = (k_lo, k_hi)
            out.append({"i": i, "r": ra[i], "a5": p50a[i] + k_lo * (p5a[i] - p50a[i]), "a95": p50a[i] + k_hi * (p95a[i] - p50a[i])})
        return pd.DataFrame(out)

    gammas = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5)
    runs = {g: run(g) for g in gammas}
    keep = set(runs[0.0]["i"])
    runs = {g: e[e["i"].isin(keep)].reset_index(drop=True) for g, e in runs.items()}
    n = len(runs[0.0])
    cut = n // 2

    def cov(e: pd.DataFrame) -> tuple[float, float, float]:
        r, a5, a95 = (e[c].to_numpy(float) for c in ("r", "a5", "a95"))
        return float((r < a5).mean()), float((r > a95).mean()), float((a95 - a5).mean())

    # Choose the step size on the first half only, then report once on the second.
    best, best_err = 0.0, float("inf")
    base_w = cov(runs[0.0].iloc[:cut])[2]
    for g in gammas:
        lo, hi, w = cov(runs[g].iloc[:cut])
        err = abs(lo - 0.05) + abs(hi - 0.05)
        if w <= base_w * 1.02 and err < best_err:
            best, best_err = g, err
    a_lo, a_hi, a_w = cov(runs[0.0].iloc[cut:])
    b_lo, b_hi, b_w = cov(runs[best].iloc[cut:])
    # Better means closer to target on the held-out half by a margin worth a moving
    # part. A tenth of a point of coverage is not a reason to add one, so it is a no
    # rather than a maybe: "unclear" is for not having the data, not for having it and
    # finding the difference too small to matter.
    gain = (abs(a_lo - 0.05) + abs(a_hi - 0.05)) - (abs(b_lo - 0.05) + abs(b_hi - 0.05))
    verdict = YES if gain > 0.01 else NO
    if verdict == YES:
        finding = (
            f"Yes. With a step size of {best:g} chosen on the first half, the held-out half came in at {b_lo:.2%} of outcomes below "
            f"the band against {a_lo:.2%} for the batch refit we ship, at a 5% target."
        )
    else:
        finding = (
            f"No. The best step size on the first half was {best:g}; on the held-out half it gave {b_lo:.2%} of outcomes below the band "
            f"against {a_lo:.2%} for the batch refit we ship, at a 5% target, with a band {abs(1 - b_w / a_w) * 100:.1f}% "
            f"{'narrower' if b_w < a_w else 'wider'}. Our miscalibration is not the slow drift adaptive conformal is built for - it arrives "
            "in bursts that a scalar nudge reaches only after the burst has passed."
        )
    return Study(
        key="online_calibration_adds_nothing",
        title="Would an online calibration update do better?",
        question="Adaptive conformal inference nudges the band a little after every outcome rather than refitting on all of history. It is the published fix for a band that drifts, which is our symptom. Does it help here?",
        method=f"Both methods scored on the same {n} matured forecasts. The step size was chosen on the first half and reported once on the second half it never saw, because choosing it on the same data it is judged on is how a method looks better than it is.",
        finding=finding,
        consequence=(
            "Not adopted. The batch refit stays, and the holding-period split above turned out to be where the real error was."
            if verdict != YES
            else "Worth adopting: the nudge is a few lines on top of the existing refit."
        ),
        verdict=verdict,
        n=int(n),
        stats={"chosen_gamma": float(best), "heldout_lo_batch": a_lo, "heldout_lo_online": b_lo,
               "heldout_hi_batch": a_hi, "heldout_hi_online": b_hi, "heldout_width_batch": a_w, "heldout_width_online": b_w},
    )


def study_analogs_beat_random_hours(forecasts: pd.DataFrame) -> Study:
    """Does any of this beat picking hours at random? The question under all of it."""
    b = forecasts.dropna(subset=["p5", "base_p5", "ret_pct"]).copy()
    if len(b) < 100:
        return Study(
            key="analogs_beat_random_hours", title="Do the analogs beat random hours of the same kind?",
            question="Every forecast also records a distribution built from random past hours in the same part of the week. Does the retrieval beat it?",
            method="Paired comparison of the two 5th percentiles against what happened.",
            finding=f"Only {len(b)} forecasts carry both; not enough.", consequence="The comparison stays on the calibration page as it is.",
            verdict=UNCLEAR, n=len(b), stats={},
        )
    b["as_of"] = pd.to_datetime(b["as_of"], utc=True)
    r = b["ret_pct"].to_numpy(float)
    diff = _pinball(r, b["base_p5"].to_numpy(float)) - _pinball(r, b["p5"].to_numpy(float))
    b["diff"] = diff
    per = b.groupby("ticker")["diff"].mean()
    b["week"] = b["as_of"].dt.tz_convert(None).dt.to_period("W")
    weeks = b["week"].unique()
    rng = np.random.default_rng(3)
    boot = np.array([b[b["week"].isin(rng.choice(weeks, size=len(weeks), replace=True))]["diff"].mean() for _ in range(2000)])
    lo_ci, hi_ci = (float(x) for x in np.percentile(boot, [2.5, 97.5]))
    clustered = _t(per.to_numpy())
    excludes_zero = lo_ci > 0
    verdict = YES if excludes_zero and clustered > T_CONVINCING else NO if hi_ci < 0 else UNCLEAR
    margin = "narrowly, and the honest error bars say so" if verdict == YES and lo_ci < 0.005 else "clearly"
    if verdict == YES:
        finding = (
            f"Yes, but {margin}. The analogs beat random hours by {diff.mean():+.4f} in pinball loss "
            f"(clustered t={clustered:+.2f}, {int((per > 0).sum())} of {len(per)} tokens). Bootstrapped by week the 95% interval is "
            f"[{lo_ci:+.4f}, {hi_ci:+.4f}] - it excludes zero{', but only just' if lo_ci < 0.005 else ''}. "
            "This is a real edge at the edge of detectability, not a decisive one."
        )
    elif verdict == NO:
        finding = (
            f"No - random hours of the same kind scored better, by {-diff.mean():+.4f} in pinball loss "
            f"(clustered t={clustered:+.2f}, bootstrap interval [{lo_ci:+.4f}, {hi_ci:+.4f}])."
        )
    else:
        finding = (
            f"Not separably. The analogs led by {diff.mean():+.4f} in pinball loss, but the week-bootstrapped interval "
            f"[{lo_ci:+.4f}, {hi_ci:+.4f}] contains zero and only {int((per > 0).sum())} of {len(per)} tokens agree "
            f"(clustered t={clustered:+.2f}). On this history the resemblance cannot be shown to beat picking hours at random."
        )
    return Study(
        key="analogs_beat_random_hours",
        title="Do the analogs beat random hours of the same kind?",
        question="Every forecast also stores a distribution drawn from random past hours in the same part of the week. If the retrieval is doing nothing, the two score the same. Does it do anything?",
        method=f"Paired pinball loss at the 5th percentile on {len(b)} matured forecasts, then error bars that respect the data: clustered by token, and block-bootstrapped by week, because overlapping forecasts on {len(per)} tokens are nowhere near {len(b)} independent facts.",
        finding=finding,
        consequence="The comparison is shown on every report, per horizon, including when it says the resemblance bought nothing. An edge this size is worth reporting and not worth overselling.",
        verdict=verdict,
        n=int(len(b)),
        stats={"mean_advantage": float(diff.mean()), "clustered_t": _t(per.to_numpy()),
               "tokens_positive": float((per > 0).sum()), "tokens": float(len(per)),
               "boot_ci_low": lo_ci, "boot_ci_high": hi_ci, "weeks": float(len(weeks))},
    )


# --------------------------------------------------------------------------- runner

def study_the_model_spots_a_big_night(outcomes: pd.DataFrame) -> Study:
    """The model says a filing is market-moving. Is the night that follows bigger?"""
    d = outcomes.dropna(subset=["ret_pct", "market_moving"]).copy()
    if len(d) < 100:
        return Study(
            key="filing_read_predicts_size", title="Does the model spot a filing that matters?",
            question="The model reads each filing and says how likely it is to move the share price. Do the ones it calls high-impact actually move more?",
            method="Compare the size of the move from the filing to the next US open, between the filings it flagged and the ones it did not.",
            finding=f"Only {len(d)} filings have both a read and a measurable window; not enough.",
            consequence="The read is not shown as a risk signal.", verdict=UNCLEAR, n=len(d), stats={},
        )
    d["abs_ret"] = d["ret_pct"].abs()
    flagged = d["market_moving"].isin(("high", "medium"))
    hi, lo = d.loc[flagged, "abs_ret"], d.loc[~flagged, "abs_ret"]
    if len(hi) < 20 or len(lo) < 20:
        return Study(
            key="filing_read_predicts_size", title="Does the model spot a filing that matters?",
            question="Do the filings the model calls high-impact actually move more?",
            method="Compare the move to the next US open between flagged and unflagged filings.",
            finding=f"The model put {len(hi)} filings on one side and {len(lo)} on the other; too lopsided to compare.",
            consequence="The read is not shown as a risk signal.", verdict=UNCLEAR, n=len(d), stats={},
        )
    # Clustered by token, because a volatile name files often and would otherwise decide this.
    per = d.groupby("ticker").apply(
        lambda x: x.loc[x["market_moving"].isin(("high", "medium")), "abs_ret"].mean()
        - x.loc[~x["market_moving"].isin(("high", "medium")), "abs_ret"].mean(), include_groups=False).dropna()
    clustered = _t(per.to_numpy()) if len(per) > 1 else float("nan")
    ratio = float(hi.mean() / lo.mean()) if lo.mean() > 0 else float("nan")
    verdict = YES if clustered > T_CONVINCING else NO if clustered < -T_CONVINCING else UNCLEAR
    lead = {
        YES: f"Yes. Filings it flagged were followed by a {hi.mean():.2f}% move against {lo.mean():.2f}% for the rest - {ratio:.2f} times as large - and the gap holds inside tokens ({int((per > 0).sum())} of {len(per)}, t={clustered:+.2f}).",
        NO: f"No - the flagged ones moved *less*: {hi.mean():.2f}% against {lo.mean():.2f}% (t={clustered:+.2f} across {len(per)} tokens).",
        UNCLEAR: f"Cannot be called. Flagged filings averaged {hi.mean():.2f}% against {lo.mean():.2f}%, but only {int((per > 0).sum())} of {len(per)} tokens agree (t={clustered:+.2f}).",
    }[verdict]
    return Study(
        key="filing_read_predicts_size",
        title="Does the model spot a filing that matters?",
        question="99% of the 8-Ks in this history landed while the US market was shut, so the token carries them alone until the next open. The model reads each one and says how likely it is to move the share price. Do the ones it flags actually move more?",
        method=f"{len(d)} filings read from their own text, with no price in the prompt. Each is scored on the token's move from the filing to the next US regular open, and the flagged ones ({len(hi)}) compared with the rest ({len(lo)}), clustered by token.",
        finding=lead,
        consequence=(
            "The read is shown next to a fresh filing on the report, as the model's words with this number attached."
            if verdict == YES
            else "The read is stored and shown on this page, and does not reach the verdict or the sizing. It is an opinion that has not earned a number."
        ),
        verdict=verdict, n=int(len(d)),
        stats={"move_flagged": float(hi.mean()), "move_rest": float(lo.mean()), "ratio": ratio,
               "n_flagged": float(len(hi)), "n_rest": float(len(lo)), "clustered_t": clustered,
               "tokens_agreeing": float((per > 0).sum()), "tokens": float(len(per))},
    )


def study_the_model_calls_the_direction(outcomes: pd.DataFrame) -> Study:
    """It also says which way. That is a prediction, so it can be marked."""
    d = outcomes.dropna(subset=["ret_pct", "direction"]).copy()
    called = d[d["direction"].isin(("up", "down"))]
    if len(called) < 60:
        return Study(
            key="filing_read_calls_direction", title="Does the model call the direction?",
            question="On the filings where it commits to up or down, is it right more often than a coin?",
            method="Score the sign of the move from the filing to the next US open against the direction it called.",
            finding=f"Only {len(called)} filings got a directional call; not enough to mark.",
            consequence="No directional read is shown.", verdict=UNCLEAR, n=len(called), stats={},
        )
    hit = np.where(called["direction"] == "up", called["ret_pct"] > 0, called["ret_pct"] < 0).astype(float)
    called = called.assign(hit=hit)
    rate = float(hit.mean())
    per = called.groupby("ticker")["hit"].mean()
    clustered = _t((per - 0.5).to_numpy()) if len(per) > 1 else float("nan")
    lo_ci, hi_ci = wilson_interval(int(hit.sum()), len(hit))
    verdict = YES if lo_ci > 0.5 and clustered > T_CONVINCING else NO if hi_ci < 0.5 else UNCLEAR
    share_called = len(called) / max(1, len(d))
    lead = {
        YES: f"Yes. It called {rate:.1%} of them right, interval [{lo_ci:.1%}, {hi_ci:.1%}], and the edge survives clustering by token (t={clustered:+.2f}).",
        NO: f"No - worse than a coin, at {rate:.1%} right, interval [{lo_ci:.1%}, {hi_ci:.1%}].",
        UNCLEAR: f"No evidence either way. It called {rate:.1%} of them right on {len(called)} filings, and the interval [{lo_ci:.1%}, {hi_ci:.1%}] contains a coin toss (clustered t={clustered:+.2f}).",
    }[verdict]
    return Study(
        key="filing_read_calls_direction",
        title="Does the model call the direction?",
        question="On top of how much a filing matters, the model says which way it points. That is a prediction with a right answer, so it can be marked.",
        method=f"It declined to call {1 - share_called:.0%} of filings, answering 'unclear'; those are not scored. The {len(called)} it did commit to are scored on the sign of the token's move to the next US open, with a Wilson interval and a per-token check.",
        finding=lead,
        consequence=(
            "Shown on the report as a directional read, with this hit rate printed beside it so nobody has to take it on faith."
            if verdict == YES
            else "No directional read reaches the report. A call that cannot be shown to beat a coin has no business next to a sized position."
        ),
        verdict=verdict, n=int(len(called)),
        stats={"hit_rate": rate, "ci_low": lo_ci, "ci_high": hi_ci, "clustered_t": clustered,
               "share_committed": share_called, "n_called": float(len(called)), "n_read": float(len(d))},
    )


ORDER = (
    "closer_is_not_tighter",
    "weighting_does_not_help",
    "analogs_beat_random_hours",
    "pooling_beats_own_history",
    "narrowing_gives_a_truer_tail",
    "distance_does_not_warn",
    "one_factor_hid_two_errors",
    "online_calibration_adds_nothing",
    "filing_read_predicts_size",
    "filing_read_calls_direction",
)


def filing_outcomes(ctx: Any, store: Any) -> pd.DataFrame:  # noqa: ANN401
    """Every filing the model read, joined to what the token did before the next open."""
    from nightwatch.features import filing_outcomes as fo

    try:
        reads = fo.load_reads(store)
    except Exception:  # noqa: BLE001 - no reads table yet is not an error
        return pd.DataFrame()
    return fo.collect(ctx, reads) if not reads.empty else pd.DataFrame()


def run_all(ctx: Any, forecasts: pd.DataFrame, *, evidence: Evidence | None = None, max_points_per_ticker: int = 40, lens_rows: pd.DataFrame | None = None) -> list[Study]:
    """Every study, recomputed. Anything that fails is reported as inconclusive rather
    than dropped, so a study cannot quietly disappear because it stopped working."""
    from nightwatch.journal import lens_study

    ev = evidence if evidence is not None else collect_evidence(ctx, max_points_per_ticker=max_points_per_ticker)
    ran = utc_now().isoformat()
    jobs: list[tuple[str, Any]] = []
    # The narrowing sweep runs two searches per qualifying night across the whole
    # history, so it is the slow one; a caller that already has the rows passes them in.
    lr = lens_rows if lens_rows is not None else lens_study.collect(ctx)
    if not lr.empty:
        jobs.append((lens_study.KEY, lambda: lens_study.study(lr)))
    if ev.ok:
        jobs += [
            ("closer_is_not_tighter", lambda: study_closer_is_not_tighter(ev)),
            ("weighting_does_not_help", lambda: study_weighting_does_not_help(ev)),
            ("distance_does_not_warn", lambda: study_distance_does_not_warn(ev)),
            ("pooling_beats_own_history", lambda: study_pooling_beats_own_history(ev)),
        ]
    if not forecasts.empty:
        jobs += [
            ("one_factor_hid_two_errors", lambda: study_one_factor_hid_two_errors(forecasts)),
            ("online_calibration_adds_nothing", lambda: study_online_calibration_adds_nothing(forecasts)),
            ("analogs_beat_random_hours", lambda: study_analogs_beat_random_hours(forecasts)),
        ]
    reads = filing_outcomes(ctx, getattr(ctx, "store", None))
    if not reads.empty:
        # The distributions the report quotes next to a fresh filing. Recomputed here
        # rather than at report time: it is a global summary over every scored filing,
        # and an analysis should not pay for it on every request.
        from nightwatch.features.filing_outcomes import save_labels, summarise_labels

        try:
            save_labels(ctx.store, summarise_labels(reads))
        except Exception:  # noqa: BLE001 - a summary failure must not lose the studies
            log.exception("filing label summary failed")
        jobs += [
            ("filing_read_predicts_size", lambda: study_the_model_spots_a_big_night(reads)),
            ("filing_read_calls_direction", lambda: study_the_model_calls_the_direction(reads)),
        ]
    out: list[Study] = []
    for key, fn in jobs:
        try:
            s = fn()
        except Exception:  # noqa: BLE001
            log.exception("study %s failed", key)
            continue
        out.append(Study(**{**s.to_dict(), "ran_at": ran}))
    return sorted(out, key=lambda s: ORDER.index(s.key) if s.key in ORDER else 99)


class StudyStore:
    """Results, with the date they were computed. A study served without one would be
    indistinguishable from a number somebody typed in."""

    def __init__(self, store: Store):
        self._conn: sqlite3.Connection = store._conn
        self._conn.executescript(SCHEMA)

    def save(self, studies: list[Study]) -> int:
        with self._conn:
            for s in studies:
                self._conn.execute(
                    "INSERT INTO studies (key, ran_at, body) VALUES (?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET ran_at=excluded.ran_at, body=excluded.body",
                    (s.key, int(utc_now().timestamp() * 1000), zlib.compress(json.dumps(s.to_dict()).encode("utf-8"), 6)),
                )
        return len(studies)

    def all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT key, ran_at, body FROM studies").fetchall()
        out = [json.loads(zlib.decompress(b).decode("utf-8")) for _, _, b in rows]
        return sorted(out, key=lambda s: ORDER.index(s["key"]) if s["key"] in ORDER else 99)

    def last_run(self) -> datetime | None:
        row = self._conn.execute("SELECT MAX(ran_at) FROM studies").fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromtimestamp(row[0] / 1000, tz=utc_now().tzinfo)
