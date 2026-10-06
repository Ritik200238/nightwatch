"""The trade ticket: what the trader intends, stated explicitly.

Everything downstream is computed *for this ticket*. Missing fields are not
guessed; the gate turns them into REVIEW_REQUIRED so the trader fills them in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from nightwatch.analog.outcomes import structural_horizons
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import ensure_utc

# The longest hold the history can speak to: past it the window runs out of data, and an
# absurd one (1e9 hours) overflows the clock arithmetic.
MAX_HOLD_HOURS = 720.0
# Bounds every entry point (HTTP API, MCP) holds a request to, so they refuse the same things.
MAX_NOTIONAL = 10_000_000
MAX_PRICE = 1e9


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
    # A stop the trader gave as a distance ("3% below"), signed: negative is below entry.
    # Turned into ``stop_price`` once the entry price is known, then left alone.
    stop_offset_pct: float | None = None
    target_price: float | None = None
    thesis: str = ""
    invalidation: str = ""
    hedge_ratio: float | None = None  # trader's own preference, if any
    # Leverage, taken on the stock's perpetual. None or 1 is a plain token position.
    leverage: float | None = None
    created_at: datetime | None = None
    # What the trader already holds, so the desk can judge the book and not just the trade.
    open_positions: tuple[tuple[str, str, float], ...] = ()  # (ticker, side, notional)
    # Named conditions narrowing which past moments count as comparable - "only earnings
    # nights", "only when the basis was stretched". Names from nightwatch.analog.lens;
    # anything else is dropped rather than guessed at.
    lenses: tuple[str, ...] = ()
    # Whether the desk may narrow the search itself when the evidence says the unfiltered
    # answer is wrong for tonight (see nightwatch.analog.lens.AUTOMATIC). A trader who
    # wants the unfiltered answer anyway turns this off; one who names lenses overrides it.
    auto_lens: bool = True
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.notional_quote) or self.notional_quote <= 0:
            raise ValueError("notional must be positive")
        if self.account_equity_quote is not None and (not math.isfinite(self.account_equity_quote) or self.account_equity_quote <= 0):
            raise ValueError("account equity must be positive")
        if self.horizon_kind == HorizonKind.HOURS and (self.horizon_hours is None or self.horizon_hours <= 0):
            raise ValueError("horizon_hours required for an explicit-hours horizon")
        if self.horizon_kind == HorizonKind.HOURS and self.horizon_hours > MAX_HOLD_HOURS:
            raise ValueError(f"a hold can be at most {MAX_HOLD_HOURS:g} hours (30 days)")
        if self.stop_offset_pct is not None and not 0 < abs(self.stop_offset_pct) < 100:
            raise ValueError("a stop distance must be between 0% and 100%")
        if self.leverage is not None and not 1.0 <= self.leverage <= 125.0:
            raise ValueError("leverage must be between 1x and 125x")
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
    def leveraged(self) -> bool:
        return self.leverage is not None and self.leverage > 1.0

    @property
    def closing_long(self) -> bool:
        return self.side == Side.LONG

    def with_stop_resolved(self, entry: float) -> TradeTicket:
        """The same ticket with a distance stop turned into a price at ``entry``."""
        if self.stop_price is not None or self.stop_offset_pct is None or entry <= 0:
            return self
        from dataclasses import replace

        return replace(self, stop_price=round(entry * (1 + self.stop_offset_pct / 100.0), 6))

    def stop_distance_pct(self, entry: float) -> float | None:
        if self.stop_price is None or entry <= 0:
            return None
        return abs(entry - self.stop_price) / entry * 100.0

    def stop_is_on_correct_side(self, entry: float) -> bool | None:
        if self.stop_price is None:
            return None
        return self.stop_price < entry if self.side == Side.LONG else self.stop_price > entry


def stop_side_problem(ticket: TradeTicket, ref_price: float | None) -> str | None:
    """One sentence when the stop sits on the wrong side of the price, else None.

    A stop that is above a long (or below a short) is a typo, not a plan; every entry point
    says so at once instead of after an analysis that cannot use it."""
    if not ticket.stop_price:
        return None
    ref = ticket.entry_price or ref_price
    if ref and ticket.stop_is_on_correct_side(ref) is False:
        way, rel = ("long", "below") if ticket.closing_long else ("short", "above")
        return f"A stop for a {way} must be {rel} the current price ({ref:,.2f}). You entered {ticket.stop_price:,.2f}."
    return None
