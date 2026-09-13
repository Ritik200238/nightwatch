"""The limit that stops a bad week becoming a bad month.

A discipline gate checks one trade. A circuit breaker checks the trader: after enough
realised loss, or enough losses in a row, the answer to the next ticket should be no
regardless of how good it looks.

**It only counts trades the trader said they took.** The journal is full of analyses,
most of which were never traded, and counting those would invent a loss record that does
not exist. A ticket becomes part of the record when it is marked taken, and its realised
result is the size the desk recommended multiplied by the move that followed, which is
exactly what the journal already scores.

States, worst first:

* ``HALTED`` — a loss limit is breached. The gate refuses every new ticket until the
  window rolls off.
* ``COOLDOWN`` — a losing streak, or most of a limit used up. The gate asks for review.
* ``NORMAL`` — trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd

from nightwatch.time_utils import ensure_utc, utc_now


class BreakerState(str, Enum):
    NORMAL = "NORMAL"
    COOLDOWN = "COOLDOWN"
    HALTED = "HALTED"


@dataclass(frozen=True)
class BreakerPolicy:
    """Limits as a share of account equity, and the streak that triggers a pause."""

    daily_loss_pct: float = 2.0
    weekly_loss_pct: float = 5.0
    monthly_loss_pct: float = 10.0
    losing_streak: int = 3
    warn_at_fraction: float = 0.75  # this much of a limit used is a cooldown, not a halt


@dataclass(frozen=True)
class WindowLoss:
    name: str
    hours: float
    realised_quote: float  # negative is a loss
    limit_quote: float | None
    used_fraction: float | None  # 0 = flat, 1 = the limit is exactly spent
    n_trades: int


@dataclass(frozen=True)
class BreakerReport:
    state: BreakerState
    reasons: list[str] = field(default_factory=list)
    windows: list[WindowLoss] = field(default_factory=list)
    losing_streak: int = 0
    n_taken: int = 0
    equity: float | None = None

    @property
    def blocks_new_trades(self) -> bool:
        return self.state is BreakerState.HALTED


def realised_pnl(row: pd.Series) -> float | None:
    """What a taken ticket actually made or lost, at the size the desk recommended.

    A ``GO`` has no reduced size, so the requested size stands. Anything the desk cut is
    counted at the cut size, because that is the advice the trader was given.
    """
    ret = row.get("ret_pct")
    if ret is None or pd.isna(ret):
        return None
    size = row.get("recommended_notional")
    if size is None or pd.isna(size):
        size = row.get("notional")
    if size is None or pd.isna(size):
        return None
    return float(size) * float(ret) / 100.0


def evaluate(taken: pd.DataFrame, *, equity: float | None, now: datetime | None = None, policy: BreakerPolicy = BreakerPolicy()) -> BreakerReport:
    """``taken`` = journal rows for tickets marked taken, matured ones carrying outcomes."""
    now = ensure_utc(now or utc_now())
    if taken.empty:
        return BreakerReport(state=BreakerState.NORMAL, reasons=["no trades marked as taken yet"], equity=equity)

    df = taken.copy()
    df["closed_at"] = pd.to_datetime(df["horizon_end"], utc=True)
    df["pnl"] = df.apply(realised_pnl, axis=1)
    df = df.dropna(subset=["pnl"]).sort_values("closed_at")
    if df.empty:
        return BreakerReport(state=BreakerState.NORMAL, reasons=["no taken trade has matured yet"], equity=equity, n_taken=len(taken))

    windows: list[WindowLoss] = []
    for name, hours, pct in (("day", 24.0, policy.daily_loss_pct), ("week", 168.0, policy.weekly_loss_pct), ("month", 720.0, policy.monthly_loss_pct)):
        recent = df[df["closed_at"] >= now - timedelta(hours=hours)]
        realised = float(recent["pnl"].sum())
        limit = equity * pct / 100.0 if equity else None
        used = (-realised / limit) if (limit and limit > 0 and realised < 0) else (0.0 if limit else None)
        windows.append(WindowLoss(name=name, hours=hours, realised_quote=realised, limit_quote=limit, used_fraction=used, n_trades=len(recent)))

    # A streak is counted on the most recent closes, oldest first.
    streak = 0
    for pnl in reversed(df["pnl"].tolist()):
        if pnl < 0:
            streak += 1
        else:
            break

    reasons: list[str] = []
    state = BreakerState.NORMAL
    for w in windows:
        if w.used_fraction is None:
            continue
        if w.used_fraction >= 1.0:
            state = BreakerState.HALTED
            reasons.append(f"{w.name} loss {w.realised_quote:,.0f} has reached the {w.limit_quote:,.0f} limit ({w.n_trades} trades)")
        elif w.used_fraction >= policy.warn_at_fraction and state is not BreakerState.HALTED:
            state = BreakerState.COOLDOWN
            reasons.append(f"{w.name} loss {w.realised_quote:,.0f} is {w.used_fraction:.0%} of the {w.limit_quote:,.0f} limit")
    if streak >= policy.losing_streak and state is BreakerState.NORMAL:
        state = BreakerState.COOLDOWN
        reasons.append(f"{streak} losing trades in a row")
    if state is BreakerState.NORMAL:
        worst = min((w for w in windows if w.limit_quote), key=lambda w: w.realised_quote, default=None)
        reasons.append(f"within every loss limit{f'; {worst.name} at {worst.realised_quote:,.0f}' if worst else ''}")
    if equity is None:
        reasons.append("account equity not given, so only the losing streak is checked")

    return BreakerReport(state=state, reasons=reasons, windows=windows, losing_streak=streak, n_taken=int(len(taken)), equity=equity)
