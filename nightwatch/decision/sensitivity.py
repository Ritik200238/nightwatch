"""What would have to change for this to be a different decision?

A verdict alone tells the trader they are too big. It does not tell them how big they
could be, or what stop would fit their risk budget. This module answers both by
re-running the *same* gate, caps and verdict at other sizes and stops, so nothing here
can drift from the headline decision: one ``DecisionContext`` holds everything that does
not depend on size, and ``evaluate`` recomputes only what does (the exit walk and the
scenario impacts, both non-linear in size).

Two questions, two answers:

* **Size.** A curve of verdict against size, plus the largest size that is still a GO,
  found by bisection. Acceptability is monotone in size: every cap and every gate rule
  that reacts to size gets harder as size grows, never easier.
* **Stop.** A curve of risk against stop distance, plus the widest stop that keeps the
  requested size inside the risk budget. Here acceptability is an interval, not a
  half-line: a stop can be too tight (inside normal hourly noise) as well as too wide.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from nightwatch.data.models import OrderBookSnapshot
from nightwatch.decision.gate import GateDecision, GateInputs, GatePolicy, GateReport, evaluate_gate
from nightwatch.decision.sizing import SizingInputs, SizingPolicy, SizingResult, VerdictResult, decide, recommend_size
from nightwatch.decision.ticket import TradeTicket
from nightwatch.execution.exit_cost import quote_exit
from nightwatch.stress.scenarios import Position, Scenario, ScenarioImpact, Severity, apply_scenario

MAX_SIZE_MULTIPLE = 4.0  # how far above the request the size sweep looks
BISECTION_STEPS = 24
STRESS_CAP_STEPS = 14  # enough for ~0.01% of the search range; each step re-prices the severe presets


@dataclass(frozen=True)
class Evaluation:
    """Gate, caps and verdict for one candidate ticket."""

    gate: GateReport
    sizing: SizingResult
    verdict: VerdictResult
    impacts: list[ScenarioImpact]
    worst_severe_pct: float | None
    exit_cost_bps: float | None
    exit_fully_filled: bool


@dataclass(frozen=True)
class SizePoint:
    notional: float
    verdict: str
    gate: str
    binding_cap: str | None
    recommended_notional: float | None
    worst_severe_pct: float | None
    exit_cost_bps: float | None
    risk_pct_of_equity: float | None


@dataclass(frozen=True)
class StopPoint:
    stop_distance_pct: float
    stop_price: float
    verdict: str
    gate: str
    risk_pct_of_equity: float | None
    risk_budget_notional: float | None


@dataclass(frozen=True)
class SensitivityReport:
    sizes: list[SizePoint] = field(default_factory=list)
    stops: list[StopPoint] = field(default_factory=list)
    max_go_notional: float | None = None
    widest_stop_pct_for_requested_size: float | None = None
    requested_notional: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionContext:
    """Everything a decision needs that does not change with size or stop."""

    entry_price: float
    analog_p5_loss_pct: float | None
    quality_flags: tuple[str, ...]
    regime_label: str
    risk_multiplier: float
    recent_losing_exits: tuple[datetime, ...]
    now: datetime
    book: OrderBookSnapshot | None
    spot_taker_fee: float
    presets: tuple[Scenario, ...]
    max_exit_notional_within_budget: float | None
    hedge_cost_bps_of_position: float | None
    hedge_residual_p5_loss_pct: float | None
    gate_policy: GatePolicy = GatePolicy()
    sizing_policy: SizingPolicy = SizingPolicy()
    _stress_caps: dict[tuple, float | None] = field(default_factory=dict, compare=False, repr=False)

    def worst_severe_loss_quote(self, ticket: TradeTicket, notional: float) -> float | None:
        """Worst severe-preset loss in quote terms at ``notional`` (negative = a loss)."""
        position = Position(ticket.ticker, ticket.side, notional, self.entry_price, hedge_ratio=ticket.hedge_ratio or 0.0)
        losses = [
            imp.total_pnl_quote for s in self.presets if s.severity == Severity.SEVERE
            if (imp := apply_scenario(position, s, book=self.book, taker_fee=self.spot_taker_fee)).total_pnl_quote is not None
        ]
        return min(losses) if losses else None

    def stress_cap_notional(self, ticket: TradeTicket) -> float | None:
        """Largest size whose worst severe-preset loss stays inside the allowed share of
        equity. Solved rather than scaled: the loss grows faster than the size because
        the exit walks deeper into the book, so a linear extrapolation would sell the
        trader a size that breaches the limit it claims to enforce.

        The answer depends on equity, side and hedge ratio, never on the size being
        asked about, so a sweep over sizes solves it once."""
        equity = ticket.account_equity_quote
        if equity is None:
            return None
        key = (equity, ticket.side, ticket.hedge_ratio)
        if key in self._stress_caps:
            return self._stress_caps[key]
        budget = equity * self.sizing_policy.max_stress_loss_pct_of_equity / 100.0
        hi = equity  # a spot position larger than the whole account is not on the table

        def loss_at(n: float) -> float:
            worst = self.worst_severe_loss_quote(ticket, n)
            return abs(min(worst, 0.0)) if worst is not None else 0.0

        if loss_at(hi) <= budget:
            self._stress_caps[key] = hi  # the limit does not bind at any plausible size
            return hi
        lo = 0.0
        for _ in range(STRESS_CAP_STEPS):
            mid = (lo + hi) / 2
            if loss_at(mid) <= budget:
                lo = mid
            else:
                hi = mid
        self._stress_caps[key] = lo
        return lo

    def evaluate(self, ticket: TradeTicket, *, impacts: list[ScenarioImpact] | None = None, exit_cost_bps: float | None = None, exit_fully_filled: bool | None = None) -> Evaluation:
        """Gate, size and decide one ticket. Precomputed pieces are reused when given."""
        if impacts is None:
            position = Position(ticket.ticker, ticket.side, ticket.notional_quote, self.entry_price, hedge_ratio=ticket.hedge_ratio or 0.0)
            impacts = [apply_scenario(position, p, book=self.book, taker_fee=self.spot_taker_fee) for p in self.presets]
        if exit_cost_bps is None and self.book is not None:
            q = quote_exit(self.book, ticket.notional_quote, closing_long=ticket.closing_long, taker_fee=self.spot_taker_fee)
            exit_cost_bps, exit_fully_filled = q.total_cost_bps, q.fully_filled
        severe = [i.total_pct_of_notional for i, s in zip(impacts, self.presets, strict=True) if s.severity == Severity.SEVERE and i.total_pct_of_notional is not None]
        worst_severe = min(severe) if severe else None
        gate = evaluate_gate(
            ticket,
            GateInputs(
                entry_price=self.entry_price, equity=ticket.account_equity_quote, analog_p5_loss_pct=self.analog_p5_loss_pct,
                quality_flags=self.quality_flags, regime_label=self.regime_label, risk_multiplier=self.risk_multiplier,
                exit_cost_bps=exit_cost_bps, exit_fully_filled=bool(exit_fully_filled), recent_losing_exits=self.recent_losing_exits, now=self.now,
            ),
            self.gate_policy,
        )
        sizing = recommend_size(
            ticket,
            SizingInputs(
                entry_price=self.entry_price, equity=ticket.account_equity_quote, stop_distance_pct=ticket.stop_distance_pct(self.entry_price),
                analog_p5_loss_pct=self.analog_p5_loss_pct, risk_multiplier=self.risk_multiplier,
                max_exit_notional_within_budget=self.max_exit_notional_within_budget, worst_severe_stress_pct=worst_severe,
                stress_cap_notional=self.stress_cap_notional(ticket),
                hedge_cost_bps_of_position=self.hedge_cost_bps_of_position, hedge_residual_p5_loss_pct=self.hedge_residual_p5_loss_pct,
            ),
            self.sizing_policy,
        )
        return Evaluation(gate=gate, sizing=sizing, verdict=decide(ticket, gate, sizing), impacts=impacts, worst_severe_pct=worst_severe, exit_cost_bps=exit_cost_bps, exit_fully_filled=bool(exit_fully_filled))


def _point(dc: DecisionContext, ticket: TradeTicket, ev: Evaluation) -> SizePoint:
    return SizePoint(
        notional=ticket.notional_quote, verdict=ev.verdict.verdict.value, gate=ev.gate.decision.value, binding_cap=ev.sizing.binding_cap,
        recommended_notional=ev.sizing.recommended_notional, worst_severe_pct=ev.worst_severe_pct, exit_cost_bps=ev.exit_cost_bps,
        risk_pct_of_equity=ev.gate.risk_pct_of_equity,
    )


def _is_go(ev: Evaluation) -> bool:
    return ev.verdict.verdict.value == "GO"


def sweep_size(dc: DecisionContext, ticket: TradeTicket, *, n: int = 12) -> list[SizePoint]:
    """Verdict as a function of size, from a tenth of the request to four times it."""
    lo = max(1.0, ticket.notional_quote / 10.0)
    hi = ticket.notional_quote * MAX_SIZE_MULTIPLE
    step = (hi - lo) / (n - 1)
    candidates = sorted({round(lo + step * i, 2) for i in range(n)} | {ticket.notional_quote})
    return [_point(dc, t, dc.evaluate(t)) for t in (replace(ticket, notional_quote=c) for c in candidates)]


def largest_go_notional(dc: DecisionContext, ticket: TradeTicket) -> float | None:
    """The largest size that still passes as GO, or None if no size does.

    Valid because acceptability only tightens with size: every cap that moves with size
    moves against it, and no gate rule becomes easier when the position grows."""
    lo = max(1.0, ticket.notional_quote / 100.0)
    hi = ticket.notional_quote * MAX_SIZE_MULTIPLE
    if _is_go(dc.evaluate(replace(ticket, notional_quote=hi))):
        return hi
    if not _is_go(dc.evaluate(replace(ticket, notional_quote=lo))):
        return None
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2
        if _is_go(dc.evaluate(replace(ticket, notional_quote=mid))):
            lo = mid
        else:
            hi = mid
    return lo


def _stop_price(ticket: TradeTicket, entry: float, distance_pct: float) -> float:
    return entry * (1.0 - distance_pct / 100.0) if ticket.closing_long else entry * (1.0 + distance_pct / 100.0)


def sweep_stop(dc: DecisionContext, ticket: TradeTicket, *, n: int = 10) -> list[StopPoint]:
    """Risk and verdict as a function of how far the stop sits from entry."""
    if dc.entry_price <= 0:
        return []
    lo, hi = dc.gate_policy.min_stop_distance_pct, min(dc.gate_policy.max_stop_distance_pct, 15.0)
    step = (hi - lo) / (n - 1)
    distances = sorted({round(lo + step * i, 2) for i in range(n)} | ({round(d, 2)} if (d := ticket.stop_distance_pct(dc.entry_price)) else set()))
    out: list[StopPoint] = []
    for dist in distances:
        price = _stop_price(ticket, dc.entry_price, dist)
        ev = dc.evaluate(replace(ticket, stop_price=price))
        cap = next((c.notional for c in ev.sizing.caps if c.name == "risk_budget"), None)
        out.append(StopPoint(stop_distance_pct=dist, stop_price=price, verdict=ev.verdict.verdict.value, gate=ev.gate.decision.value, risk_pct_of_equity=ev.gate.risk_pct_of_equity, risk_budget_notional=cap))
    return out


def widest_stop_within_risk_budget(dc: DecisionContext, ticket: TradeTicket) -> float | None:
    """The widest stop distance (%) at which the requested size keeps the risk-budget
    rule passing. None when equity is unknown or even the tightest allowed stop fails."""
    if ticket.account_equity_quote is None or dc.entry_price <= 0:
        return None

    def passes(dist: float) -> bool:
        ev = dc.evaluate(replace(ticket, stop_price=_stop_price(ticket, dc.entry_price, dist)))
        return next((r.decision == GateDecision.GO for r in ev.gate.rules if r.rule == "risk_budget"), False)

    lo, hi = dc.gate_policy.min_stop_distance_pct, dc.gate_policy.max_stop_distance_pct
    if not passes(lo):
        return None
    if passes(hi):
        return hi
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2
        if passes(mid):
            lo = mid
        else:
            hi = mid
    return lo


def build_sensitivity(dc: DecisionContext, ticket: TradeTicket, *, headline: Evaluation | None = None) -> SensitivityReport:
    notes: list[str] = []
    sizes = sweep_size(dc, ticket)
    max_go = largest_go_notional(dc, ticket)
    stops = sweep_stop(dc, ticket) if ticket.account_equity_quote is not None else []
    widest = widest_stop_within_risk_budget(dc, ticket)
    ev = headline or dc.evaluate(ticket)
    if max_go is None:
        blocking = [r.rule for r in ev.gate.rules if r.decision != GateDecision.GO and r.rule not in ("position_size", "risk_budget", "exit_liquidity")]
        notes.append(
            f"no size is a GO while {', '.join(blocking)} is unresolved" if blocking
            else f"no size is a GO: the {ev.sizing.binding_cap or 'binding'} cap stays below the request at every size"
        )
    elif max_go >= ticket.notional_quote:
        notes.append(f"the requested {ticket.notional_quote:,.0f} is a GO; room up to {max_go:,.0f}")
    else:
        notes.append(f"a GO up to {max_go:,.0f}, {1 - max_go / ticket.notional_quote:.0%} below the request")
    if widest is not None and (d := ticket.stop_distance_pct(dc.entry_price)) is not None and d > widest:
        notes.append(f"the stop would have to come in from {d:.2f}% to {widest:.2f}% for this size to fit the risk budget")
    return SensitivityReport(sizes=sizes, stops=stops, max_go_notional=max_go, widest_stop_pct_for_requested_size=widest, requested_notional=ticket.notional_quote, notes=notes)
