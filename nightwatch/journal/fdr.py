"""Multiple-testing correction across the published studies.

Eleven studies were run and each one's verdict was read off its own statistic, so the
chance that at least one "yes" is luck is higher than any single test suggests. This
module derives, where it can be done honestly, one p-value per study from what the
study already stores, corrects them together with Benjamini-Hochberg at a 5% false
discovery rate, and flags the results that rest on very few observations.

It runs on the stored results at serve time. Verdicts and stats are never rewritten:
the correction is a second opinion printed beside the first, not a new verdict.

Where a p-value comes from, by study (the ``p_method`` field says it in words):

* token-clustered t  -> two-sided Student t with clusters - 1 degrees of freedom.
* bootstrap interval -> the bootstrap draws are not stored, so p is a normal
  approximation from the interval's width. It says so.
* a study whose verdict is a fixed tolerance on a coverage rate (not a comparison
  against a null) has no p-value and is marked ``not a hypothesis test``. Inventing
  one would be worse than leaving it out.

Some stored results do not carry their cluster count. Then the normal approximation is
used, which can only make p smaller. A study that fails to survive on that best case
fails for a reason that does not depend on the missing number.
"""

from __future__ import annotations

import math
from typing import Any

ALPHA = 0.05  # false discovery rate the correction controls
# Under this many independent observations a cell is shown but not leaned on. It is the
# same floor lens_study.MIN_PAIRS uses to decide a condition is "reported, not judged".
SMALL_N = 30

NOT_A_TEST = "not a hypothesis test"


# ------------------------------------------------------------------ distributions


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def two_sided_p_from_t(t: float | None, df: float | None) -> float | None:
    """Two-sided p for a t statistic. ``df=None`` means the normal approximation."""
    if t is None or not math.isfinite(t):
        return None
    if df is None or df > 1e6:
        return math.erfc(abs(t) / math.sqrt(2.0))
    if df < 1:
        return None
    return float(_betainc(df / 2.0, 0.5, df / (df + t * t)))


def one_sided_p_from_t(t: float, df: float | None) -> float | None:
    """P(T >= t): small when t is large and positive."""
    two = two_sided_p_from_t(t, df)
    if two is None:
        return None
    return 0.5 * two if t > 0 else 1.0 - 0.5 * two


def bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), in the input order."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = min(1.0, running)
    return q


# ---------------------------------------------------------------- per-study p-values


def _f(stats: dict[str, Any], key: str) -> float | None:
    try:
        v = float(stats.get(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _df(clusters: float | None) -> float | None:
    return clusters - 1.0 if clusters and clusters > 1 else None


def _clustered(t: float | None, clusters: float | None, what: str) -> tuple[float | None, str]:
    if t is None:
        return None, NOT_A_TEST
    df = _df(clusters)
    p = two_sided_p_from_t(t, df)
    basis = (
        f"Student t, {int(df)} degrees of freedom ({int(clusters or 0)} tokens)"
        if df
        else "normal approximation (token count not stored, so p is a lower bound)"
    )
    return p, f"Two-sided p from the {what}: {basis}."


def _p_weighting(st: dict[str, Any], n: int) -> tuple[float | None, str]:
    ts = {k[2:]: v for k, v in st.items() if k.startswith("t_") and isinstance(v, (int, float)) and math.isfinite(v)}
    if not ts:
        return None, NOT_A_TEST
    ps = [one_sided_p_from_t(t, n - 1 if n > 1 else None) for t in ts.values()]
    ps = [p for p in ps if p is not None]
    p = min(1.0, len(ts) * min(ps))
    return p, (
        f"Smallest one-sided p across the {len(ts)} weighting schemes (Student t, {n - 1} degrees of freedom), times {len(ts)} "
        "for having tried that many. The t is on individual moments, not clustered by token, so it flatters the schemes."
    )


def _p_random_hours(st: dict[str, Any]) -> tuple[float | None, str]:
    p_t, _ = _clustered(_f(st, "clustered_t"), _f(st, "tokens"), "clustered t")
    lo, hi, mean = _f(st, "boot_ci_low"), _f(st, "boot_ci_high"), _f(st, "mean_advantage")
    if p_t is None or lo is None or hi is None or mean is None or hi <= lo:
        return p_t, "Two-sided p from the token-clustered t."
    se = (hi - lo) / (2.0 * 1.959964)
    p_b = two_sided_p_from_t(mean / se, None)
    assert p_b is not None
    # The verdict needs both the clustered t and the bootstrap interval to clear zero,
    # so the claim is only as strong as the weaker of the two.
    return max(p_t, p_b), (
        f"The verdict needs two things at once, so p is the larger of two: the token-clustered t (p = {p_t:.3f}, Student t, "
        f"{int(_f(st, 'tokens') or 0) - 1} degrees of freedom) and the week-bootstrap interval (p = {p_b:.3f}). The bootstrap draws are not "
        "stored, so that second p is a normal approximation from the width of the 95% interval."
    )


def _p_pooling(st: dict[str, Any], n: int) -> tuple[float | None, str]:
    t = _f(st, "t_own_minus_other")
    if t is None:
        return None, NOT_A_TEST
    return two_sided_p_from_t(-t, n - 1 if n > 1 else None), (
        f"Two-sided p from a paired t on {n} moments (Student t, {n - 1} degrees of freedom). Not clustered by token, so it is "
        "optimistic."
    )


def _p_narrowing(st: dict[str, Any]) -> tuple[float | None, str]:
    conds = sorted({k[: -len(".n")] for k in st if k.endswith(".n")})
    judged: list[tuple[str, float]] = []
    approx = False
    for c in conds:
        n, t = _f(st, f"{c}.n"), _f(st, f"{c}.t_clustered")
        if n is None or t is None or n < SMALL_N:
            continue
        df = _df(_f(st, f"{c}.tokens"))
        approx = approx or df is None
        p = two_sided_p_from_t(t, df)
        if p is not None:
            judged.append((c, p))
    if not judged:
        return None, NOT_A_TEST
    k = len(judged)
    best_c, best_p = min(judged, key=lambda x: x[1])
    tail = " Token counts per condition were not stored, so each p uses the normal approximation and is a lower bound." if approx else ""
    return min(1.0, k * best_p), (
        f"Smallest two-sided p across the {k} conditions with at least {SMALL_N} nights ({best_c.replace('_', ' ')}: p = {best_p:.3f}), "
        f"times {k} for having looked at that many.{tail}"
    )


def _p_direction(st: dict[str, Any]) -> tuple[float | None, str]:
    p_t, _ = _clustered(_f(st, "clustered_t"), _f(st, "tokens"), "clustered t")
    rate, n = _f(st, "hit_rate"), _f(st, "n_called")
    if p_t is None or rate is None or not n:
        return p_t, "Two-sided p from the token-clustered t."
    p_h = two_sided_p_from_t((rate - 0.5) / math.sqrt(0.25 / n), None)
    assert p_h is not None
    tail = "" if _df(_f(st, "tokens")) else "; token count not stored, so that one is a normal approximation"
    return max(p_t, p_h), (
        "The verdict needs the hit-rate interval and the token-clustered t to both clear a coin, so p is the larger of the two: "
        f"hit rate against 50% on {int(n)} calls (normal approximation, p = {p_h:.3f}) and the clustered t (p = {p_t:.3f}{tail})."
    )


def derive_p(study: dict[str, Any]) -> tuple[float | None, str]:
    """(p, how it was derived) for one stored study, or (None, 'not a hypothesis test')."""
    key, st, n = study.get("key", ""), study.get("stats") or {}, int(study.get("n") or 0)
    if not st:
        return None, NOT_A_TEST
    if key in ("closer_is_not_tighter", "distance_does_not_warn", "filing_read_predicts_size"):
        return _clustered(_f(st, "clustered_t"), _f(st, "tokens"), "token-clustered t")
    if key == "disagreement_warns_of_a_breach":
        return _clustered(_f(st, "controlled_t"), _f(st, "tokens"), "token-clustered t with the size of the shipped number held fixed")
    if key == "weighting_does_not_help":
        return _p_weighting(st, n)
    if key == "analogs_beat_random_hours":
        return _p_random_hours(st)
    if key == "pooling_beats_own_history":
        return _p_pooling(st, n)
    if key == "narrowing_gives_a_truer_tail":
        return _p_narrowing(st)
    if key == "filing_read_calls_direction":
        return _p_direction(st)
    if key in ("one_factor_hid_two_errors", "online_calibration_adds_nothing"):
        return None, f"{NOT_A_TEST}: the verdict is a fixed tolerance on a coverage rate, not a comparison against a null."
    return None, NOT_A_TEST


def small_sample(study: dict[str, Any]) -> str | None:
    """A note when the sample the verdict leans on, or a cell shown beside it, is thin."""
    st = study.get("stats") or {}
    cells = sorted(
        (float(v), k[: -len(".n")]) for k, v in st.items()
        if k.endswith(".n") and isinstance(v, (int, float)) and 0 < v < SMALL_N
    )
    if cells:
        named = ", ".join(f"{c.replace('_', ' ')} (n={int(v)})" for v, c in cells)
        return (
            f"{len(cells)} condition{'s' if len(cells) != 1 else ''} rest on fewer than {SMALL_N} nights: {named}. "
            "They are shown but not judged, and they do not decide the verdict."
        )
    n = int(study.get("n") or 0)
    if 0 < n < SMALL_N:
        return f"Only {n} observations; under {SMALL_N} is too few to lean on."
    return None


def annotate(studies: list[dict[str, Any]], *, alpha: float = ALPHA) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Copies of the studies with ``p_value``, ``q_value``, ``survives_fdr``, ``p_method``,
    ``small_sample`` and ``small_sample_note`` added, plus a summary of the correction."""
    derived = [derive_p(s) for s in studies]
    idx = [i for i, (p, _) in enumerate(derived) if p is not None]
    qs = dict(zip(idx, bh_adjust([float(derived[i][0]) for i in idx]), strict=True))  # type: ignore[arg-type]
    out = []
    for i, s in enumerate(studies):
        p, how = derived[i]
        note = small_sample(s)
        q = qs.get(i)
        out.append({
            **s,
            "p_value": p,
            "q_value": q,
            "survives_fdr": None if q is None else bool(q < alpha),
            "p_method": how,
            "small_sample": note is not None,
            "small_sample_note": note,
        })
    yes = [s for s in out if s.get("verdict") == "yes"]
    testable_yes = [s for s in yes if s["survives_fdr"] is not None]
    summary = {
        "method": "Benjamini-Hochberg",
        "alpha": alpha,
        "m_tests": len(idx),
        "m_studies": len(studies),
        "yes_total": len(yes),
        "yes_tested": len(testable_yes),
        "yes_survive": sum(1 for s in testable_yes if s["survives_fdr"]),
        "yes_fail": [s["key"] for s in testable_yes if not s["survives_fdr"]],
    }
    return out, summary
