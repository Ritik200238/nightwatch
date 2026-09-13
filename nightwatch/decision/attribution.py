"""Which position is actually carrying the risk.

A book-level tail number says how bad the bad case is. It does not say who is responsible
for it, and the two are often different: the largest position is not always the one
driving the loss, and a small position in something that moves with everything else can
contribute more than a big position in something that does not.

Two measures, both computed from the same historical P&L paths the book tail uses:

* **Component risk.** Split the book's tail loss among its positions so the parts add up
  to the whole. Each position's share is its average P&L in exactly those historical
  windows where the book was in its worst 5%. That is the honest version of the
  question, because it is measured in the states that matter rather than assumed from a
  covariance.
* **Marginal risk.** What the book's tail would be without a position, and the difference.
  This answers "should I cut this one", which the component share does not: a position
  can carry a large share and still be the one holding the book together.

Where a position has no usable history it is reported as unknown, never as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nightwatch.decision.portfolio import MIN_OVERLAP_HOURS, TAIL_PCT, Position, _returns


@dataclass(frozen=True)
class Contribution:
    ticker: str
    side: str
    notional_quote: float
    share_of_gross: float
    component_quote: float | None  # average P&L of this position in the book's worst windows
    component_share: float | None  # its fraction of the book's tail loss
    marginal_quote: float | None  # how much worse the tail is because this position is held
    note: str = ""


@dataclass(frozen=True)
class Attribution:
    book_tail_quote: float | None
    n_windows: int
    contributions: list[Contribution] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def worst_contributor(self) -> Contribution | None:
        scored = [c for c in self.contributions if c.component_quote is not None]
        return min(scored, key=lambda c: c.component_quote) if scored else None


def _pnl_matrix(positions: list[Position], frames: dict[str, pd.DataFrame], horizon_h: int) -> tuple[pd.DataFrame, list[str]]:
    """Historical quote P&L per position on a shared index, and what had to be left out."""
    notes: list[str] = []
    cols = {}
    for p in positions:
        f = frames.get(p.ticker)
        if f is None or f.empty:
            notes.append(f"{p.ticker}: no stored history")
            continue
        r = _returns(f, horizon_h)
        if len(r) < MIN_OVERLAP_HOURS:
            notes.append(f"{p.ticker}: only {len(r)} usable hours")
            continue
        key = f"{p.ticker}|{p.side}|{p.notional_quote:g}"
        cols[key] = r * (p.signed / 100.0)
    if not cols:
        return pd.DataFrame(), notes
    return pd.concat(cols, axis=1, join="inner").dropna(), notes


def attribute(positions: list[Position], frames: dict[str, pd.DataFrame], *, horizon_h: float = 24.0) -> Attribution:
    """Split the book's tail loss among the positions, and price removing each one."""
    h = max(1, int(round(horizon_h)))
    gross = sum(abs(p.notional_quote) for p in positions) or 1.0
    mat, notes = _pnl_matrix(positions, frames, h)
    if mat.empty or len(mat) < MIN_OVERLAP_HOURS:
        return Attribution(
            book_tail_quote=None, n_windows=int(len(mat)),
            contributions=[Contribution(p.ticker, p.side, p.notional_quote, abs(p.notional_quote) / gross, None, None, None, "not enough shared history") for p in positions],
            notes=notes + (["not enough history shared by the positions to attribute anything"] if not mat.empty else []),
        )

    book = mat.sum(axis=1)
    tail_cut = float(np.percentile(book.to_numpy(), TAIL_PCT))
    worst = book <= tail_cut  # the historical windows that define the book's bad case
    book_tail = float(book[worst].mean())

    contributions: list[Contribution] = []
    for p in positions:
        key = f"{p.ticker}|{p.side}|{p.notional_quote:g}"
        share = abs(p.notional_quote) / gross
        if key not in mat.columns:
            contributions.append(Contribution(p.ticker, p.side, p.notional_quote, share, None, None, None, "no usable history"))
            continue
        component = float(mat.loc[worst, key].mean())
        without = book - mat[key]
        tail_without = float(np.percentile(without.to_numpy(), TAIL_PCT))
        contributions.append(
            Contribution(
                ticker=p.ticker, side=p.side, notional_quote=p.notional_quote, share_of_gross=share,
                component_quote=component, component_share=(component / book_tail) if book_tail else None,
                marginal_quote=tail_cut - tail_without,  # negative: the book's tail is worse for holding it
            )
        )
    return Attribution(book_tail_quote=book_tail, n_windows=int(len(mat)), contributions=contributions, notes=notes)
