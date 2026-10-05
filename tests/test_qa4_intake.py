"""QA round 4: holdings sentences, nonsense, and leverage limits, each with the audit's exact input."""

from __future__ import annotations

import pytest

from nightwatch.api.intake import parse_message
from tests.test_intake import TICKERS


def p(text):
    return parse_message(text, TICKERS)


@pytest.mark.parametrize(
    "text",
    [
        "I hold 30k AAPL and 10k NVDA. Long 20k TSLA overnight",
        "Long 20k TSLA overnight. I hold 30k AAPL and 10k NVDA",
        "I hold 30k AAPL and 10k NVDA, buy 20k TSLA overnight",
        "I also hold 30k AAPL and 10k NVDA. Long 20k TSLA overnight",
    ],
)
def test_the_clause_with_a_side_verb_is_the_trade_wherever_it_sits(text):
    out = p(text)
    assert (out.ticker, out.side, out.notional_quote) == ("TSLA", "long", 20_000.0)
    assert {t for t, _, _ in out.open_positions} == {"AAPL", "NVDA"}


def test_chinese_holdings_clause_is_not_the_trade():
    out = p("我持有3万U的苹果，做多2万U特斯拉过夜")
    assert (out.ticker, out.side, out.notional_quote) == ("TSLA", "long", 20_000.0)
    assert [t for t, _, _ in out.open_positions] == ["AAPL"]


def test_a_bare_hold_with_no_other_trade_clause_is_still_the_trade():
    out = p("I hold 20k TSLA overnight")
    assert (out.ticker, out.side, out.notional_quote) == ("TSLA", "long", 20_000.0)
    assert out.open_positions == []
