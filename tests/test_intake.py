"""The rule-based intake: what a trader types, and what it must never invent."""

from __future__ import annotations

import pytest

from nightwatch.api.intake import parse_message, read_conversation
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture

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


def test_a_size_written_without_a_k_or_a_dollar_sign_is_still_a_size():
    """"long 20000 TSLA" is as plain as "long 20k TSLA", and used to parse as no size
    at all - which meant the chat asked for a size the trader had already given."""
    out = p("long 20000 TSLA overnight")
    assert (out.kind, out.ticker, out.side, out.notional_quote) == ("analyze", "TSLA", "long", 20_000.0)
    assert p("short 5000 NVDA for 12 hours").notional_quote == 5_000.0
    assert p("buy 1500 MSFT, my account is 200000").notional_quote == 1_500.0


def test_a_bare_number_that_is_not_a_size_is_left_alone():
    assert p("long TSLA at 350").notional_quote is None  # a level
    assert p("long TSLA 50").notional_quote is None  # nobody sizes at fifty dollars
    assert p("short 3000 NVDA, stop at 180").stop_price == 180.0  # the stop keeps its number
    assert p("short 3000 NVDA, stop at 180").notional_quote == 3_000.0
    assert p("long 10k TSLA for 12 hours").horizon_hours == 12.0  # a duration is not money


def test_through_the_weekend_on_a_weekday_runs_to_the_open_after_it(monkeypatch):
    """"Hold through the weekend" said on a Thursday means Monday's open. It used to be
    read as the next open - seven hours later, on Thursday."""
    from datetime import datetime, timedelta

    from nightwatch.api import intake as it
    from nightwatch.time_utils import UTC

    thursday = datetime(2026, 9, 24, 6, 21, tzinfo=UTC)
    monkeypatch.setattr("nightwatch.time_utils.utc_now", lambda: thursday)
    for text in ("Hold $20k of TSLA through the weekend, stop at 350", "short 5k NVDA into Monday", "long 10k AAPL over the weekend"):
        i = it.parse_message(text, ["TSLA", "NVDA", "AAPL"])
        t = it.intent_to_ticket(i, 200_000.0)
        end = thursday + timedelta(hours=t.horizon_hours)
        assert t.horizon_kind.value == "hours" and end.weekday() == 0 and end.hour == 13, text
        assert t.extra.get("horizon_label", "").startswith("through the weekend")
    # "Overnight" is still the next open.
    assert it.intent_to_ticket(it.parse_message("long 20k TSLA overnight", ["TSLA"]), None).horizon_kind.value == "next_open"


def test_the_language_is_read_from_the_message():
    from nightwatch.api import intake as it

    assert it.language_of("我想周末持有特斯拉") == "zh" and it.language_of("long 20k TSLA") == "en"


def test_the_model_is_needed_only_for_what_the_rules_cannot_read():
    from nightwatch.api import intake as it

    assert not it.needs_the_model("long 20k TSLA overnight, stop 350")
    assert it.needs_the_model("long 20k TSLA, only earnings nights")
    # Chinese is read by rules too now; only a request to narrow still needs the model.
    assert not it.needs_the_model("我想做多特斯拉")
    assert it.needs_the_model("只看财报前：做多特斯拉两万")


def _report(store_path, **kw):  # noqa: ANN001, ANN003, ANN202
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import analyze
    from nightwatch.stress.scenarios import Side
    from tests.test_pipeline import AS_OF, _ctx

    base = {"ticker": "TSLA", "side": Side.LONG, "notional_quote": 10_000.0, "account_equity_quote": 200_000.0, "horizon_kind": HorizonKind.NEXT_OPEN}
    return analyze(_ctx(store_path), TradeTicket(**{**base, **kw}), as_of=AS_OF, record=False)


def test_the_briefing_mentions_the_traders_own_stop(seeded_store):  # noqa: F811
    from nightwatch.api import intake as it

    r = _report(seeded_store, stop_price=100.0, thesis="t", invalidation="i")
    text = it.brief(r)
    assert "Your stop at 100.00" in text and "past moments like this would have hit it" in text


def test_a_review_for_a_missing_plan_says_how_to_clear_it(seeded_store):  # noqa: F811
    """"Why: written plan: missing thesis" names a rule. The trader needs to be told
    what to type."""
    from nightwatch.api import intake as it

    text = it.brief(_report(seeded_store))
    assert "To clear the review, tell me why you want this trade and what would prove it wrong" in text
    assert "written plan" not in text


def test_the_chinese_briefing_carries_the_same_numbers(seeded_store):  # noqa: F811
    import re

    from nightwatch.api import intake as it

    r = _report(seeded_store, stop_price=100.0)
    en, zh = it.brief(r), it.brief(r, "zh")
    nums = lambda s: set(re.findall(r"[-+]?\d[\d,]*\.\d+%?", s))  # noqa: E731
    assert "历史" in zh and "要通过复核" in zh
    assert nums(zh) <= nums(en) | nums(it.brief(r)), "only the words change"



@pytest.mark.parametrize(("text", "expected"), [
    ("我想周末持有两万美元的特斯拉，风险大吗？", ("TSLA", "long", 20000.0, "through_weekend")),
    ("做空英伟达5000U，过夜，止损230", ("NVDA", "short", 5000.0, "next_open")),
    ("买入1.5万美元苹果，持有8小时", ("AAPL", "long", 15000.0, "hours")),
    ("做多TSLA 3万", ("TSLA", "long", 30000.0, None)),
])
def test_chinese_trade_messages_are_read_without_the_model(text, expected):
    from nightwatch.api import intake as it

    i = it.parse_message(text, ["TSLA", "NVDA", "AAPL"])
    assert (i.ticker, i.side, i.notional_quote, i.horizon_kind) == expected and i.kind == "analyze"


def test_chinese_numbers_and_the_stop_are_read():
    from nightwatch.api import intake_zh as zh

    assert zh.chinese_number("两万") == 20000 and zh.chinese_number("五千") == 5000 and zh.chinese_number("三十") == 30
    fields = zh.read("做空英伟达5000U，止损230，因为估值太高，如果涨破240就算错", {"NVDA"})
    assert fields["stop_price"] == 230.0 and fields["thesis"] == "估值太高" and fields["invalidation"] == "涨破240"


def test_a_price_on_its_own_is_not_taken_for_a_size():
    from nightwatch.api import intake_zh as zh

    assert "notional_quote" not in zh.read("做多特斯拉，止损350", {"TSLA"})


def test_a_missing_field_is_asked_for_in_chinese():
    from nightwatch.api import intake_zh as zh

    assert "做多还是做空" in zh.ask(["side"]) and "USDT" in zh.ask(["notional_quote"])


def test_switching_stock_drops_the_price_levels_given_for_the_last_one():
    """A TSLA stop at 350 carried into an NVDA ticket became a stop 56% away that every
    past moment "hit". Prices belong to the stock they were given for."""
    from nightwatch.api import intake as it

    msgs = [{"role": "user", "content": "我想周末持有两万美元的特斯拉，止损350"}, {"role": "assistant", "content": "..."}, {"role": "user", "content": "换成英伟达呢"}]
    i = it.read_conversation(msgs, ["TSLA", "NVDA"])
    assert i.ticker == "NVDA" and i.stop_price is None
    assert i.side == "long" and i.notional_quote == 20000.0, "the size and direction still carry"
    same = it.read_conversation([{"role": "user", "content": "long 20k TSLA, stop 350"}, {"role": "user", "content": "make it 30k"}], ["TSLA"])
    assert same.stop_price == 350.0, "the same stock keeps its stop"


def test_a_book_that_cannot_absorb_the_size_is_said_not_crashed_on(seeded_store):  # noqa: F811
    """"short 5,000,000 USDT of SMCI" crashed the chat with a 500: the exit cost was empty
    because the book could not take the size, and the briefing formatted None."""
    from nightwatch.api import intake as it
    from nightwatch.execution.exit_cost import ExitQuote

    r = _report(seeded_store)
    r.execution.exit_quote = ExitQuote(5_000_000.0, "sell", 100.0, None, None, 10.0, None, None, 3, False, "2026-09-12T14:00:00+00:00")
    assert "cannot absorb this size" in it.brief(r) and "无法在任何价格" in it.brief(r, "zh")
