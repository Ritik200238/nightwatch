"""What this trade does to everything else you are holding.

A per-trade verdict can be right about the trade and wrong about the book. Three long
positions in different tokenized US stocks are not three independent bets: when the
market that prices all of them is shut and news lands, they gap together. This measures
that directly rather than assuming it.

What it answers:

* **Concentration.** Gross and net exposure against equity, the largest single name, and
  how much of the book sits in the top three.
* **Correlation, measured.** Hourly returns of the tokens the trader actually holds,
  over the same closed-market hours the analysis cares about. No assumed betas.
* **Diversification, or the lack of it.** The 5th-percentile loss of the book as a whole,
  against the sum of each position's own 5th-percentile loss. If the first is close to
  the second, the book is one bet in three names.
* **The marginal effect.** All of the above with and without the proposed trade, because
  that difference is the decision.

Everything is computed from stored hourly bars. Where history is too short to measure a
correlation honestly, the pair is reported as unknown rather than assumed to be zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

MIN_OVERLAP_HOURS = 240  # ten days of shared history before a correlation means anything
TAIL_PCT = 5.0


@dataclass(frozen=True)
class Position:
    ticker: str
    side: str  # "long" | "short"
    notional_quote: float

    @property
    def signed(self) -> float:
        return self.notional_quote * (1.0 if self.side == "long" else -1.0)


@dataclass(frozen=True)
class PairCorrelation:
    a: str
    b: str
    correlation: float | None
    overlap_hours: int


@dataclass(frozen=True)
class BookRisk:
    gross_quote: float
    net_quote: float
    gross_pct_of_equity: float | None
    net_pct_of_equity: float | None
    largest_name: str | None
    largest_pct_of_gross: float | None
    top3_pct_of_gross: float | None
    tail_loss_quote: float | None  # the book's own 5th-percentile loss over the horizon
    standalone_tail_sum_quote: float | None  # the same, if the names moved independently
    diversification_ratio: float | None  # 1.0 = no benefit at all


@dataclass(frozen=True)
class PortfolioReport:
    positions: list[Position]
    before: BookRisk
    after: BookRisk
    attribution: Any = None  # nightwatch.decision.attribution.Attribution
    correlations: list[PairCorrelation] = field(default_factory=list)
    mean_correlation_to_book: float | None = None
    notes: list[str] = field(default_factory=list)
    horizon_h: float = 24.0

    @property
    def adds_tail_quote(self) -> float | None:
        if self.before.tail_loss_quote is None or self.after.tail_loss_quote is None:
            return None
        return self.after.tail_loss_quote - self.before.tail_loss_quote


def _returns(frame: pd.DataFrame, horizon_h: int) -> pd.Series:
    """Overlapping returns over the holding period, on the token's own hourly closes."""
    close = frame["spot_close"].astype(float)
    return (close.shift(-horizon_h) / close - 1.0).dropna() * 100.0


def _book_risk(positions: list[Position], frames: dict[str, pd.DataFrame], *, equity: float | None, horizon_h: int) -> tuple[BookRisk, list[str]]:
    notes: list[str] = []
    if not positions:
        return BookRisk(0.0, 0.0, 0.0 if equity else None, 0.0 if equity else None, None, None, None, None, None, None), notes

    gross = sum(abs(p.notional_quote) for p in positions)
    net = sum(p.signed for p in positions)
    by_name: dict[str, float] = {}
    for p in positions:
        by_name[p.ticker] = by_name.get(p.ticker, 0.0) + abs(p.notional_quote)
    ranked = sorted(by_name.items(), key=lambda kv: kv[1], reverse=True)

    # The book's own tail: sum each position's P&L path, then take its 5th percentile.
    series = []
    standalone = 0.0
    have_all = True
    for p in positions:
        f = frames.get(p.ticker)
        if f is None or f.empty:
            have_all = False
            notes.append(f"no stored history for {p.ticker}: it is counted in exposure but not in the tail")
            continue
        r = _returns(f, horizon_h)
        if len(r) < MIN_OVERLAP_HOURS:
            have_all = False
            notes.append(f"{p.ticker} has only {len(r)} usable hours: too short for a tail")
            continue
        pnl = r * (p.signed / 100.0)  # quote P&L per historical window
        series.append(pnl.rename(p.ticker))
        standalone += abs(float(np.percentile(pnl.to_numpy(), TAIL_PCT)))

    tail = None
    div = None
    if series:
        aligned = pd.concat(series, axis=1, join="inner").dropna()
        if len(aligned) >= MIN_OVERLAP_HOURS:
            book_pnl = aligned.sum(axis=1).to_numpy()
            tail = float(np.percentile(book_pnl, TAIL_PCT))
            div = (abs(tail) / standalone) if standalone > 0 else None
        else:
            notes.append(f"only {len(aligned)} hours are shared by every position: not enough to combine them")
            have_all = False
    if not have_all and tail is not None:
        notes.append("the combined tail covers only the positions with enough history")

    return (
        BookRisk(
            gross_quote=gross, net_quote=net,
            gross_pct_of_equity=(gross / equity * 100.0) if equity else None,
            net_pct_of_equity=(net / equity * 100.0) if equity else None,
            largest_name=ranked[0][0] if ranked else None,
            largest_pct_of_gross=(ranked[0][1] / gross * 100.0) if gross else None,
            top3_pct_of_gross=(sum(v for _, v in ranked[:3]) / gross * 100.0) if gross else None,
            tail_loss_quote=tail, standalone_tail_sum_quote=-standalone if standalone else None,
            diversification_ratio=div,
        ),
        notes,
    )


def correlations(positions: list[Position], frames: dict[str, pd.DataFrame], *, horizon_h: int, focus: str | None = None) -> list[PairCorrelation]:
    """Measured correlation of holding-period returns between every pair held."""
    names = sorted({p.ticker for p in positions})
    out: list[PairCorrelation] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, fb = frames.get(a), frames.get(b)
            if fa is None or fb is None or fa.empty or fb.empty:
                out.append(PairCorrelation(a, b, None, 0))
                continue
            ra, rb = _returns(fa, horizon_h), _returns(fb, horizon_h)
            joined = pd.concat([ra.rename("a"), rb.rename("b")], axis=1, join="inner").dropna()
            if len(joined) < MIN_OVERLAP_HOURS:
                out.append(PairCorrelation(a, b, None, len(joined)))
                continue
            out.append(PairCorrelation(a, b, float(joined["a"].corr(joined["b"])), len(joined)))
    if focus:
        out.sort(key=lambda c: (focus not in (c.a, c.b), -(abs(c.correlation) if c.correlation is not None else -1)))
    return out


def evaluate(
    existing: list[Position],
    proposed: Position | None,
    frames: dict[str, pd.DataFrame],
    *,
    equity: float | None,
    horizon_h: float = 24.0,
) -> PortfolioReport:
    """Risk of the book as held, and as it would be with the proposed trade added."""
    h = max(1, int(round(horizon_h)))
    after_positions = existing + ([proposed] if proposed else [])
    before, notes_b = _book_risk(existing, frames, equity=equity, horizon_h=h)
    after, notes_a = _book_risk(after_positions, frames, equity=equity, horizon_h=h)

    pairs = correlations(after_positions, frames, horizon_h=h, focus=proposed.ticker if proposed else None)
    mean_corr = None
    if proposed:
        touching = [c.correlation for c in pairs if proposed.ticker in (c.a, c.b) and c.correlation is not None]
        mean_corr = float(np.mean(touching)) if touching else None

    from nightwatch.decision.attribution import attribute

    attribution = attribute(after_positions, frames, horizon_h=h)
    notes = list(dict.fromkeys(notes_b + notes_a))
    if proposed and mean_corr is not None and mean_corr > 0.7:
        notes.append(f"{proposed.ticker} moves with the rest of the book (mean correlation {mean_corr:.2f}): this adds size, not diversification")
    if after.diversification_ratio is not None and after.diversification_ratio > 0.9 and len(after_positions) > 1:
        notes.append("the book's tail is almost the sum of its parts, so these names are one bet")
    return PortfolioReport(positions=after_positions, before=before, after=after, attribution=attribution, correlations=pairs, mean_correlation_to_book=mean_corr, notes=notes, horizon_h=float(h))
