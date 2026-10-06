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
