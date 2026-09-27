"""Leverage: where the exchange closes the position, and how often history got there.

A tokenized stock is spot; leverage on it is taken on Bitget's USDT-margined perpetual
for the same stock. A leveraged position has a failure mode a spot one does not: the
exchange closes it when the margin left falls to the maintenance requirement, and the
trader loses the margin rather than riding the move back. For an overnight or weekend
hold that is the question that matters most - "at what price am I liquidated, and how
often did moments like this one get there?" - and before this module it was not asked:
"5x long NVDA" was quietly analysed as a spot trade.

Liquidation price (isolated margin)
-----------------------------------
With entry E, leverage L, maintenance-margin rate m and the taker fee f charged when
the exchange closes the position, the margin left at price P for a long is
``E/L + (P - E)`` per unit, and the exchange closes when that reaches ``P·(m + f)``:

    long   P_liq = E · (1 − 1/L) / (1 − m − f)
    short  P_liq = E · (1 + 1/L) / (1 + m + f)

``m`` comes from Bitget's published position tiers for the perp, chosen by the position's
notional: a larger position sits in a higher tier with a higher maintenance rate and a
lower maximum leverage. Bitget's own engine also counts funding and any fees already
paid, so the real price can sit slightly closer than this; the report says "about".

How often it would have happened
--------------------------------
Measured the same three ways the stop is: on the retrieved analogs' own highs and lows
over the ticket's horizon, against every preset stress scenario's price move, and as
the share of Monte Carlo paths whose worst point reaches it. All three use the token's
price as the path; the perp tracks the same stock through the index, and the difference
between the two is the basis the stress presets already shock separately.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Used only when Bitget's tier table cannot be fetched; said on the report when it is.
FALLBACK_MMR = 0.01
FALLBACK_MAX_LEVERAGE = 20.0
# A liquidation reached on one moment in twenty is the same bar the desk holds every
# other loss to: the calibrated 5th percentile.
LIQUIDATION_SHARE_NO_GO = 0.05


@dataclass(frozen=True)
class MarginTier:
    start: float  # position notional, USDT, lower bound (inclusive)
    end: float  # upper bound (exclusive)
    max_leverage: float
    mmr: float  # maintenance-margin rate, as a fraction


def parse_tiers(rows: list[dict[str, Any]]) -> list[MarginTier]:
    """Bitget's ``query-position-lever`` rows as tiers, ordered by size."""
    out = []
    for r in rows or []:
        try:
            out.append(MarginTier(float(r["startUnit"]), float(r["endUnit"]), float(r["leverage"]), float(r["keepMarginRate"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda t: t.start)


def tier_for(tiers: list[MarginTier], notional: float) -> MarginTier | None:
    for t in tiers:
        if t.start <= notional < t.end:
            return t
    return tiers[-1] if tiers and notional >= tiers[-1].start else None


def liquidation_price(entry: float, leverage: float, *, long: bool, mmr: float, taker_fee: float) -> float:
    m = mmr + taker_fee
    if long:
        return entry * (1.0 - 1.0 / leverage) / (1.0 - m)
    return entry * (1.0 + 1.0 / leverage) / (1.0 + m)


@dataclass
class LeverageView:
    leverage: float
    perp_symbol: str | None
    margin_quote: float
    liquidation_price: float | None
    liquidation_distance_pct: float | None  # how far the price must move against the position
    mmr: float
    max_leverage_at_size: float | None
    tiers_source: str  # "bitget" | "assumed"
    allowed: bool
    # How often it would have happened.
    analog_hits: int | None = None
    analog_of: int | None = None
    presets_hit: list[str] = field(default_factory=list)
    mc_share: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def analog_share(self) -> float | None:
        return self.analog_hits / self.analog_of if self.analog_of else None


def assess(
    *, leverage: float, notional: float, entry: float, long: bool, perp_symbol: str | None,
    tiers: list[MarginTier] | None, taker_fee: float,
) -> LeverageView:
    """The liquidation facts for one leveraged ticket, before history is consulted."""
    notes: list[str] = []
    source = "bitget" if tiers else "assumed"
    tier = tier_for(tiers, notional) if tiers else None
    mmr = tier.mmr if tier else FALLBACK_MMR
    max_lev = tier.max_leverage if tier else (None if tiers else FALLBACK_MAX_LEVERAGE)
    if not tiers:
        notes.append(f"Bitget's margin tiers could not be read, so a {FALLBACK_MMR:.0%} maintenance margin is assumed")
    margin = notional / leverage
    if perp_symbol is None:
        notes.append("Bitget lists no perpetual for this stock, so it cannot be traded with leverage there")
        return LeverageView(leverage, None, margin, None, None, mmr, None, source, False, notes=notes)
    allowed = max_lev is None or leverage <= max_lev + 1e-9
    if not allowed:
        notes.append(f"Bitget allows at most {max_lev:g}x on a position this size")
    if entry <= 0:
        return LeverageView(leverage, perp_symbol, margin, None, None, mmr, max_lev, source, allowed, notes=notes)
    liq = liquidation_price(entry, leverage, long=long, mmr=mmr, taker_fee=taker_fee)
    distance = abs(liq / entry - 1.0) * 100.0
    return LeverageView(leverage, perp_symbol, margin, liq, distance, mmr, max_lev, source, allowed, notes=notes)


def attach_history(view: LeverageView, *, analog_hits: int | None, analog_of: int | None, preset_moves: dict[str, float], mc_worst_pct: np.ndarray | None) -> LeverageView:
    """Fill in how often the liquidation level was reached.

    ``preset_moves`` maps a scenario name to its price move against the position, in
    percent of notional (negative = against). ``mc_worst_pct`` is each simulated path's
    worst point, same convention.
    """
    d = view.liquidation_distance_pct
    view.analog_hits, view.analog_of = analog_hits, analog_of
    if d is None:
        return view
    view.presets_hit = [name for name, move in preset_moves.items() if move is not None and move <= -d]
    if mc_worst_pct is not None and len(mc_worst_pct):
        view.mc_share = float((np.asarray(mc_worst_pct, dtype=float) <= -d).mean())
    return view


def gate_rule(view: LeverageView | None, p5_loss_pct: float | None) -> tuple[str, str] | None:
    """The gate's verdict on a leveraged ticket: (decision, reason), or None when unleveraged.

    NO_GO when the exchange would not accept it, when the calibrated one-in-twenty bad
    outcome already reaches the liquidation price, or when one past moment in twenty or
    more got there inside the hold. REVIEW when any of them did, or a severe preset does.
    """
    if view is None:
        return None
    if view.perp_symbol is None:
        return "NO_GO", "no Bitget perpetual for this stock, so it cannot be held with leverage"
    if not view.allowed:
        return "NO_GO", f"{view.leverage:g}x is above the {view.max_leverage_at_size:g}x Bitget allows at this size"
    d = view.liquidation_distance_pct
    if d is None:
        return "REVIEW_REQUIRED", "liquidation price unknown: no entry price"
    share = view.analog_share
    if p5_loss_pct is not None and abs(p5_loss_pct) >= d:
        return "NO_GO", f"the 1-in-20 bad outcome ({p5_loss_pct:+.1f}%) reaches the liquidation price {d:.1f}% away"
    if share is not None and share >= LIQUIDATION_SHARE_NO_GO:
        return "NO_GO", f"{view.analog_hits} of {view.analog_of} past moments like this would have been liquidated ({d:.1f}% away)"
    if (view.analog_hits or 0) > 0 or view.presets_hit:
        what = []
        if view.analog_hits:
            what.append(f"{view.analog_hits} of {view.analog_of} past moments")
        if view.presets_hit:
            what.append(f"{len(view.presets_hit)} stress preset{'s' if len(view.presets_hit) > 1 else ''}")
        return "REVIEW_REQUIRED", f"liquidation {d:.1f}% away is reached by {' and '.join(what)}"
    return "GO", f"liquidation {d:.1f}% away; no past moment like this and no preset reached it"
