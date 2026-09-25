"""The study that scores the engine's disagreement with itself, on rows whose answer is
known. The trap it is built around - disagreement that only proxies a small number -
has to come back "no", and disagreement that really carries information has to come
back "yes"."""

import numpy as np
import pandas as pd

from nightwatch.journal import robust_study as rs
from nightwatch.journal.studies import NO, UNCLEAR, YES

TOKENS = [f"T{i}" for i in range(8)]
VERSIONS = ["shipped", "k25", "k30", "k60", "no_basis", "no_volatility", "no_macro"]


def rows(*, n_per_token: int, informative: bool, seed: int = 0) -> pd.DataFrame:
    """Every moment has a shipped 5th percentile of random size and a set of versions
    scattered around it. In the ``informative`` world the outcome breaches more often
    when the versions scatter more, at any size; in the other world the breach rate
    depends only on the size of the shipped number, and the scatter merely grows as
    the number shrinks - which is what the real sweep found."""
    rng = np.random.default_rng(seed)
    out = []
    for t in TOKENS:
        for _ in range(n_per_token):
            size = float(rng.uniform(1.0, 8.0))
            scatter = float(rng.uniform(0.2, 1.5)) if informative else 0.4 + 1.6 / size
            rel = scatter
            if informative:
                p_breach = 0.02 + 0.12 * (rel - 0.2) / 1.3
            else:
                p_breach = 0.15 / size
            truth = -size - 1.0 if rng.uniform() < p_breach else -size + 1.0 + rng.normal(0, 0.3)
            row = {"ticker": t, "as_of": "2026-01-01T21:00:00+00:00", "horizon_h": 12, "truth": truth, "p5_shipped": -size}
            for v in VERSIONS[1:]:
                row[f"p5_{v}"] = -size + rng.uniform(-0.5, 0.5) * rel * size
            out.append(row)
    return pd.DataFrame(out)


def test_disagreement_that_carries_information_is_a_yes():
    s = rs.study(rows(n_per_token=120, informative=True))
    assert s.verdict == YES and "survives" in s.finding
    assert s.stats["controlled_t"] > 2


def test_disagreement_that_only_proxies_a_small_number_is_a_no_and_says_so():
    s = rs.study(rows(n_per_token=120, informative=False))
    assert s.verdict == NO
    assert "looks true and it is not" in s.finding and "proxy" in s.finding
    assert s.stats["raw_t"] > 2 > abs(s.stats["controlled_t"])
    assert "carry none" in s.consequence and "floor" in s.consequence


def test_a_handful_of_moments_is_not_judged():
    s = rs.study(rows(n_per_token=10, informative=True))
    assert s.verdict == UNCLEAR and s.stats == {}


def test_every_one_step_change_to_the_recipe_is_a_variant():
    from nightwatch.analog.engine import AnalogConfig

    v = rs.variants(AnalogConfig())
    assert set(v) == {"shipped", "k25", "k30", "k60"} | {f"no_{g}" for g in rs.FEATURE_GROUPS}
    for name, cols in rs.FEATURE_GROUPS.items():
        assert not set(cols) & set(v[f"no_{name}"].features)
    assert v["k60"].k == 60 and v["k60"].features == AnalogConfig().features
