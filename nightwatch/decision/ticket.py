"""The trade ticket: what the trader intends, stated explicitly.

Everything downstream is computed *for this ticket*. Missing fields are not
guessed; the gate turns them into REVIEW_REQUIRED so the trader fills them in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from nightwatch.analog.outcomes import structural_horizons
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import ensure_utc


class HorizonKind(str, Enum):
    NEXT_OPEN = "next_open"  # hold until the next US regular open
    WINDOW_END = "window_end"  # hold until the current closed window ends / session closes
    HOURS = "hours"  # explicit number of hours


@dataclass(frozen=True)
class TradeTicket:
    ticker: str
    side: Side
    notional_quote: float
    account_equity_quote: float | None = None
    horizon_kind: HorizonKind = HorizonKind.NEXT_OPEN
    horizon_hours: float | None = None
    entry_price: float | None = None  # None = current mid
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str = ""
    invalidation: str = ""
    hedge_ratio: float | None = None  # trader's own preference, if any
    created_at: datetime | None = None
    # What the trader already holds, so the desk can judge the book and not just the trade.
    open_positions: tuple[tuple[str, str, float], ...] = ()  # (ticker, side, notional)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.notional_quote <= 0:
            raise ValueError("notional must be positive")
        if self.account_equity_quote is not None and self.account_equity_quote <= 0:
            raise ValueError("account equity must be positive")
        if self.horizon_kind == HorizonKind.HOURS and (self.horizon_hours is None or self.horizon_hours <= 0):
            raise ValueError("horizon_hours required for an explicit-hours horizon")
        if self.hedge_ratio is not None and not 0.0 <= self.hedge_ratio <= 1.0:
            raise ValueError("hedge_ratio must be in [0, 1]")
        if self.created_at is not None:
            object.__setattr__(self, "created_at", ensure_utc(self.created_at))

    def horizon_h(self, now: datetime) -> float:
        if self.horizon_kind == HorizonKind.HOURS:
            return float(self.horizon_hours or 0.0)
        return structural_horizons(now)[self.horizon_kind.value]

    def horizon_end(self, now: datetime) -> datetime:
        return ensure_utc(now) + timedelta(hours=self.horizon_h(now))

    @property
    def closing_long(self) -> bool:
        return self.side == Side.LONG

    def stop_distance_pct(self, entry: float) -> float | None:
        if self.stop_price is None or entry <= 0:
            return None
        return abs(entry - self.stop_price) / entry * 100.0

    def stop_is_on_correct_side(self, entry: float) -> bool | None:
        if self.stop_price is None:
            return None
        return self.stop_price < entry if self.side == Side.LONG else self.stop_price > entry
