"""The headline reason beside a NO GO must be the rule that refused the trade."""
from nightwatch.decision.gate import GateDecision, GateReport, RuleResult


def test_a_refusing_rule_is_listed_before_rules_that_only_ask_for_more():
    g = GateReport(
        decision=GateDecision.NO_GO,
        rules=[
            RuleResult("written_plan", GateDecision.REVIEW_REQUIRED, "missing thesis"),
            RuleResult("position_size", GateDecision.REVIEW_REQUIRED, "Account equity not provided"),
            RuleResult("liquidation", GateDecision.NO_GO, "reaches the liquidation price 0.6% away"),
            RuleResult("stop", GateDecision.GO, "ok"),
        ],
    )
    assert g.reasons[0].startswith("liquidation:")
    assert [r.split(":")[0] for r in g.reasons[1:]] == ["written plan", "position size"]


def test_without_a_refusal_the_rule_order_is_unchanged():
    g = GateReport(decision=GateDecision.REVIEW_REQUIRED, rules=[
        RuleResult("written_plan", GateDecision.REVIEW_REQUIRED, "a"), RuleResult("position_size", GateDecision.REVIEW_REQUIRED, "b")])
    assert [r.split(":")[0] for r in g.reasons] == ["written plan", "position size"]


def _report(verdict, rules):
    from types import SimpleNamespace

    return SimpleNamespace(
        verdict=SimpleNamespace(verdict=SimpleNamespace(value=verdict), recommended_notional=None),
        ticket=SimpleNamespace(account_equity_quote=100_000.0, notional_quote=10_000.0),
        gate=SimpleNamespace(rules=[SimpleNamespace(rule=n, decision=SimpleNamespace(value=d)) for n, d in rules]),
    )


def test_a_liquidation_refusal_says_to_lower_the_leverage_not_to_write_a_plan():
    from nightwatch.api.intake import next_step

    refused = _report("NO_GO", [("written_plan", "REVIEW_REQUIRED"), ("liquidation", "NO_GO")])
    assert "lower the leverage" in next_step(refused, zh=False)
    assert "降低杠杆" in next_step(refused, zh=True)
    # Without a liquidation refusal a missing plan is still what to fix first.
    plan_only = _report("REVIEW", [("written_plan", "REVIEW_REQUIRED")])
    assert "tell me why you want it" in next_step(plan_only, zh=False)
