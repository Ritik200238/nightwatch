"""The rule-based intake: what a trader types, and what it must never invent."""

from __future__ import annotations

import pytest

from nightwatch.api.intake import parse_message, read_conversation

TICKERS = "AAPL AMD AMZN AVGO BABA COIN CRCL GOOGL HOOD INTC META MSFT MSTR MU NFLX NVDA PLTR QQQ SMCI SPY SQQQ TQQQ TSLA TSM".split()


def p(text: str, equity: float | None = None):
    return parse_message(text, TICKERS, equity)


@pytest.mark.parametrize(
    ("text", "ticker", "side", "notional"),
    [
        ("long 25k TSLA overnight", "TSLA", "long", 25_000),
        ("short $50,000 of nvidia until the close", "NVDA", "short", 50_000),
        ("buy 1.5m msft", "MSFT", "long", 1_500_000),
        ("sell 20000 usdt of $PLTR", "PLTR", "short", 20_000),
        ("go long 30k on coinbase", "COIN", "long", 30_000),
        ("bearish 15k smci", "SMCI", "short", 15_000),
    ],
)
def test_the_usual_shapes_a_trader_types(text, ticker, side, notional):
    out = p(text)
    assert (out.ticker, out.side, out.notional_quote) == (ticker, side, float(notional))
    assert out.kind == "analyze"


def test_holding_a_position_is_being_long():
    """These are the two starter prompts on the desk; both must land without a question."""
    a = p("Hold $20k of TSLA through the weekend, stop at 350")
    assert (a.kind, a.ticker, a.side, a.notional_quote, a.stop_price) == ("analyze", "TSLA", "long", 20_000.0, 350.0)
    b = p("Short 5k NVDA for the next 12 hours")
    assert (b.kind, b.ticker, b.side, b.notional_quote, b.horizon_hours) == ("analyze", "NVDA", "short", 5_000.0, 12.0)
    # A holding *period* after a stated direction does not flip it.
    assert p("short 15k SPY, holding period 2 days").side == "short"


def test_short_term_is_a_horizon_not_a_direction():
    out = p("buy 10k AAPL, short term view")
    assert out.side == "long"


def test_horizons_are_read_the_way_they_are_said():
    assert p("long 10k TSLA overnight").horizon_kind == "next_open"
    assert p("long 10k TSLA until the close").horizon_kind == "window_end"
    assert p("long 10k TSLA for 8 hours").horizon_hours == 8.0
    assert p("long 10k TSLA for 3 days").horizon_hours == 72.0
    assert p("long 10k TSLA for a week").horizon_hours == 168.0
    # Silence about the horizon stays silence, so that a later message in a conversation
    # cannot overwrite an earlier "for 8 hours" with the default.
    assert p("long 10k TSLA").horizon_kind is None


def test_labelled_numbers_do_not_get_mistaken_for_size():
    out = p("long 25k TSLA, stop at 340, target 400, my account is 500k")
    assert out.notional_quote == 25_000
    assert out.stop_price == 340.0 and out.target_price == 400.0
    assert out.account_equity_quote == 500_000


def test_a_hedge_is_read_only_when_it_is_asked_for():
    assert p("long 10k TSLA").hedge_ratio is None
    assert p("long 10k TSLA, hedge it").hedge_ratio == 1.0
    assert p("long 10k TSLA, hedge half").hedge_ratio == 0.5
    assert p("long 10k TSLA, hedge 40%").hedge_ratio == 0.4


def test_nothing_is_invented():
    """The gate exists to make a trader write a plan. The parser must not write it."""
    out = p("long 25k TSLA overnight")
    assert out.thesis is None and out.invalidation is None and out.stop_price is None
    out = p("long 25k TSLA because the chip cycle is turning; wrong if it closes below 300")
    assert out.thesis == "the chip cycle is turning"
    assert out.invalidation == "it closes below 300"


def test_missing_fields_are_named_rather_than_guessed():
    out = p("what about tesla?")
    assert out.kind == "clarify" and out.ticker == "TSLA"
    assert out.missing_fields == ["side", "notional_quote"]
    assert "long or short" in out.reply and "size" in out.reply


def test_a_conversation_builds_the_ticket_a_piece_at_a_time():
    msgs = [
        {"role": "user", "content": "stress test tesla for me"},
        {"role": "assistant", "content": "I need long or short, what size in USDT."},
        {"role": "user", "content": "long"},
        {"role": "user", "content": "25k, overnight, stop 330"},
    ]
    out = read_conversation(msgs, TICKERS, 200_000)
    assert out.kind == "analyze"
    assert (out.ticker, out.side, out.notional_quote, out.stop_price) == ("TSLA", "long", 25_000.0, 330.0)
    assert out.account_equity_quote == 200_000


def test_a_later_message_does_not_wipe_the_horizon_it_says_nothing_about():
    msgs = [
        {"role": "user", "content": "long 25k TSLA for 8 hours"},
        {"role": "user", "content": "actually make it 30k"},
    ]
    out = read_conversation(msgs, TICKERS)
    assert out.notional_quote == 30_000.0
    assert (out.horizon_kind, out.horizon_hours) == ("hours", 8.0)

    # But a message that does speak about it wins.
    said = read_conversation([*msgs, {"role": "user", "content": "hold it overnight instead"}], TICKERS)
    assert said.horizon_kind == "next_open"


def test_a_ticket_with_no_stated_horizon_holds_to_the_next_open():
    from nightwatch.api.intake import intent_to_ticket

    ticket = intent_to_ticket(p("long 10k TSLA"), 200_000)
    assert ticket.horizon_kind.value == "next_open"


def test_the_latest_message_overrides_an_earlier_one():
    msgs = [
        {"role": "user", "content": "long 25k TSLA"},
        {"role": "user", "content": "actually make it short 40k"},
    ]
    out = read_conversation(msgs, TICKERS)
    assert out.side == "short" and out.notional_quote == 40_000.0 and out.ticker == "TSLA"


def test_a_ticker_we_have_no_data_for_is_simply_not_found():
    assert p("long 10k GME").ticker is None


def test_a_number_that_rounds_to_zero_is_not_written_as_a_loss():
    from nightwatch.api.intake import _pct

    assert _pct(-0.04) == "0.0%"  # not "-0.0%"
    assert _pct(0.04) == "0.0%"
    assert _pct(-1.26) == "-1.3%"
    assert _pct(2.5) == "+2.5%"
