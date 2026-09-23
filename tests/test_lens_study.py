"""The study that scores narrowing, scored on rows whose answer is known.

The verdict has to follow the evidence in both directions: a narrowed tail that the
outcomes respect more often must come back "yes", one they respect less must come back
"no", and a handful of nights must come back "not enough to say" however good they look.
"""

import numpy as np
import pandas as pd

from nightwatch.journal import lens_study as ls
from nightwatch.journal.studies import NO, UNCLEAR, YES

TOKENS = [f"T{i}" for i in range(8)]


def rows(lens: str, *, n_per_token: int, lens_is_right: bool, seed: int = 0) -> pd.DataFrame:
    """Outcomes drawn with a true 5th percentile of -6%. One arm says -6%, the other -2%;
    which arm is the narrowed one decides which should win."""
    rng = np.random.default_rng(seed)
    out = []
    for t in TOKENS:
        y = rng.normal(0.0, 6.0 / 1.645, n_per_token)
        right, wrong = -6.0, -2.0
        for v in y:
            out.append({
                "lens": lens, "ticker": t, "as_of": "2026-01-01T21:00:00+00:00", "horizon_h": 12,
                "truth": float(v), "applied": True, "searched": True, "hours_left": 900, "n_all": 40, "n_lens": 30,
                "p5_all": wrong if lens_is_right else right,
                "p5_lens": right if lens_is_right else wrong,
            })
    return pd.DataFrame(out)


def test_a_narrowed_tail_the_outcomes_respect_is_a_yes():
    s = ls.study(rows("earnings_soon", n_per_token=40, lens_is_right=True))
    assert s.verdict == YES and "earnings ahead" in s.finding
    assert s.stats["earnings_soon.breach_lens"] < s.stats["earnings_soon.breach_all"]


def test_a_narrowed_tail_that_is_breached_more_is_a_no_and_is_flagged():
    s = ls.study(rows("basis_stretched", n_per_token=40, lens_is_right=False))
    assert s.verdict == NO
    assert "less reliable" in s.consequence, "a condition that makes the tail worse has to change what the desk shows"


def test_a_handful_of_nights_is_not_judged_however_good_it_looks():
    s = ls.study(rows("earnings_soon", n_per_token=3, lens_is_right=True))
    assert s.verdict == UNCLEAR


def test_mixed_results_are_reported_as_mixed():
    both = pd.concat([
        rows("earnings_soon", n_per_token=40, lens_is_right=True, seed=1),
        rows("weekend", n_per_token=40, lens_is_right=False, seed=2),
    ])
    s = ls.study(both)
    assert s.verdict == UNCLEAR and "better for" in s.finding and "worse for" in s.finding


def test_moments_that_could_not_be_narrowed_are_counted_not_scored():
    """A refused narrowing has no narrowed forecast to score. Dropping it silently would
    hide how often the desk has to say no; counting it as a pass would be worse."""
    r = rows("fomc_soon", n_per_token=10, lens_is_right=True)
    r.loc[r.index[:30], ["applied", "p5_lens"]] = [False, None]
    r.loc[r.index[30:45], ["searched", "p5_lens"]] = [False, None]
    table = ls.score(r)
    rec = table.iloc[0]
    assert rec["asked"] == 80 and rec["too_few_hours"] == 30 and rec["too_few_episodes"] == 15
    assert rec["n"] == 35


def test_an_empty_sweep_is_unclear_not_an_error():
    assert ls.study(pd.DataFrame()).verdict == UNCLEAR
