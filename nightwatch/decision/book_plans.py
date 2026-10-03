"""What to do about a book that is over its limit, and how far it is from breaking.

The book view elsewhere (``portfolio``, ``attribution``) says how bad the whole book's
bad case is and which position carries it. Three things were still missing, and all
three are here, all deterministic, all read off the same historical windows the book tail
uses (so a number here can never disagree with the one on the page):

* **The whole book through the crashes.** The five crash weeks the single-ticket stress
  already replays (COVID, 2022, March 2023, August 2024, April 2025), applied to every
  holding at once on the *same* market day, so the book's loss is one coherent day and
  not five separate worst cases added together.
* **Rebalance plans.** When the book with the new trade breaches its one-in-twenty
  limit, two or three concrete alternatives - take the trade smaller, trim the holding
  that carries most of the bad case, hedge that name with its Bitget perpetual - each
  solved for the smallest change that gets back inside the limit, then *re-scored* on the
  same windows and the same crashes, so the before and after are measured, not argued.
* **Book-level reverse stress.** Instead of "what does this move cost", "what move costs
  the limit": the common shock that takes the book to its loss limit, how often history's
  windows reached that loss, and where a leveraged leg would be liquidated relative to it.

Nothing here is a model of the future. A plan is "had you held this instead, here is what
the same past would have done to it". What a plan does not include is said in its notes
(funding on a perp, tax, slippage on the trim beyond a taker fee).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nightwatch.decision.portfolio import TAIL_PCT, BookModel, Position, _sign

GRID_STEPS = 20  # plan amounts are found in 5% steps of the leg they act on
SIZE_GRID = 64
SIZE_REFINE = 24
MIN_PLAN_NOTIONAL = 1.0
MAX_PLANS = 3


@dataclass(frozen=True)
class BookScore:
    """One version of the book (as asked, or after a plan) scored on the shared windows."""

    tail_quote: float  # one-in-twenty P&L, negative = loss
    tail_pct_of_equity: float | None
    worst_window_quote: float  # the single worst historical window
    worst_crash_quote: float | None  # the worst of the crash replays
    worst_crash_name: str | None
    inside_limit: bool | None  # None when there is no equity to state a limit against


@dataclass(frozen=True)
class RebalancePlan:
    lever: str  # "smaller_trade" | "skip_trade" | "trim_holding" | "hedge_perp"
    ticker: str  # the name the lever acts on
    amount_quote: float  # notional the lever moves (trimmed, hedged, or the new smaller size)
    fraction: float | None  # of that leg trimmed / hedged
    cost_quote: float  # taker fees to do it (funding on a perp is not in here)
    before: BookScore  # the book as asked
    after: BookScore
    achieves_limit: bool
    detail: str  # one plain English line
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CrashRow:
    key: str
    name: str
    date: str | None  # the market day used
    held_quote: float | None  # the book as held, no new trade
    asked_quote: float | None  # with the new trade at the size asked
    worst_ticker: str | None  # who lost most that day (with the trade)
    missing: list[str] = field(default_factory=list)  # holdings with no replay data that day


@dataclass(frozen=True)
class ReverseLevel:
    key: str  # "limit" | "ten_pct"
    loss_quote: float
    loss_pct_of_equity: float
    shock_pct_before: float | None  # common move against the book that costs this much
    shock_pct_after: float | None
    windows_hit_before: int
    windows_hit_after: int


@dataclass(frozen=True)
class LegLiquidation:
    ticker: str
    leverage: float
    distance_pct: float  # move against the leg that closes it out (Bitget margin tiers)
    windows_hit: int  # windows whose hold-end move reached it (touches along the way: see the leverage section)
    windows: int
    comes_before_limit: bool | None  # liquidates at a smaller common move than the loss limit costs


@dataclass(frozen=True)
class BookStress:
    limit_quote: float | None
    limit_pct_of_equity: float | None
    breached: bool | None  # the book with the trade, as asked, is past the limit
    book_alone_over_limit: bool
    windows: int
    direction: str | None  # "down" if the book is net long, "up" if net short, None if flat
    asked_score: BookScore | None
    crashes: list[CrashRow] = field(default_factory=list)
    plans: list[RebalancePlan] = field(default_factory=list)
    reverse: list[ReverseLevel] = field(default_factory=list)
    liquidation: LegLiquidation | None = None
    notes: list[str] = field(default_factory=list)


def _crash_table() -> dict[str, Any]:
    from nightwatch.stress.scenarios import crash_replays

    return crash_replays()


def _crash_kind(horizon_h: float) -> str:
    from nightwatch.stress.scenarios import REPLAY_D3_AFTER_H

    return "d3" if horizon_h > REPLAY_D3_AFTER_H else "gap"


@dataclass(frozen=True)
class _Leg:
    ticker: str
    signed: float  # signed quote notional of the leg as it stands in the asked book
    kind: str  # "held" (has a column in the windows), "crash_only" (no stored history), "new"
    col: int | None = None  # column in model.positions_pnl for a held leg


class _Scorer:
    """Scores a set of per-leg scales (1 = as held, 0.5 = half of it, 0 = gone) on the windows."""

    def __init__(self, model: BookModel, legs: list[_Leg], equity: float | None, budget: float | None, horizon_h: float, table: dict[str, Any]) -> None:
        self.model, self.legs, self.equity, self.budget = model, legs, equity, budget
        self.table, self.kind = table, _crash_kind(horizon_h)
        self.meta = (table.get("_meta") or {}).get("windows") or {}
        self.mat = model.positions_pnl.to_numpy()
        self.unit = model.unit

    def pnl(self, scales: list[float]) -> np.ndarray:
        out = np.zeros(self.model.windows)
        for leg, s in zip(self.legs, scales, strict=True):
            if not s:
                continue
            if leg.kind == "held":
                out = out + self.mat[:, leg.col] * s
            elif leg.kind == "new" and self.unit is not None:
                out = out + self.unit * (leg.signed * s)
        return out

    def tail(self, scales: list[float]) -> float:
        return float(np.percentile(self.pnl(scales), TAIL_PCT))

    def loss(self, scales: list[float]) -> float:
        return max(0.0, -self.tail(scales))

    def crash_rows(self, scales: list[float]) -> list[CrashRow]:
        rows: list[CrashRow] = []
        for key, info in self.meta.items():
            held_q = asked_q = None
            worst_t = None
            date = None
            missing: list[str] = []
            for way in ("down", "up"):
                tot_held = tot_all = 0.0
                seen_all = seen_held = False
                per: dict[str, float] = {}
                miss = []
                for leg, s in zip(self.legs, scales, strict=True):
                    m = ((self.table.get(leg.ticker) or {}).get(key) or {}).get(f"{self.kind}_{way}_pct")
                    if m is None:
                        miss.append(leg.ticker)
                        continue
                    v = leg.signed * s * m / 100.0
                    tot_all += v
                    seen_all = True
                    if leg.kind != "new":
                        tot_held += v
                        seen_held = True
                    per[leg.ticker] = per.get(leg.ticker, 0.0) + v
                cand_all = tot_all if seen_all else None
                cand_held = tot_held if seen_held else None
                if cand_all is not None and (asked_q is None or cand_all < asked_q):
                    asked_q = cand_all
                    date = (info.get("market_days") or {}).get(f"{self.kind}_{way}")
                    worst_t = min(per, key=per.get) if per else None
                    missing = sorted(set(miss))
                if cand_held is not None and (held_q is None or cand_held < held_q):
                    held_q = cand_held
            rows.append(CrashRow(key, info.get("name", key), date, held_q, asked_q, worst_t, missing))
        return rows

    def worst_crash(self, scales: list[float]) -> tuple[float | None, str | None]:
        rows = [r for r in self.crash_rows(scales) if r.asked_quote is not None]
        if not rows:
            return None, None
        r = min(rows, key=lambda x: x.asked_quote)  # type: ignore[arg-type,return-value]
        return r.asked_quote, r.name

    def score(self, scales: list[float]) -> BookScore:
        pnl = self.pnl(scales)
        tail = float(np.percentile(pnl, TAIL_PCT))
        crash_q, crash_n = self.worst_crash(scales)
        return BookScore(
            tail_quote=tail,
            tail_pct_of_equity=(tail / self.equity * 100.0) if self.equity else None,
            worst_window_quote=float(pnl.min()) if len(pnl) else 0.0,
            worst_crash_quote=crash_q, worst_crash_name=crash_n,
            inside_limit=(max(0.0, -tail) <= self.budget + 1e-9) if self.budget is not None else None,
        )


def _smallest_fraction(loss_at, target: float) -> float | None:
    """Smallest fraction of a leg (in 5% steps) at which the loss is inside ``target``."""
    for i in range(1, GRID_STEPS + 1):
        f = i / GRID_STEPS
        if loss_at(f) <= target + 1e-9:
            return f
    return None


def _fmt(x: float) -> str:
    return f"{abs(x):,.0f}"


def build(
    model: BookModel | None,
    existing: list[Position],
    proposed: Position | None,
    *,
    equity: float | None,
    limit_pct_of_equity: float,
    horizon_h: float,
    perp_names: set[str],
    spot_taker: float,
    perp_taker: float,
    leverage: dict[str, Any] | None = None,
    table: dict[str, Any] | None = None,
) -> BookStress | None:
    """Score the book through the crashes, plan a way back inside the limit, and reverse-stress it.

    ``perp_names`` is the set of tickers that have a Bitget perpetual (hedgeable);
    ``leverage`` is the report's leverage block for the new trade, if it is leveraged.
    Returns None when the book cannot be measured at all.
    """
    if model is None or not existing:
        return None
    table = _crash_table() if table is None else table
    cols = list(model.positions_pnl.columns)
    legs: list[_Leg] = []
    for ci, c in enumerate(cols):
        idx = int(str(c).split(":", 1)[0])
        p = existing[idx]
        legs.append(_Leg(p.ticker, p.signed, "held", ci))
    legs += [_Leg(p.ticker, p.signed, "crash_only") for p in existing if p.ticker in model.unknown]
    new_leg = None
    if proposed is not None and model.unit is not None:
        new_leg = _Leg(proposed.ticker, proposed.signed, "new")
        legs.append(new_leg)
    budget = equity * limit_pct_of_equity / 100.0 if equity else None
    sc = _Scorer(model, legs, equity, budget, horizon_h, table)
    n = len(legs)
    as_asked = [1.0] * n
    held_only = [1.0] * (n - 1) + [0.0] if new_leg else as_asked
    notes: list[str] = []
    if model.unknown:
        notes.append(f"{', '.join(model.unknown)}: no stored history, so left out of the windows (the crash replays use their own daily table)")

    asked = sc.score(as_asked)
    alone_loss = sc.loss(held_only)
    asked_loss = max(0.0, -asked.tail_quote)
    breached = (asked_loss > budget + 1e-9) if budget is not None else None

    # --- crashes: the whole book on one market day ---
    crashes = sc.crash_rows(as_asked)

    # --- plans ---
    plans: list[RebalancePlan] = []
    if breached and budget is not None and new_leg is not None:
        plans = _plans(sc, legs, as_asked, held_only, asked, budget, proposed, perp_names, spot_taker, perp_taker, notes)

    # --- reverse stress ---
    reverse, direction = _reverse(model, existing, proposed, new_leg is not None, equity, budget)
    liq = _liquidation(model, proposed, leverage, reverse, new_leg is not None)

    return BookStress(
        limit_quote=budget, limit_pct_of_equity=limit_pct_of_equity if budget is not None else None,
        breached=breached, book_alone_over_limit=bool(budget is not None and alone_loss > budget + 1e-9),
        windows=model.windows, direction=direction, asked_score=asked, crashes=crashes, plans=plans,
        reverse=reverse, liquidation=liq, notes=notes,
    )


def _plans(sc: _Scorer, legs: list[_Leg], as_asked: list[float], held_only: list[float], asked: BookScore, budget: float,
           proposed: Position, perp_names: set[str], spot_taker: float, perp_taker: float, notes: list[str]) -> list[RebalancePlan]:
    n = len(legs)
    new_i = n - 1
    out: list[RebalancePlan] = []

    # who carries the bad case, measured in the windows where the asked book is worst
    pnl = sc.pnl(as_asked)
    worst_mask = pnl <= np.percentile(pnl, TAIL_PCT)
    comp: list[float] = []
    for i in range(n):
        one = [0.0] * n
        one[i] = 1.0
        comp.append(float(sc.pnl(one)[worst_mask].mean()))
    order = sorted(range(n), key=lambda i: comp[i])  # most negative first

    def with_scale(i: int, s: float) -> list[float]:
        v = list(as_asked)
        v[i] = s
        return v

    # A. the new trade, smaller
    grid = [proposed.notional_quote * k / SIZE_GRID for k in range(SIZE_GRID + 1)]

    def loss_new(size: float) -> float:
        return sc.loss(with_scale(new_i, size / proposed.notional_quote))

    inside = [g for g in grid if loss_new(g) <= budget + 1e-9]
    if inside and max(inside) >= MIN_PLAN_NOTIONAL:
        lo = max(inside)
        hi = min((g for g in grid if g > lo), default=proposed.notional_quote)
        for _ in range(SIZE_REFINE):
            mid = (lo + hi) / 2
            if loss_new(mid) <= budget:
                lo = mid
            else:
                hi = mid
        sc_ = with_scale(new_i, lo / proposed.notional_quote)
        out.append(RebalancePlan(
            "smaller_trade", proposed.ticker, lo, lo / proposed.notional_quote, 0.0, asked, sc.score(sc_), True,
            f"take {proposed.ticker} at {_fmt(lo)} instead of {_fmt(proposed.notional_quote)}",
        ))
    else:
        off = sc.score(held_only)
        out.append(RebalancePlan(
            "skip_trade", proposed.ticker, 0.0, 0.0, 0.0, asked, off, bool(off.inside_limit),
            f"skip the {proposed.ticker} trade: no size of it fits" + ("" if off.inside_limit else ", and the book on its own is already past the limit"),
        ))

    # B. trim the holding that carries most of the bad case (held positions only)
    held_order = [i for i in order if legs[i].kind == "held" and comp[i] < 0]
    if held_order:
        i = held_order[0]
        leg = legs[i]
        f = _smallest_fraction(lambda x: sc.loss(with_scale(i, 1.0 - x)), budget)
        achieves = f is not None
        f = f if f is not None else 1.0
        trimmed = abs(leg.signed) * f
        out.append(RebalancePlan(
            "trim_holding", leg.ticker, trimmed, f, spot_taker * trimmed, asked, sc.score(with_scale(i, 1.0 - f)), achieves,
            f"trim {leg.ticker} by {f * 100:.0f}% ({_fmt(trimmed)}), the holding that carries most of the bad case"
            + ("" if achieves else "; even closing it does not get the book inside the limit"),
            ["a trim realises gains or losses on the held position; tax is not counted"],
        ))

    # C. hedge the carrier with its own Bitget perpetual
    for i in order:
        if comp[i] >= 0:
            break
        leg = legs[i]
        if leg.kind == "crash_only" or leg.ticker not in perp_names:
            continue
        f = _smallest_fraction(lambda x, i=i: sc.loss(with_scale(i, 1.0 - x)), budget)
        achieves = f is not None
        f = f if f is not None else 1.0
        hedged = abs(leg.signed) * f
        out.append(RebalancePlan(
            "hedge_perp", leg.ticker, hedged, f, 2.0 * perp_taker * hedged, asked, sc.score(with_scale(i, 1.0 - f)), achieves,
            f"hedge {f * 100:.0f}% of {leg.ticker} ({_fmt(hedged)}) with a {'short' if leg.signed > 0 else 'long'} on its Bitget perpetual",
            ["modelled as the perp tracking the stock one for one; funding paid or earned while it is open is not counted",
             "the cost is a taker fee to open and again to close"],
        ))
        break
    if all(p.lever != "hedge_perp" for p in out) and order and comp[order[0]] < 0:
        notes.append(f"{legs[order[0]].ticker} carries most of the bad case but has no Bitget perpetual to hedge it with")

    out.sort(key=lambda p: (not p.achieves_limit, p.cost_quote + (0.0 if p.lever != "skip_trade" else 1e12)))
    return out[:MAX_PLANS]


def _reverse(model: BookModel, existing: list[Position], proposed: Position | None, has_new: bool, equity: float | None, budget: float | None) -> tuple[list[ReverseLevel], str | None]:
    if not equity or budget is None:
        return [], None
    held_net = sum(p.signed for p in existing if p.ticker not in model.unknown)
    after_net = held_net + (proposed.signed if proposed is not None and has_new else 0.0)
    direction = "down" if after_net > 1e-9 else "up" if after_net < -1e-9 else None
    pnl_b = model.pnl()
    pnl_a = model.pnl(proposed.notional_quote, proposed.side) if proposed is not None and has_new else pnl_b
    levels: list[ReverseLevel] = []
    for key, loss in (("limit", budget), ("ten_pct", equity * 0.10)):
        def shock(net: float, loss: float = loss) -> float | None:
            return (loss / abs(net) * 100.0) if abs(net) > 1e-9 else None

        levels.append(ReverseLevel(
            key, loss, loss / equity * 100.0, shock(held_net), shock(after_net),
            int((pnl_b <= -loss).sum()), int((pnl_a <= -loss).sum()),
        ))
    return levels, direction


def _liquidation(model: BookModel, proposed: Position | None, lev: dict[str, Any] | None, reverse: list[ReverseLevel], has_new: bool) -> LegLiquidation | None:
    if not lev or proposed is None or not has_new or model.unit is None:
        return None
    d, x = lev.get("liquidation_distance_pct"), lev.get("leverage")
    if d is None or not x or lev.get("perp_symbol") is None:
        return None
    r = model.unit * 100.0
    hit = int((r <= -d).sum()) if _sign(proposed.side) > 0 else int((r >= d).sum())
    limit_shock = next((lv.shock_pct_after for lv in reverse if lv.key == "limit"), None)
    return LegLiquidation(
        ticker=proposed.ticker, leverage=float(x), distance_pct=float(d), windows_hit=hit, windows=model.windows,
        comes_before_limit=(d < limit_shock) if limit_shock is not None else None,
    )
