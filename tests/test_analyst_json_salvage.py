"""A model reply that is almost JSON must never reach the page as braces and backslash-n."""
from nightwatch.api import analyst


def test_a_raw_line_break_inside_a_string_still_parses():
    obj = analyst.parse_reply('{"take": "The call\nA GO at 20,000.", "for": "x", "against": "y"}')
    assert obj and obj["take"].startswith("The call") and obj["for"] == "x"


def test_a_stray_quote_is_salvaged_field_by_field():
    raw = '{"take": "The call\\nShort \\"AMD\\" is thin.\\n\\nWhat matters most tonight\\nA spike.", "for": "a", "against": "b"}'
    obj = analyst.parse_reply(raw.replace('\\"AMD\\"', '"AMD"'))  # unescaped quote: invalid JSON
    assert obj is not None
    assert obj["take"].startswith("The call\nShort") and "\\n" not in obj["take"]
    assert obj["against"] == "b"


def test_not_json_at_all_is_not_an_object():
    assert analyst.parse_reply("The desk says GO.") is None


def test_a_refusal_at_full_size_is_not_called_an_allowance():
    r = {"verdict": {"verdict": "NO_GO", "recommended_notional": 10000.0}, "ticket": {"notional_quote": 10000.0}}
    assert analyst.refused_as_asked(r)
    assert analyst._fixed_reconcile(r, "en") == "The desk's verdict stands: NO GO at the size asked."
    smaller = {"verdict": {"verdict": "NO_GO", "recommended_notional": 3000.0}, "ticket": {"notional_quote": 10000.0}}
    assert not analyst.refused_as_asked(smaller)
    assert "3,000" in analyst._fixed_reconcile(smaller, "en")


def test_a_chinese_take_names_the_verdict_and_the_rule_in_chinese():
    r = {"verdict": {"verdict": "REVIEW", "recommended_notional": 20000.0}, "ticket": {"notional_quote": 20000.0},
         "gate": {"rules": [{"rule": "written_plan", "decision": "REVIEW_REQUIRED"}]},
         "ticket_account": None}
    out = analyst._fixed_reconcile(r, "zh")
    assert "REVIEW" not in out and "需要复核" in out
    mind = analyst.mind_line({**r, "ticket": {"notional_quote": 20000.0, "account_equity_quote": 50000.0}}, "zh")
    assert "written" not in mind and "REVIEW" not in mind
