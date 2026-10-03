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
  that difference is the decision. Both books are read off the same historical windows
  (see ``BookModel``), and the model is also what the sizing cap solves against, so the
  number on the page and the size the desk recommends cannot disagree.

Everything is computed from stored hourly bars. Where history is too short to measure a
correlation or a tail honestly, the pair or the holding is reported as unknown and left
out, never assumed to be zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    # Holdings left out of the tail for want of stored history. Never assumed to be flat.
    unknown: list[str] = field(default_factory=list)
    worst_window: str | None = None  # start of the historical window in which the book lost most
    same_name: dict | None = None  # the new trade's name already held: held, combined, share of equity
    windows: int = 0  # how many shared historical windows the tail was read from
    # Filled once the verdict is known: the book with the trade at the size the desk
    # recommends, and the book cap that helped size it (see nightwatch.decision.sizing).
    tail_after_recommended_quote: float | None = None
    book_cap_quote: float | None = None
    book_cap_pct_of_equity: float | None = None
    book_cap_binds: bool = False
    # Crash replays of the whole book, rebalance plans and the book-level reverse stress
    # (nightwatch.decision.book_plans). Filled by the pipeline once the policy is known.
    stress: Any = None

    @property
    def adds_tail_quote(self) -> float | None:
        if self.before.tail_loss_quote is None or self.after.tail_loss_quote is None:
            return None
        return self.after.tail_loss_quote - self.before.tail_loss_quote


def _returns(frame: pd.DataFrame, horizon_h: int) -> pd.Series:
    """Overlapping returns over the holding period, on the token's own hourly closes."""
    close = frame["spot_close"].astype(float)
    return (close.shift(-horizon_h) / close - 1.0).dropna() * 100.0


def _sign(side: str) -> float:
    return 1.0 if str(getattr(side, "value", side)) == "long" else -1.0


@dataclass(frozen=True)
class BookModel:
    """The held book and the candidate trade on one shared set of historical windows.

    Every holding, and the trade being asked about, is scored over the *same* rolling
    windows, of the *same* length as the ticket's hold, on the hours all of them have
    history for (an inner join on the window start time). That is what makes a
    combination honest: a tail is only the tail of a book if its parts were measured at
    the same moments.

    ``base`` is the held positions' summed P&L in quote per window; ``unit`` is the
    candidate token's return per window as a fraction, which times a signed notional is
    that trade's P&L. Together they give the book's tail at any size of the new trade
    without re-reading a bar.
    """

    times: pd.DatetimeIndex
    base: np.ndarray
    unit: np.ndarray | None
    positions_pnl: pd.DataFrame  # one column per held position that has history
    known: tuple[str, ...]
    unknown: tuple[str, ...]
    horizon_h: int

    @property
    def windows(self) -> int:
        return len(self.base)

    def pnl(self, notional: float = 0.0, side: str = "long") -> np.ndarray:
        if self.unit is None or not notional:
            return self.base
        return self.base + self.unit * (notional * _sign(side))

    def tail(self, notional: float = 0.0, side: str = "long") -> float:
        """The book's one-in-twenty P&L (negative = a loss) with ``notional`` of the trade added."""
        return float(np.percentile(self.pnl(notional, side), TAIL_PCT))

    def worst_window(self, notional: float = 0.0, side: str = "long") -> str | None:
        """The start of the historical window in which the book lost most."""
        pnl = self.pnl(notional, side)
        if not len(pnl):
            return None
        return pd.Timestamp(self.times[int(np.argmin(pnl))]).isoformat()

    def standalone_tail_sum(self, notional: float = 0.0, side: str = "long") -> float:
        """Each position's own one-in-twenty loss, added up as if they never moved together."""
        total = sum(abs(float(np.percentile(self.positions_pnl[c].to_numpy(), TAIL_PCT))) for c in self.positions_pnl.columns)
        if self.unit is not None and notional:
            total += abs(float(np.percentile(self.unit * (notional * _sign(side)), TAIL_PCT)))
        return total


BuiltBook = tuple["BookModel | None", list[str], tuple[str, ...]]


def build_book_model(existing: list[Position], ticker: str | None, frames: dict[str, pd.DataFrame], *, horizon_h: int) -> BuiltBook:
    """Score the held book, and ``ticker`` if given, over their shared windows.

    Returns the model (None if no window is shared by enough history to say anything),
    notes, and the holdings left out for want of history. A holding with no usable
    history is reported as unknown and excluded; it is never assumed to be flat.
    """
    notes: list[str] = []
    unknown: list[str] = []
    cols: dict[str, pd.Series] = {}
    for i, p in enumerate(existing):
        f = frames.get(p.ticker)
        if f is None or f.empty:
            unknown.append(p.ticker)
            notes.append(f"no stored history for {p.ticker}: it is counted in exposure but not in the tail")
            continue
        r = _returns(f, horizon_h)
        if len(r) < MIN_OVERLAP_HOURS:
            unknown.append(p.ticker)
            notes.append(f"{p.ticker} has only {len(r)} usable hours: too short for a tail")
            continue
        cols[f"{i}:{p.ticker}"] = r * (p.signed / 100.0)  # quote P&L per historical window
    unit = None
    if ticker:
        f = frames.get(ticker)
        r = _returns(f, horizon_h) if f is not None and not f.empty else None
        if r is not None and len(r) >= MIN_OVERLAP_HOURS:
            unit = r / 100.0
        else:
            notes.append(f"{ticker} has too little stored history to measure how it adds to the book")
    unknown_t = tuple(dict.fromkeys(unknown))
    if not cols:
        return None, notes, unknown_t
    known = tuple(dict.fromkeys(p.ticker for p in existing if p.ticker not in unknown_t))
    series = [s.rename(k) for k, s in cols.items()] + ([unit.rename("__new__")] if unit is not None else [])
    joint = pd.concat(series, axis=1, join="inner").dropna()  # identical window starts for every part
    if len(joint) < MIN_OVERLAP_HOURS:
        notes.append(f"only {len(joint)} hours are shared by every position: not enough to combine them")
        return None, notes, unknown_t
    positions_pnl = joint[list(cols)]
    if unknown_t:
        notes.append("the combined tail covers only the positions with enough history")
    model = BookModel(
        times=pd.DatetimeIndex(joint.index), base=positions_pnl.sum(axis=1).to_numpy(),
        unit=joint["__new__"].to_numpy() if unit is not None else None,
        positions_pnl=positions_pnl, known=known, unknown=unknown_t, horizon_h=horizon_h,
    )
    return model, notes, unknown_t


def same_name_exposure(existing: Any, ticker: str, side: str) -> tuple[float, float]:  # noqa: ANN401
    """(signed quote already held in ``ticker``, the part of it running the same way as ``side``).

    Existing NVDA plus a new NVDA is one position as far as concentration goes. A held
    position the other way does not relax the limit; it counts as zero in the second figure.
    """
    held = 0.0
    for p in existing:
        t, s, n = (p.ticker, p.side, p.notional_quote) if isinstance(p, Position) else (str(p[0]).upper(), p[1], float(p[2]))
        if t == ticker:
            held += n * _sign(s)
    return held, max(0.0, held * _sign(side))


def _exposure(positions: list[Position], *, equity: float | None) -> BookRisk:
    if not positions:
        return BookRisk(0.0, 0.0, 0.0 if equity else None, 0.0 if equity else None, None, None, None, None, None, None)
    gross = sum(abs(p.notional_quote) for p in positions)
    net = sum(p.signed for p in positions)
    by_name: dict[str, float] = {}
    for p in positions:
        by_name[p.ticker] = by_name.get(p.ticker, 0.0) + abs(p.notional_quote)
    ranked = sorted(by_name.items(), key=lambda kv: kv[1], reverse=True)
    return BookRisk(
        gross_quote=gross, net_quote=net,
        gross_pct_of_equity=(gross / equity * 100.0) if equity else None,
        net_pct_of_equity=(net / equity * 100.0) if equity else None,
        largest_name=ranked[0][0] if ranked else None,
        largest_pct_of_gross=(ranked[0][1] / gross * 100.0) if gross else None,
        top3_pct_of_gross=(sum(v for _, v in ranked[:3]) / gross * 100.0) if gross else None,
        tail_loss_quote=None, standalone_tail_sum_quote=None, diversification_ratio=None,
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
    built: BuiltBook | None = None,
) -> PortfolioReport:
    """Risk of the book as held, and as it would be with the proposed trade added.

    The tail of both books is read off the same windows (see ``BookModel``), so the
    difference between them is the trade's doing and nothing else. ``built`` lets a
    caller that already made the model (the pipeline, which also sizes against it) pass
    it in instead of paying for it twice.
    """
    h = max(1, int(round(horizon_h)))
    after_positions = existing + ([proposed] if proposed else [])
    model, m_notes, unknown = built if built is not None else build_book_model(existing, proposed.ticker if proposed else None, frames, horizon_h=h)
    before = _exposure(existing, equity=equity)
    after = _exposure(after_positions, equity=equity)
    worst = None
    if model is not None:
        n, side = (proposed.notional_quote, proposed.side) if proposed and model.unit is not None else (0.0, "long")
        tail_b, tail_a = model.tail(), model.tail(n, side)
        stand_b, stand_a = model.standalone_tail_sum(), model.standalone_tail_sum(n, side)
        before = replace(before, tail_loss_quote=tail_b, standalone_tail_sum_quote=-stand_b if stand_b else None,
                         diversification_ratio=(abs(tail_b) / stand_b) if stand_b > 0 else None)
        after = replace(after, tail_loss_quote=tail_a, standalone_tail_sum_quote=-stand_a if stand_a else None,
                        diversification_ratio=(abs(tail_a) / stand_a) if stand_a > 0 else None)
        worst = model.worst_window(n, side)

    pairs = correlations(after_positions, frames, horizon_h=h, focus=proposed.ticker if proposed else None)
    mean_corr = None
    if proposed:
        touching = [c.correlation for c in pairs if proposed.ticker in (c.a, c.b) and c.correlation is not None]
        mean_corr = float(np.mean(touching)) if touching else None

    from nightwatch.decision.attribution import attribute

    attribution = attribute(after_positions, frames, horizon_h=h)
    notes = list(dict.fromkeys(m_notes))
    if proposed and mean_corr is not None and mean_corr > 0.7:
        notes.append(f"{proposed.ticker} moves with the rest of the book (mean correlation {mean_corr:.2f}): this adds size, not diversification")
    if after.diversification_ratio is not None and after.diversification_ratio > 0.9 and len(after_positions) > 1:
        notes.append("the book's tail is almost the sum of its parts, so these names are one bet")
    same = None
    if proposed:
        held, same_way = same_name_exposure(existing, proposed.ticker, proposed.side)
        if held:
            combined = held + proposed.signed
            same = {
                "ticker": proposed.ticker, "held_signed_quote": held, "combined_signed_quote": combined,
                "combined_pct_of_equity": (abs(combined) / equity * 100.0) if equity else None,
                "same_direction_quote": same_way,
            }
            notes.append(f"you already hold {abs(held):,.0f} of {proposed.ticker} {'long' if held > 0 else 'short'}; with this trade that name is {abs(combined):,.0f}")
    return PortfolioReport(
        positions=after_positions, before=before, after=after, attribution=attribution, correlations=pairs,
        mean_correlation_to_book=mean_corr, notes=notes, horizon_h=float(h), unknown=list(unknown),
        worst_window=worst, same_name=same, windows=model.windows if model is not None else 0,
    )
