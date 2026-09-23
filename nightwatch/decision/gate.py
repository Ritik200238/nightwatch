"""Pre-trade discipline gate.

Runs *before* any market analysis is trusted. Each check is a small, named rule with
a plain-English reason; the decision is the worst outcome across rules:

* ``GO``               – every rule passed
* ``REVIEW_REQUIRED``  – something is missing or unknown; do not trade until fixed
* ``NO_GO``            – a rule was violated

Rules (all inputs explicit; nothing is assumed):
1. Written thesis and invalidation present.
2. Stop defined, on the correct side of entry, not absurdly tight/wide.
3. Position ≤ max share of account equity (when equity is known).
4. Risk at stop (or, without a stop, the analog 5th-percentile loss) ≤ risk budget.
5. No losing exit inside the revenge-trade cooldown window (from the journal).
6. Data quality: no snapshot flags that make the analysis untrustworthy.
7. Market posture: hostile regime → selective only (size must already be reduced).
8. Exit liquidity: the book can absorb the position within the cost budget.
9. Circuit breaker: realised losses on taken trades, and losing streaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from nightwatch.decision.ticket import TradeTicket

# Only what makes the analysis untrustworthy blocks. Thin weekend trading is the
# product's whole subject, so it is a caution that shows up in the verdict, not a veto.
BLOCKING_QUALITY_FLAGS = frozenset({"index_price_missing"})
CAUTION_QUALITY_FLAGS = {
    "spot_no_trade_share_24h_gt_25pct": "thin trading: over a quarter of the last day had no trades, so volatility and the analogs lean on filled bars",
    "spot_quieter_than_its_own_norm": "quieter than this token usually is at this time of week, which is a liquidity change rather than a weekend",
    "native_close_older_than_72h": "the native stock has not printed for three days; fair value is older than usual",
}
# Flags matched by prefix rather than exact name, because they carry a measurement.
BLOCKING_QUALITY_PREFIXES = ("spot_has_not_traded_for_",)


class GateDecision(str, Enum):
    GO = "GO"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_GO = "NO_GO"


@dataclass(frozen=True)
class GatePolicy:
    max_position_pct_of_equity: float = 25.0
    max_risk_pct_of_equity: float = 1.0
    min_stop_distance_pct: float = 0.3
    max_stop_distance_pct: float = 25.0
    revenge_cooldown_h: float = 24.0
    max_exit_cost_bps: float = 50.0
    hostile_regime_max_multiplier: float = 0.5  # if regime says hostile, size must be ≤ this × plan


@dataclass(frozen=True)
class RuleResult:
    rule: str
    decision: GateDecision
    reason: str


@dataclass(frozen=True)
class GateInputs:
    entry_price: float
    equity: float | None
    analog_p5_loss_pct: float | None  # negative number, e.g. -3.1
    quality_flags: tuple[str, ...]
    regime_label: str
    risk_multiplier: float
    exit_cost_bps: float | None
    exit_fully_filled: bool
    has_book: bool = True  # whether a book existed at all, as opposed to one too thin to fill
    breaker_state: str = "NORMAL"  # NORMAL | COOLDOWN | HALTED
    breaker_reason: str = ""
    recent_losing_exits: tuple[datetime, ...] = ()
    now: datetime | None = None


@dataclass(frozen=True)
class GateReport:
    decision: GateDecision
    rules: list[RuleResult] = field(default_factory=list)
    risk_quote: float | None = None
    risk_pct_of_equity: float | None = None
    risk_basis: str = ""
    advisories: list[str] = field(default_factory=list)  # passed, but the trader should know

    @property
    def reasons(self) -> list[str]:
        """Why the gate did not simply say go, in words a person reads.

        Rule names are identifiers - ``written_plan``, ``market_posture`` - and they were
        being printed verbatim into the chat reply, where "written_plan: missing
        invalidation" reads as a leaked variable rather than an answer.
        """
        return [f"{r.rule.replace('_', ' ')}: {r.reason}" for r in self.rules if r.decision != GateDecision.GO]


def _worst(rules: list[RuleResult]) -> GateDecision:
    if any(r.decision == GateDecision.NO_GO for r in rules):
        return GateDecision.NO_GO
    if any(r.decision == GateDecision.REVIEW_REQUIRED for r in rules):
        return GateDecision.REVIEW_REQUIRED
    return GateDecision.GO


def evaluate_gate(ticket: TradeTicket, inputs: GateInputs, policy: GatePolicy = GatePolicy()) -> GateReport:
    rules: list[RuleResult] = []
    advisories: list[str] = []
    entry = inputs.entry_price

    # 1. Written plan.
    if ticket.thesis.strip() and ticket.invalidation.strip():
        rules.append(RuleResult("written_plan", GateDecision.GO, "thesis and invalidation stated"))
    else:
        missing = [k for k, v in (("thesis", ticket.thesis), ("invalidation", ticket.invalidation)) if not v.strip()]
        rules.append(RuleResult("written_plan", GateDecision.REVIEW_REQUIRED, f"missing {', '.join(missing)}"))

    # 2. Stop.
    dist = ticket.stop_distance_pct(entry)
    if dist is None:
        # A stop is the better discipline, but its absence is not a reason to give no
        # answer: the calibrated 5th percentile is a measured loss level and sizes the trade.
        if inputs.analog_p5_loss_pct is not None:
            rules.append(RuleResult("stop", GateDecision.GO, f"no stop given; sized on the 5th percentile ({inputs.analog_p5_loss_pct:+.1f}%) instead"))
            advisories.append(f"no stop given: risk is sized on the calibrated 5th percentile, {inputs.analog_p5_loss_pct:+.1f}% over the horizon")
        else:
            rules.append(RuleResult("stop", GateDecision.REVIEW_REQUIRED, "no stop price and no analog distribution to size on"))
    elif ticket.stop_is_on_correct_side(entry) is False:
        rules.append(RuleResult("stop", GateDecision.NO_GO, "stop is on the wrong side of entry"))
    elif dist < policy.min_stop_distance_pct:
        rules.append(RuleResult("stop", GateDecision.NO_GO, f"stop {dist:.2f}% away is tighter than {policy.min_stop_distance_pct}% — inside normal hourly noise for this token"))
    elif dist > policy.max_stop_distance_pct:
        rules.append(RuleResult("stop", GateDecision.REVIEW_REQUIRED, f"stop {dist:.1f}% away is wider than {policy.max_stop_distance_pct}%"))
    else:
        rules.append(RuleResult("stop", GateDecision.GO, f"stop {dist:.2f}% from entry"))

    # 3. Position size vs equity.
    if inputs.equity is None:
        rules.append(RuleResult("position_size", GateDecision.REVIEW_REQUIRED, "account equity not provided"))
    else:
        share = ticket.notional_quote / inputs.equity * 100.0
        if share > policy.max_position_pct_of_equity:
            rules.append(RuleResult("position_size", GateDecision.NO_GO, f"position is {share:.1f}% of equity (limit {policy.max_position_pct_of_equity}%)"))
        else:
            rules.append(RuleResult("position_size", GateDecision.GO, f"position is {share:.1f}% of equity"))

    # 4. Risk budget.
    risk_quote = None
    risk_pct = None
    basis = ""
    if dist is not None:
        risk_quote = ticket.notional_quote * dist / 100.0
        basis = "distance to stop"
    elif inputs.analog_p5_loss_pct is not None:
        risk_quote = ticket.notional_quote * abs(min(inputs.analog_p5_loss_pct, 0.0)) / 100.0
        basis = "analog 5th-percentile loss"
    if risk_quote is None:
        rules.append(RuleResult("risk_budget", GateDecision.REVIEW_REQUIRED, "cannot compute risk: no stop and no analog distribution"))
    elif inputs.equity is None:
        rules.append(RuleResult("risk_budget", GateDecision.REVIEW_REQUIRED, f"risk {risk_quote:,.0f} ({basis}) but equity unknown"))
    else:
        risk_pct = risk_quote / inputs.equity * 100.0
        if risk_pct > policy.max_risk_pct_of_equity:
            rules.append(RuleResult("risk_budget", GateDecision.NO_GO, f"risk {risk_pct:.2f}% of equity ({basis}) exceeds {policy.max_risk_pct_of_equity}%"))
        else:
            rules.append(RuleResult("risk_budget", GateDecision.GO, f"risk {risk_pct:.2f}% of equity ({basis})"))

    # 5. Revenge cooldown.
    now = inputs.now
    recent = [t for t in inputs.recent_losing_exits if now is not None and now - t <= timedelta(hours=policy.revenge_cooldown_h)]
    if recent:
        rules.append(RuleResult("revenge_cooldown", GateDecision.NO_GO, f"losing exit {max(recent).isoformat()} inside the {policy.revenge_cooldown_h:.0f}h cooldown"))
    else:
        rules.append(RuleResult("revenge_cooldown", GateDecision.GO, "no recent losing exit"))

    # 6. Data quality.
    blocking = sorted(f for f in inputs.quality_flags if f in BLOCKING_QUALITY_FLAGS or f.startswith(BLOCKING_QUALITY_PREFIXES))
    if blocking:
        rules.append(RuleResult("data_quality", GateDecision.REVIEW_REQUIRED, "analysis inputs degraded: " + ", ".join(blocking)))
    else:
        rules.append(RuleResult("data_quality", GateDecision.GO, "inputs complete" if not inputs.quality_flags else "minor flags: " + ", ".join(inputs.quality_flags)))
    advisories.extend(CAUTION_QUALITY_FLAGS[f] for f in inputs.quality_flags if f in CAUTION_QUALITY_FLAGS)

    # 7. Posture.
    if inputs.regime_label == "hostile":
        rules.append(RuleResult("market_posture", GateDecision.REVIEW_REQUIRED, f"hostile regime (size multiplier {inputs.risk_multiplier:.2f}); selective entries only"))
    elif inputs.regime_label == "unknown":
        rules.append(RuleResult("market_posture", GateDecision.REVIEW_REQUIRED, "regime unknown: not enough history"))
    else:
        rules.append(RuleResult("market_posture", GateDecision.GO, f"regime {inputs.regime_label}"))

    # 8. Exit liquidity. A book that cannot absorb the size and no book at all are
    # different answers: the first is a decision, the second is an admission. Both leave
    # the cost as None, so the order of these two branches decides which one gets said.
    if not inputs.exit_fully_filled and inputs.has_book:
        rules.append(RuleResult("exit_liquidity", GateDecision.NO_GO, "the live book cannot absorb this size at any price"))
    elif inputs.exit_cost_bps is None:
        rules.append(RuleResult("exit_liquidity", GateDecision.REVIEW_REQUIRED, "no order book available to cost the exit"))
    elif inputs.exit_cost_bps > policy.max_exit_cost_bps:
        rules.append(RuleResult("exit_liquidity", GateDecision.NO_GO, f"exit would cost {inputs.exit_cost_bps:.0f} bps (limit {policy.max_exit_cost_bps:.0f})"))
    else:
        rules.append(RuleResult("exit_liquidity", GateDecision.GO, f"exit costs {inputs.exit_cost_bps:.0f} bps on the live book"))

    # 9. Circuit breaker: the trader's own recent record, not this trade's merits.
    if inputs.breaker_state == "HALTED":
        rules.append(RuleResult("circuit_breaker", GateDecision.NO_GO, inputs.breaker_reason or "loss limit reached; no new trades"))
    elif inputs.breaker_state == "COOLDOWN":
        rules.append(RuleResult("circuit_breaker", GateDecision.REVIEW_REQUIRED, inputs.breaker_reason or "cooling off after recent losses"))
    else:
        rules.append(RuleResult("circuit_breaker", GateDecision.GO, inputs.breaker_reason or "no loss limit is close"))

    return GateReport(decision=_worst(rules), rules=rules, risk_quote=risk_quote, risk_pct_of_equity=risk_pct, risk_basis=basis, advisories=advisories)
