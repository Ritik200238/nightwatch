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
