"""The home page's demo trades must state an account size the intake reads.

Without one the gate cannot size the risk, so every chip came back REVIEW asking for it:
in the live journal, 442 of the last 500 verdicts were REVIEW, the chips most of them.
The strings are read from the page source itself, so editing a chip keeps this honest.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nightwatch.api.intake import read_conversation
from tests.test_intake import TICKERS

PAGE = Path(__file__).resolve().parents[1] / "web" / "src" / "components" / "desk" / "desk-page.tsx"
CJK = re.compile(r"[一-鿿]")


def _chips() -> list[dict[str, str]]:
    """Each starter chip's `send` and (when there is one) `sendZh`, as written in the page."""
    src = PAGE.read_text(encoding="utf-8")
    block = re.search(r"const HERO_CHIPS[^=]*=\s*\[(.*?)\n\];", src, re.S)
    assert block, "HERO_CHIPS not found in desk-page.tsx"
    out = []
    for line in block.group(1).splitlines():
        if "send:" not in line:
            continue
        chip = {"send": re.search(r'send: "([^"]+)"', line).group(1)}
        if m := re.search(r'sendZh: "([^"]+)"', line):
            chip["sendZh"] = m.group(1)
        out.append(chip)
    return out


def _sends() -> list[str]:
    return [c["send"] for c in _chips()]


def _page_texts() -> list[str]:
    """What each chip sends on each page: English everywhere, the Chinese text on the Chinese page."""
    return [t for c in _chips() for t in {c["send"], c.get("sendZh", c["send"])}]


def _placeholders() -> list[str]:
    src = PAGE.read_text(encoding="utf-8")
    m = re.search(r'placeholder=\{tx\("([^"]+)", "([^"]+)"\)\}', src)
    assert m, "hero placeholder not found in desk-page.tsx"
    return [m.group(1).removeprefix("e.g. "), m.group(2).removeprefix("例如：")]


def _read(text: str):
    return read_conversation([{"role": "user", "content": text}], TICKERS, None)


def _pct(line: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
    assert m, line
    return float(m.group(1))


def test_every_hero_chip_is_found():
    assert len(_chips()) == 3


@pytest.mark.parametrize("text", _page_texts() + _placeholders())
def test_example_states_an_account_the_intake_reads(text):
    got = _read(text)
    assert got.kind == "analyze", got.missing_fields
    assert got.account_equity_quote == 200_000
    # The account is read as the account, never as the size of the trade.
    assert got.notional_quote is not None and got.notional_quote < got.account_equity_quote


@pytest.mark.parametrize("text", _page_texts())
def test_chip_states_a_plan_the_intake_reads_cleanly(text):
    got = _read(text)
    assert got.thesis and got.invalidation, (got.thesis, got.invalidation)
    # The final question is not swallowed into the "wrong if" line ("... below 170 - is it safe").
    assert not re.search(r"safe|安全", got.invalidation), got.invalidation
    # A move the desk can measure, not wording it would ignore.
    assert re.search(r"\d+(?:\.\d+)?\s*%", got.invalidation), got.invalidation


def test_chinese_page_sends_chinese_for_every_chip():
    for c in _chips():
        assert CJK.search(c.get("sendZh", c["send"])), c


@pytest.mark.parametrize("chip", [c for c in _chips() if "sendZh" in c], ids=lambda c: c["send"][:24])
def test_chinese_chip_is_the_same_trade_as_the_english_one(chip):
    en, zh = _read(chip["send"]), _read(chip["sendZh"])
    for field in ("kind", "ticker", "side", "notional_quote", "account_equity_quote", "leverage", "horizon_kind", "horizon_hours"):
        assert getattr(zh, field) == getattr(en, field), (field, getattr(en, field), getattr(zh, field))
    assert en.thesis and zh.thesis
    assert _pct(zh.invalidation) == _pct(en.invalidation)
    # The same final question, in either language.
    assert chip["send"].rstrip().endswith("Is it safe?") and chip["sendZh"].rstrip().endswith("安全吗？")
