"""Scenario framework and rToken-native presets.

A *scenario* is a named shock applied to a position over a horizon. Presets are not
hand-typed numbers: each one is **calibrated from stored data** for the ticker in
question (empirical quantiles of the very quantity it shocks), and every preset
records where its number came from so the report can show it.

Shocks a scenario can carry
---------------------------
* ``price_move_pct``   – underlying/token price move over the horizon
* ``basis_shock_bps``  – additional token-vs-fair-value dislocation at exit
* ``depth_multiplier`` – order-book depth scaled (0.2 = liquidity drought)
* ``vol_multiplier``   – realised-vol multiple used to size the price move
* ``halt_hours``       – cannot exit for this many hours (exposure to the move
  distribution over that window instead of at will)
* ``funding_rate``     – per-interval funding for a perp hedge, if any

Applying a scenario to a ``Position`` yields a ``ScenarioImpact``: mark-to-market
P&L, exit cost from the (possibly thinned) book, and the total, all in quote currency
and as a share of position notional.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from nightwatch.data.book_metrics import walk_book
from nightwatch.data.models import EarningsEvent, OrderBookLevel, OrderBookSnapshot
from nightwatch.time_utils import ET, Session


class Severity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    EXTREME = "extreme"


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Position:
    ticker: str
    side: Side
    notional_quote: float  # position size in quote currency (USDT)
    entry_price: float
    hedge_ratio: float = 0.0  # share of notional hedged with the perp (0..1)

    @property
    def sign(self) -> float:
        return 1.0 if self.side == Side.LONG else -1.0

    @property
    def base_qty(self) -> float:
        return self.notional_quote / self.entry_price


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    severity: Severity
    horizon_h: float
    price_move_pct: float = 0.0
    basis_shock_bps: float = 0.0
    depth_multiplier: float = 1.0
    vol_multiplier: float = 1.0
    halt_hours: float = 0.0
    funding_rate: float = 0.0
    probability_note: str = ""
    calibration: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioImpact:
    scenario_id: str
    mtm_pnl_quote: float
    basis_pnl_quote: float
    exit_cost_quote: float | None  # None when the book cannot absorb the exit
    hedge_pnl_quote: float
    funding_cost_quote: float
    total_pnl_quote: float | None
    total_pct_of_notional: float | None
    exit_fully_filled: bool
    breaches: dict[str, bool]


@dataclass(frozen=True)
class Limits:
    max_loss_pct: float = 5.0  # of notional
    max_exit_cost_bps: float = 50.0
    require_full_exit: bool = True


# --------------------------------------------------------------------- applying


def thin_book(levels: tuple[OrderBookLevel, ...], multiplier: float) -> tuple[OrderBookLevel, ...]:
    if multiplier == 1.0:
        return levels
    return tuple(OrderBookLevel(price=lv.price, size=lv.size * max(multiplier, 0.0)) for lv in levels)


def apply_scenario(
    position: Position,
    scenario: Scenario,
    *,
    book: OrderBookSnapshot | None,
    taker_fee: float,
    limits: Limits = Limits(),
) -> ScenarioImpact:
    """Mark the position through the scenario and cost the exit on the stressed book."""
    sign = position.sign
    qty = position.base_qty
    # Underlying move.
    exit_price = position.entry_price * (1.0 + scenario.price_move_pct / 100.0)
    mtm = sign * qty * (exit_price - position.entry_price)
    # Basis dislocation hurts whichever way you must trade to exit: a long sells into
    # a discount, a short buys into a premium. Modelled as an adverse shock.
    basis_pnl = -abs(scenario.basis_shock_bps) / 1e4 * position.notional_quote * (1.0 - position.hedge_ratio)
    # Hedge: the perp offsets the underlying move on the hedged share (basis risk stays).
    hedge_pnl = -sign * position.hedge_ratio * qty * (exit_price - position.entry_price)
    # Funding on the hedge leg over the horizon (8h intervals).
    intervals = max(0.0, scenario.horizon_h / 8.0)
    funding_cost = abs(scenario.funding_rate) * intervals * position.notional_quote * position.hedge_ratio

    exit_cost: float | None
    fully = True
    unhedged_notional = position.notional_quote * (1.0 - position.hedge_ratio)
    if unhedged_notional <= 1e-9:
        exit_cost = 0.0  # nothing to unwind on the spot leg
    elif book is None or book.mid is None:
        exit_cost = None
        fully = False
    else:
        side_levels = book.bids if position.side == Side.LONG else book.asks
        stressed = thin_book(side_levels, scenario.depth_multiplier)
        res = walk_book(stressed, book.mid, unhedged_notional)
        fully = res.fully_filled
        if np.isnan(res.cost_bps):
            exit_cost = None
        else:
            exit_cost = (res.cost_bps / 1e4 + taker_fee) * unhedged_notional

    total = None if exit_cost is None else mtm + basis_pnl + hedge_pnl - exit_cost - funding_cost
    total_pct = None if total is None else total / position.notional_quote * 100.0
    breaches = {
        "max_loss": total_pct is not None and total_pct < -limits.max_loss_pct,
        "exit_cost": exit_cost is not None and exit_cost / position.notional_quote * 1e4 > limits.max_exit_cost_bps,
        "cannot_fully_exit": limits.require_full_exit and not fully,
    }
    return ScenarioImpact(
        scenario_id=scenario.id, mtm_pnl_quote=mtm, basis_pnl_quote=basis_pnl, exit_cost_quote=exit_cost,
        hedge_pnl_quote=hedge_pnl, funding_cost_quote=funding_cost, total_pnl_quote=total,
        total_pct_of_notional=total_pct, exit_fully_filled=fully, breaches=breaches,
    )


def sensitivity(
    position: Position,
    base: Scenario,
    field_name: str,
    values: Sequence[float],
    *,
    book: OrderBookSnapshot | None,
    taker_fee: float,
) -> pd.DataFrame:
    """Sweep one scenario field across ``values``; returns total P&L per value."""
    rows = []
    for v in values:
        sc = Scenario(**{**base.__dict__, field_name: v, "id": f"{base.id}:{field_name}={v}"})
        imp = apply_scenario(position, sc, book=book, taker_fee=taker_fee)
        rows.append({field_name: v, "total_pct": imp.total_pct_of_notional, "exit_cost_quote": imp.exit_cost_quote, "fully_filled": imp.exit_fully_filled})
    return pd.DataFrame(rows)


# ------------------------------------------------------------- data-driven presets


@dataclass(frozen=True)
class EmpiricalInputs:
    """Numbers measured from the ticker's history that presets are built from."""

    closed_window_ret_pct: np.ndarray  # spot return over each past closed window (close→open)
    earnings_gap_pct: np.ndarray  # native stock close-to-open return across past report dates
    abs_basis_closed_bps: np.ndarray  # |basis vs index| during closed hours
    rv_24h_now: float  # annualised
    horizon_h: float  # the ticket's horizon
    funding_rate_abs_p95: float = 0.0
    # Where the nearest report is. None means unknown, and an unknown date cannot rule
    # an earnings gap out.
    hours_to_earnings: float | None = None
    hours_since_earnings: float | None = None


def closed_window_returns(frame: pd.DataFrame) -> np.ndarray:
    """Spot return from the last regular-session bar before each closed window to the
    first regular-session bar after it (the 'what happened while the market was shut'
    distribution). Uses the session labels on the aligned frame."""
    f = frame[["spot_close", "session"]].dropna(subset=["spot_close"])
    if f.empty:
        return np.array([])
    is_reg = (f["session"] == Session.REGULAR.value).to_numpy()
    closes = f["spot_close"].to_numpy(dtype=float)
    rets = []
    last_reg_close = None
    in_closed = False
    for i in range(len(f)):
        if is_reg[i]:
            if in_closed and last_reg_close is not None:
                rets.append((closes[i] / last_reg_close - 1.0) * 100.0)
            in_closed = False
            last_reg_close = closes[i]
        else:
            in_closed = True
    return np.asarray(rets, dtype=float)


def earnings_gaps(native_daily: pd.DataFrame, events: Sequence[EarningsEvent]) -> np.ndarray:
    """The overnight reaction to each past report: the first session open *after* the
    numbers were public versus the last close *before*.

    * before-open (``bmo``): report-day open vs previous session close
    * after-close (``amc`` / unknown): next session open vs report-day close

    Daily bars are indexed by their session start (Yahoo: 13:30/14:30 UTC), so the
    report day's bar is the first bar at or after the report's ET-midnight instant.
    """
    if native_daily.empty or not events:
        return np.array([])
    closes = native_daily["close"]
    opens = native_daily["open"] if "open" in native_daily else closes
    idx = closes.index
    out = []
    seen: set[str] = set()
    for ev in sorted(events, key=lambda e: e.report_date):
        key = ev.report_date.astimezone(ET).date().isoformat()
        if key in seen:
            continue
        seen.add(key)
        rd = pd.Timestamp(ev.report_date).tz_convert("UTC")
        pos = int(idx.searchsorted(rd, side="left"))  # report day's session bar
        if pos >= len(idx):
            continue
        if ev.timing == "bmo":
            if pos == 0:
                continue
            before, after = float(closes.iloc[pos - 1]), float(opens.iloc[pos])
        else:
            if pos + 1 >= len(idx):
                continue
            before, after = float(closes.iloc[pos]), float(opens.iloc[pos + 1])
        if before > 0:
            out.append((after / before - 1.0) * 100.0)
    return np.asarray(out, dtype=float)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# Slack around the report instant: a report date is known to the day, and an
# after-the-close report is priced at the next open, up to a day later.
EARNINGS_SLACK_H = 24.0


def earnings_in_window(inp: EmpiricalInputs) -> bool:
    """Whether an earnings reaction can land inside this hold.

    A report due inside the holding period, or one already out that the market has not
    yet opened on, can gap the position. One a month away cannot, and a preset built on
    it was being quoted as the worst case - and as "the case against" - on nights with
    no report anywhere near them. An unknown date keeps the presets: absence of a date
    is not evidence of no report.
    """
    to, since = inp.hours_to_earnings, inp.hours_since_earnings
    if to is None and since is None:
        return True
    return (to is not None and to <= inp.horizon_h + EARNINGS_SLACK_H) or (since is not None and since <= EARNINGS_SLACK_H)


def build_presets(inp: EmpiricalInputs, *, min_obs: int = 20) -> list[Scenario]:
    """Presets calibrated from the ticker's own history. Each records its source."""
    presets: list[Scenario] = []
    h = inp.horizon_h
    # Expected move from realised vol over the horizon (√time, 8760 trading hours/yr).
    sigma_h = inp.rv_24h_now * np.sqrt(h / 8760.0) * 100.0 if inp.rv_24h_now and h > 0 else None

    if inp.closed_window_ret_pct.size >= min_obs:
        r = inp.closed_window_ret_pct
        for sev, p in ((Severity.MODERATE, 10), (Severity.SEVERE, 5), (Severity.EXTREME, 1)):
            move = float(np.percentile(r, p))
            presets.append(Scenario(
                id=f"closed_window_gap_p{p}", name=f"Closed-window gap, {_ordinal(p)} percentile", severity=sev, horizon_h=h,
                price_move_pct=move, probability_note=f"{p}% of {r.size} past closed windows were worse",
                calibration={"source": "spot close→open across closed windows", "n": int(r.size), "percentile": p},
            ))
    if inp.earnings_gap_pct.size >= 4 and earnings_in_window(inp):
        g = inp.earnings_gap_pct
        worst = float(np.min(g))
        presets.append(Scenario(
            id="earnings_gap_worst", name="Earnings gap: worst observed", severity=Severity.EXTREME, horizon_h=h,
            price_move_pct=worst, probability_note=f"worst of {g.size} past earnings reactions",
            calibration={"source": "native stock close→open across report dates", "n": int(g.size), "median_abs": float(np.median(np.abs(g)))},
        ))
        presets.append(Scenario(
            id="earnings_gap_typical", name="Earnings gap: typical adverse", severity=Severity.SEVERE, horizon_h=h,
            price_move_pct=-float(np.median(np.abs(g))), probability_note="median absolute past reaction, adverse direction",
            calibration={"source": "native stock close→open across report dates", "n": int(g.size)},
        ))
    if sigma_h is not None:
        for mult, sev in ((2.0, Severity.SEVERE), (3.0, Severity.EXTREME)):
            presets.append(Scenario(
                id=f"vol_spike_x{int(mult)}", name=f"Volatility spike ×{int(mult)}", severity=sev, horizon_h=h,
                price_move_pct=-mult * sigma_h, vol_multiplier=mult, probability_note=f"{int(mult)}σ adverse move at current realised vol",
                calibration={"source": "rv_24h × √horizon", "rv_24h": float(inp.rv_24h_now), "sigma_h_pct": float(sigma_h)},
            ))
    if inp.abs_basis_closed_bps.size >= min_obs:
        b = inp.abs_basis_closed_bps
        for p, sev in ((95, Severity.SEVERE), (99, Severity.EXTREME)):
            presets.append(Scenario(
                id=f"basis_blowout_p{p}", name=f"Basis blowout, {_ordinal(p)} percentile of closed hours", severity=sev, horizon_h=h,
                basis_shock_bps=float(np.percentile(b, p)), probability_note=f"{100 - p}% of {b.size} closed-market hours had a wider gap",
                calibration={"source": "|basis vs index| during closed sessions", "n": int(b.size), "percentile": p},
            ))
    presets.append(Scenario(
        id="liquidity_drought", name="Liquidity drought (book depth ÷ 5)", severity=Severity.SEVERE, horizon_h=h,
        depth_multiplier=0.2, probability_note="exit into a book one fifth as deep as now",
        calibration={"source": "live order book scaled"},
    ))
    if inp.closed_window_ret_pct.size >= min_obs and sigma_h is not None:
        presets.append(Scenario(
            id="exchange_halt_24h", name="Cannot exit for 24h during an adverse move", severity=Severity.EXTREME, horizon_h=max(h, 24.0),
            halt_hours=24.0, price_move_pct=-2.0 * float(inp.rv_24h_now) * np.sqrt(24.0 / 8760.0) * 100.0, depth_multiplier=0.5,
            probability_note="2σ 24h move with no ability to react, then exit into a half-depth book",
            calibration={"source": "rv_24h, book"},
        ))
    if inp.funding_rate_abs_p95 > 0:
        presets.append(Scenario(
            id="funding_spike", name="Funding spike on the hedge leg", severity=Severity.MILD, horizon_h=h,
            funding_rate=inp.funding_rate_abs_p95, probability_note="95th percentile |funding| every 8h for the horizon",
            calibration={"source": "perp funding history", "p95_abs": float(inp.funding_rate_abs_p95)},
        ))
    return presets


def impacts_table(impacts: Sequence[ScenarioImpact], scenarios: Sequence[Scenario]) -> pd.DataFrame:
    by_id = {s.id: s for s in scenarios}
    rows = []
    for imp in impacts:
        sc = by_id[imp.scenario_id]
        rows.append({
            "scenario": sc.name, "severity": sc.severity.value, "price_move_pct": sc.price_move_pct, "basis_shock_bps": sc.basis_shock_bps,
            "depth_x": sc.depth_multiplier, "total_pct": imp.total_pct_of_notional, "total_quote": imp.total_pnl_quote,
            "exit_cost_quote": imp.exit_cost_quote, "fully_filled": imp.exit_fully_filled,
            "breach": ",".join(k for k, v in imp.breaches.items() if v) or "",
            "note": sc.probability_note,
        })
    return pd.DataFrame(rows)
