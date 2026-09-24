"""Narrowing the search to the kind of moment the trader actually means.

The retrieval answers "what happened after moments like now". Sometimes that is not the
question. A trader carrying a position into an earnings night does not want the average
of every night; they want the earnings ones, and the two distributions are not the same
object. Until now there was no way to say so.

A lens is a named condition with a fixed predicate. The model's job is to turn a phrase
into a list of these names and nothing else - it never writes a threshold, a column name
or an expression. That boundary is the whole design:

* **Auditable.** Every lens prints its own definition, so "only earnings nights" resolves
  to ``hours_to_earnings <= 24`` on the page, not into a query nobody can see.
* **Safe.** The model cannot invent a filter, reach a column that is not searched, or
  produce a threshold chosen to flatter the answer. It picks from a menu written here.
* **Honest when it fails.** Narrowing thins the cohort fast, and the refusal rule is
  unchanged: below the minimum number of distinct episodes the desk says so and answers
  nothing. Asking a narrow question and being told there is no evidence for it is a
  correct outcome, and the common one.

The lens applies to the searched history, not to the result, so the distance ranking
happens *within* the filtered set rather than picking the survivors of an unfiltered
ranking. Those give different cohorts, and only the first is the cohort asked for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# Nights and weekends when the US market is shut - the windows this desk exists for.
CLOSED_BUCKETS = ("weeknight", "friday_night", "weekend", "sunday_night", "holiday")


@dataclass(frozen=True)
class Lens:
    """One named condition a trader can ask for, and exactly what it means."""

    name: str
    label: str  # what it is called on the page
    definition: str  # the predicate in words, shown next to the result
    predicate: Callable[[pd.DataFrame], pd.Series[bool]]
    says: tuple[str, ...] = ()  # phrases that should resolve to this lens

    def mask(self, frame: pd.DataFrame) -> pd.Series[bool]:
        try:
            m = self.predicate(frame)
        except KeyError:
            # A history missing the column cannot satisfy the condition, and silently
            # matching everything would answer a question nobody asked.
            return pd.Series(False, index=frame.index)
        return m.fillna(False).astype(bool)

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "label": self.label, "definition": self.definition}


def _col(frame: pd.DataFrame, name: str) -> pd.Series[float]:
    if name not in frame.columns:
        raise KeyError(name)
    return frame[name]


LENSES: tuple[Lens, ...] = (
    Lens(
        "earnings_soon", "earnings ahead", "earnings due within 24 hours",
        lambda f: _col(f, "hours_to_earnings") <= 24,
        says=("earnings", "earnings night", "into earnings", "before earnings", "results", "财报前", "财报夜", "财报当晚"),
    ),
    Lens(
        "earnings_this_week", "earnings within three days", "earnings due within 72 hours",
        lambda f: _col(f, "hours_to_earnings") <= 72,
        says=("earnings this week", "earnings coming", "earnings soon", "财报周", "财报前几天"),
    ),
    Lens(
        "just_after_earnings", "just after earnings", "earnings reported in the last 24 hours",
        lambda f: _col(f, "hours_since_earnings") <= 24,
        says=("after earnings", "post earnings", "earnings drift", "the day after results", "财报后", "刚出财报"),
    ),
    Lens(
        "fomc_soon", "FOMC ahead", "an FOMC decision due within 48 hours",
        lambda f: _col(f, "hours_to_fomc") <= 48,
        says=("fed", "fomc", "rate decision", "before the fed", "美联储", "议息", "fomc前"),
    ),
    Lens(
        "weekend", "over a weekend", "the Friday night, weekend or Sunday night window",
        lambda f: _col(f, "bucket").isin(("weekend", "friday_night", "sunday_night")),
        says=("weekend", "over the weekend", "saturday", "sunday", "friday night", "周末"),
    ),
    Lens(
        "weeknight", "an ordinary weeknight", "the Monday-to-Thursday overnight window",
        lambda f: _col(f, "bucket") == "weeknight",
        says=("weeknight", "overnight", "a normal night", "midweek night", "工作日晚上", "平日夜盘"),
    ),
    Lens(
        "market_shut", "while the US market was shut", "any hour outside the US regular session",
        lambda f: _col(f, "bucket").isin(CLOSED_BUCKETS),
        says=("market closed", "market shut", "out of hours", "after hours", "closed market", "休市"),
    ),
    Lens(
        "market_open", "during the US session", "the US regular trading session",
        lambda f: _col(f, "bucket") == "us_regular",
        says=("market open", "during the session", "regular hours", "intraday", "盘中", "开盘时段"),
    ),
    Lens(
        "basis_stretched", "the token stretched from fair value", "|basis z-score| at or above 2",
        lambda f: _col(f, "basis_index_z").abs() >= 2.0,
        says=("basis stretched", "far from fair value", "big premium", "big discount", "dislocated", "wide basis", "溢价大", "折价大", "价差大", "偏离公允"),
    ),
    Lens(
        "basis_calm", "the token near fair value", "|basis z-score| at or below 0.5",
        lambda f: _col(f, "basis_index_z").abs() <= 0.5,
        says=("basis calm", "near fair value", "tight basis", "trading in line", "价差小", "贴近公允"),
    ),
    Lens(
        "high_volatility", "volatile", "realised volatility in the top fifth of its own year",
        lambda f: _col(f, "vol_pctl_90d") >= 80,
        says=("volatile", "high vol", "choppy", "wild", "turbulent", "高波动", "波动大"),
    ),
    Lens(
        "low_volatility", "quiet", "realised volatility in the bottom fifth of its own year",
        lambda f: _col(f, "vol_pctl_90d") <= 20,
        says=("quiet", "low vol", "calm", "sleepy", "低波动", "波动小"),
    ),
    Lens(
        "thin_liquidity", "the book thin", "traded volume at or below half the usual for that hour of the week",
        lambda f: _col(f, "liq_ratio") <= 0.5,
        says=("thin", "illiquid", "no liquidity", "thin book", "hard to exit", "流动性差", "盘口薄", "流动性不足"),
    ),
    Lens(
        "uptrend", "in an uptrend", "price above its moving average",
        lambda f: _col(f, "trend_sma_pct") > 0,
        says=("uptrend", "rising", "trending up", "going up", "上涨趋势", "上升趋势"),
    ),
    Lens(
        "downtrend", "in a downtrend", "price below its moving average",
        lambda f: _col(f, "trend_sma_pct") < 0,
        says=("downtrend", "falling", "selling off", "trending down", "going down", "下跌趋势", "下降趋势"),
    ),
    Lens(
        "fresh_filing", "just after an SEC filing", "a filing accepted in the last 24 hours",
        lambda f: _col(f, "hours_since_filing") <= 24,
        says=("filing", "8-k", "sec filing", "after a filing", "news filing", "公告后", "刚发公告"),
    ),
    Lens(
        "risk_off", "with the market nervous", "VIX in the top fifth of its own year",
        lambda f: _col(f, "vix_pctl_1y") >= 80,
        says=("risk off", "vix high", "market nervous", "fear", "scared market", "恐慌", "避险"),
    ),
)

# There is no "in the news" lens, and that is a data fact rather than an oversight. The
# headline feed is thin against fifteen thousand hours of history: on TSLA 0.5% of hours
# carry any tagged headline at all, none carry two, and the mean is 0.005. A lens built
# on it would leave 72 hours out of 15,129 and be refused every time it was asked for.
# Offering a filter that can only ever say no is worse than not offering it.

BY_NAME: dict[str, Lens] = {x.name: x for x in LENSES}


def resolve(names: list[str] | tuple[str, ...] | None) -> list[Lens]:
    """Names to lenses, silently dropping any the model invented.

    Dropping rather than failing is deliberate: a model that returns one good condition
    and one imaginary one should still narrow the search the way the trader asked, and
    the report prints exactly which lenses were applied so nothing is hidden.
    """
    out: list[Lens] = []
    for n in names or ():
        lens = BY_NAME.get(str(n).strip().lower())
        if lens is not None and lens not in out:
            out.append(lens)
    return out


def mask(frame: pd.DataFrame, lenses: list[Lens]) -> pd.Series[bool]:
    """Rows satisfying every lens. Conditions combine with AND, because a trader asking
    for "earnings nights over a weekend" means both, not either."""
    keep = pd.Series(True, index=frame.index)
    for lens in lenses:
        keep &= lens.mask(frame)
    return keep


def describe(lenses: list[Lens]) -> str:
    return " and ".join(x.label for x in lenses)


def menu() -> list[dict[str, str]]:
    """The vocabulary, for the model's prompt and for the interface."""
    return [x.to_dict() for x in LENSES]


def prompt_menu() -> str:
    """The lens list as the model sees it: a name, what it means, and how it is said."""
    lines = []
    for x in LENSES:
        said = f"  (e.g. {', '.join(x.says[:4])})" if x.says else ""
        lines.append(f'  "{x.name}" - {x.label}: {x.definition}{said}')
    return "\n".join(lines)


@dataclass(frozen=True)
class LensResult:
    """What a narrowed search found, and what it cost in evidence."""

    lenses: list[Lens]
    n_before: int
    n_after: int
    applied: bool
    refused: str = ""
    # Set when the desk chose this narrowing itself rather than being asked for it, and
    # says why. Empty for a narrowing the trader requested.
    auto: str = ""

    @property
    def names(self) -> list[str]:
        return [x.name for x in self.lenses]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lenses": [x.to_dict() for x in self.lenses],
            "names": self.names,
            "description": describe(self.lenses),
            "n_before": self.n_before,
            "n_after": self.n_after,
            "applied": self.applied,
            "refused": self.refused,
            "auto": self.auto,
        }


def _too_thin(lenses: list[Lens], n_after: int) -> str:
    return (
        f"only {n_after} past hours match {describe(lenses)}, which is too few to build a "
        f"distribution from; the answer below is the unfiltered one"
    )


def apply(frame: pd.DataFrame, names: list[str] | None, *, min_rows: int) -> tuple[pd.DataFrame, LensResult]:
    """Narrow the searchable history, or explain why it was not narrowed.

    ``min_rows`` is the floor below which filtering would leave too little to search.
    When the lens would take the history under it, the search runs unfiltered and the
    report says the request could not be honoured - which is a better answer than a
    distribution built from nine hours that happen to match.
    """
    lenses = resolve(names)
    if not lenses:
        return frame, LensResult([], len(frame), len(frame), applied=False)
    keep = mask(frame, lenses)
    n_after = int(keep.sum())
    if n_after < min_rows:
        return frame, LensResult(lenses, len(frame), n_after, applied=False, refused=_too_thin(lenses, n_after))
    return frame[keep], LensResult(lenses, len(frame), n_after, applied=True)


def apply_to_parts(parts: Sequence[tuple[str, pd.DataFrame]], names: list[str] | None, *, min_rows: int) -> tuple[list[tuple[str, pd.DataFrame]], LensResult]:
    """The same narrowing, done to each token's history before they are stacked.

    Identical rows to filtering the stack afterwards - a row filter commutes with a
    concatenation - without copying and sorting 326,016 rows to keep 1,752 of them. That
    is a memory saving on a 1 GB box, not a speed one: measured, the search time barely
    moved (9.4s to 9.1s cold). A cold narrowed search is slow because the other 23
    tokens' feature frames are rebuilt for the new hour; warm, the same query takes 3.0s.
    """
    lenses = resolve(names)
    n_before = sum(len(f) for _, f in parts)
    if not lenses:
        return list(parts), LensResult([], n_before, n_before, applied=False)
    kept = [(t, f[mask(f, lenses)]) for t, f in parts]
    n_after = sum(len(f) for _, f in kept)
    if n_after < min_rows:
        return list(parts), LensResult(lenses, n_before, n_after, applied=False, refused=_too_thin(lenses, n_after))
    # A token with nothing left is a token that contributed nothing, and the report says
    # how many were searched. Keeping its empty frame would inflate that count and give
    # the stack a column of all-null dtypes to reconcile.
    return [(t, f) for t, f in kept if len(f)], LensResult(lenses, n_before, n_after, applied=True)


# Conditions the desk applies without being asked. Only ones a study has shown the
# unfiltered answer to be wrong for belong here, and only while that stays true: on
# 100 past overnight holds with earnings due within three days, the unfiltered 5th
# percentile was breached 22.0% of the time against a 5% target and the narrowed one
# 7.0% (12 of 18 tokens better, t=+2.9; study "narrowing_gives_a_truer_tail"). Sizing
# an earnings-week position off the unfiltered tail is sizing it off a number that is
# wrong four times in five of the nights it is meant to cover.
AUTOMATIC = ("earnings_this_week",)


def automatic_for(features: dict[str, Any]) -> list[Lens]:
    """The automatic conditions that hold for the moment described by ``features``."""
    row = pd.DataFrame([{k: v for k, v in features.items() if v is not None}])
    return [BY_NAME[n] for n in AUTOMATIC if n in BY_NAME and bool(BY_NAME[n].mask(row).iloc[0])]


MAX_SUGGESTIONS = 4
# A condition holding across a large share of the history barely changes the cohort, so
# it is not worth offering even when it happens to be true right now. Which conditions
# those are is measured on the token's own past rather than asserted here: on TSLA's
# 15,129 hours "the market is shut" covers 54% and "in an uptrend" 47%, while "thin
# book" covers 19%. A third is the line between narrowing the search and renaming it.
COMMONPLACE_SHARE = 1 / 3


def suggest_now(frame: pd.DataFrame) -> list[str]:
    """Lenses worth offering for the moment in front of the trader.

    Not a filter - a prompt. If earnings are hours away, "only earnings nights" is the
    question a person would think to ask next, and the interface can offer it rather
    than waiting to be asked.

    The frame runs to the present hour, so the offer is read off its last row, and the
    rarest qualifying condition is offered first: the unusual thing about tonight is
    the one worth asking about.
    """
    if frame.empty:
        return []
    row = frame.iloc[[-1]]
    n = len(frame)
    scored: list[tuple[float, str]] = []
    for x in LENSES:
        if not bool(x.mask(row).iloc[0]):
            continue
        share = float(x.mask(frame).sum()) / n
        if share > COMMONPLACE_SHARE:
            continue
        scored.append((share, x.name))
    scored.sort()
    return [name for _, name in scored[:MAX_SUGGESTIONS]]


def episodes(timestamps: pd.DatetimeIndex, separation_h: float) -> int:
    """A conservative count of the separate matches a set of hours can supply.

    The search keeps one match per episode - matches closer than ``separation_h`` count
    once - and refuses below a minimum number. Hours are grouped into runs (a gap of at
    least ``separation_h`` starts a new one), and a run of D hours is credited with
    ceil(D / (2 x separation_h)) matches, at least one: what a distance-ordered pick can
    be relied on to get out of it, not the most a time-ordered pick could squeeze.

    That is what makes the count honest where the hour count is not. "FOMC ahead" covers
    14,847 pooled hours and comes to 14 runs - one per meeting, the same dates for every
    token - under the 15 the search needs, which is why it was refused on 471 of 474
    FOMC nights. Pooling adds hours, not meetings.
    """
    if len(timestamps) == 0:
        return 0
    from nightwatch.time_utils import index_epoch_ns

    ns = np.unique(index_epoch_ns(pd.DatetimeIndex(timestamps)))
    sep = np.int64(round(separation_h * 3600)) * 1_000_000_000
    breaks = np.flatnonzero(np.diff(ns) >= sep)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [len(ns) - 1]))
    span_h = (ns[ends] - ns[starts]) / 3.6e12
    return int(np.maximum(1, np.ceil(span_h / (2 * separation_h))).sum())


def pooled_availability(frames: dict[str, pd.DataFrame], separation_h: float) -> dict[str, dict[str, int]]:
    """Per condition, the hours and the separate events across every token's history."""
    out: dict[str, dict[str, int]] = {}
    for x in LENSES:
        hours, stamps = 0, []
        for f in frames.values():
            m = x.mask(f)
            hours += int(m.sum())
            stamps.append(f.index[np.asarray(m, dtype=bool)])
        idx = stamps[0].append(stamps[1:]) if stamps else pd.DatetimeIndex([])
        out[x.name] = {"hours": hours, "episodes": episodes(idx, separation_h)}
    return out


def sample_sizes(frame: pd.DataFrame) -> dict[str, int]:
    """How many past hours each lens would leave, for showing the cost up front."""
    return {x.name: int(x.mask(frame).sum()) for x in LENSES}
