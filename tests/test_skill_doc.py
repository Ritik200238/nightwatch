"""The Agent Hub skill document must describe the MCP tools the server really exposes."""

import re
from pathlib import Path

from nightwatch.api import mcp_server

SKILL = Path(__file__).resolve().parent.parent / "skills" / "nightwatch-stress-test" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_front_matter_names_the_skill_and_says_when_to_use_it():
    head = _text().split("---")[1]
    assert re.search(r"^name: nightwatch-stress-test$", head, re.M)
    assert "description:" in head and "Bitget" in head


def test_every_tool_the_server_exposes_is_in_the_skills_tool_table():
    text = _text()
    for tool in mcp_server.TOOLS:
        assert f"`{tool['name']}(" in text, f"{tool['name']} is not described in SKILL.md"


def test_every_stress_test_argument_is_mentioned():
    """A parameter the skill never names is one the calling model will not use, however well the server handles it."""
    text = _text()
    props = next(t for t in mcp_server.TOOLS if t["name"] == "stress_test")["inputSchema"]["properties"]
    missing = [p for p in props if not re.search(rf"\b{p}\b", text)]
    assert not missing, f"SKILL.md does not mention: {missing}"


def test_the_skill_names_the_endpoint_and_the_verdict_codes_the_tool_returns():
    text = _text()
    assert "https://nightwatch-gules.vercel.app/api/mcp" in text
    assert "`REDUCE_TO`" in text and "`NO_GO`" in text
    # No tool the server does not have.
    for name in set(re.findall(r"`([a-z_]+)\(", text)):
        assert name in {t["name"] for t in mcp_server.TOOLS}, f"SKILL.md names a tool that does not exist: {name}"
