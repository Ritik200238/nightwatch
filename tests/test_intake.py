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


def test_account_size_is_read_in_chinese_and_never_mistaken_for_a_size():
    """Live-test failure: "账户10万U" was ignored and the invalidation's "340" was read
    as the position size instead. The account, thesis and invalidation spans must all be
    spent before a bare number is taken for a size."""
    from nightwatch.api import intake_zh as zh

    fields = zh.read(
        "周末5倍杠杆做多特斯拉 1万U，账户10万U，止损4%，理由：Robotaxi 预期，如果收盘跌破 340 就算错",
        {"TSLA"},
    )
    assert fields["ticker"] == "TSLA" and fields["side"] == "long"
    assert fields["leverage"] == 5.0 and fields["stop_pct"] == 4.0
    assert fields["notional_quote"] == 10000.0, "the 1万U size, not the 340 in the invalidation"
    assert fields["account_equity_quote"] == 100000.0
    assert fields["thesis"] == "Robotaxi 预期" and "340" in fields["invalidation"]
    assert fields["horizon_kind"] == "through_weekend"

    # A later message giving only the account size: it sets the account, not a position.
    followup = zh.read("账户 20万U", {"TSLA"})
    assert followup["account_equity_quote"] == 200000.0 and "notional_quote" not in followup

    # A thesis and invalidation with no size in the message at all: still no size read.
    thesis_only = zh.read("因为 AI 资本开支继续增长，如果收盘跌破 200 就算错", {"TSLA"})
    assert thesis_only["thesis"] == "AI 资本开支继续增长" and thesis_only["invalidation"] == "收盘跌破 200"
    assert "notional_quote" not in thesis_only


def test_new_chinese_thesis_markers_are_read():
    from nightwatch.api import intake_zh as zh

    for marker in ("理由：", "理由:", "论点：", "逻辑："):
        fields = zh.read(f"做多特斯拉，{marker}Robotaxi 预期", {"TSLA"})
        assert fields["thesis"] == "Robotaxi 预期", marker


def test_account_follow_up_is_read_through_the_full_parser():
    """"账户 20万U" sets the account size and is never read as the position itself."""
    i = p("账户 20万U")
    assert i.account_equity_quote == 200000.0 and i.notional_quote is None


def test_full_chinese_trade_message_is_read_through_the_full_parser():
    i = p("周末5倍杠杆做多特斯拉 1万U，账户10万U，止损4%，理由：Robotaxi 预期，如果收盘跌破 340 就算错")
    assert i.ticker == "TSLA" and i.side == "long" and i.notional_quote == 10000.0
    assert i.account_equity_quote == 100000.0 and i.leverage == 5.0 and i.stop_pct == 4.0
    assert i.thesis == "Robotaxi 预期" and "340" in (i.invalidation or "")
    assert i.horizon_kind == "through_weekend"


def test_a_chinese_invalidation_number_is_never_read_as_a_size_through_the_full_parser():
    i = p("因为 AI 资本开支继续增长，如果收盘跌破 200 就算错")
    assert i.notional_quote is None


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


@pytest.mark.parametrize(
    ("text", "pct", "direction"),
    [
        ("short 20k TSLA overnight, stop 1% above", 1.0, "above"),
        ("long 20k TSLA overnight, stop 2.5% below", 2.5, "below"),
        ("long 20k TSLA over the weekend, 3% stop", 3.0, None),
        ("long 20k TSLA overnight, stop at 5%", 5.0, None),
    ],
)
def test_a_stop_given_as_a_percentage_is_a_distance_not_a_price(text, pct, direction):  # noqa: ANN001
    """Live test: "stop 1% above" became a stop at 1.00, 99.9% away, hit by all 40 past
    moments. A percentage is how far, never where."""
    p = parse_message(text, ["TSLA"])
    assert p.stop_price is None and p.stop_pct == pct and p.stop_dir == direction
    assert p.notional_quote == 20_000.0  # the percentage is not mistaken for a size either


def test_a_chinese_percentage_stop_is_a_distance_too():
    p = parse_message("周末做多英伟达 2万U，止损3%", ["NVDA"])
    assert p.stop_price is None and p.stop_pct == 3.0 and p.notional_quote == 20_000.0


def test_an_unsaid_direction_is_the_losing_side_and_a_said_one_is_kept():
    from nightwatch.api.intake import intent_to_ticket

    long_ = intent_to_ticket(parse_message("long 20k TSLA overnight, 3% stop", ["TSLA"]), None)
    short = intent_to_ticket(parse_message("short 20k TSLA overnight, 3% stop", ["TSLA"]), None)
    assert long_.stop_offset_pct == -3.0 and short.stop_offset_pct == 3.0
    assert long_.with_stop_resolved(200.0).stop_price == 194.0 and short.with_stop_resolved(200.0).stop_price == 206.0
    # Said the wrong way round, it is kept as said, so the gate can call it wrong-side
    # rather than the desk quietly moving the trader's stop.
    odd = intent_to_ticket(parse_message("short 20k TSLA overnight, stop 3% below", ["TSLA"]), None)
    assert odd.stop_offset_pct == -3.0


def test_a_later_stop_replaces_an_earlier_one_of_either_kind():
    as_price = read_conversation([{"role": "user", "content": "long 20k TSLA overnight, stop 3%"}, {"role": "user", "content": "make the stop 340"}], ["TSLA"])
    assert as_price.stop_price == 340.0 and as_price.stop_pct is None
    as_pct = read_conversation([{"role": "user", "content": "long 20k TSLA overnight, stop 340"}, {"role": "user", "content": "actually stop 2%"}], ["TSLA"])
    assert as_pct.stop_price is None and as_pct.stop_pct == 2.0


def test_a_percentage_stop_reaches_the_report_as_a_price(seeded_store):  # noqa: F811
    r = _report(seeded_store, stop_offset_pct=-3.0, thesis="t", invalidation="i")
    entry = r.snapshot.prices["spot_close"]
    assert r.ticket.stop_price == pytest.approx(entry * 0.97)
    assert "Your stop at" in __import__("nightwatch.api.intake", fromlist=["brief"]).brief(r)


def test_a_size_of_zero_is_said_as_nothing_to_size_not_as_a_size(seeded_store):  # noqa: F811
    """"REVIEW ... Size it at 0 instead" read as a contradiction on a live test."""
    from dataclasses import replace

    from nightwatch.api import intake as it

    r = _report(seeded_store, thesis="t", invalidation="i")
    caps = [replace(c, notional=0.0) if c.name == "exit_liquidity" else c for c in r.verdict.caps]
    r.verdict = replace(r.verdict, recommended_notional=0.0, caps=caps)
    text = it.brief(r)
    assert "Size it at 0" not in text and "No size gets out within the exit-cost budget" in text


def test_a_missing_account_size_is_asked_for_by_name(seeded_store):  # noqa: F811
    from nightwatch.api import intake as it

    r = _report(seeded_store, account_equity_quote=None, thesis="t", invalidation="i")
    assert "tell me your account size" in it.brief(r) and "账户规模" in it.brief(r, "zh")
    assert "tell me your account size" not in it.brief(_report(seeded_store, thesis="t", invalidation="i"))


@pytest.mark.parametrize(
    ("text", "lev"),
    [
        ("5x long NVDA 20k over the weekend", 5.0),
        ("long 20k TSLA overnight at 10x leverage", 10.0),
        ("long 20k TSLA overnight, leverage 3", 3.0),
        ("long 20000 usdt TSLA 100x", 100.0),
        ("周末5倍杠杆做多英伟达 2万U", 5.0),
        ("周末做多英伟达 2万U 杠杆10倍", 10.0),
        ("long 20k TSLA overnight", None),
    ],
)
def test_leverage_is_read_and_never_mistaken_for_a_size(text, lev):  # noqa: ANN001
    """Live test: "5x long NVDA" was analysed as a plain spot trade with no word said."""
    p = parse_message(text, ["TSLA", "NVDA"])
    assert p.leverage == lev and p.notional_quote == 20_000.0


def test_a_leveraged_ticket_gets_a_liquidation_line(seeded_store):  # noqa: F811
    from nightwatch.api import intake as it

    r = _report(seeded_store, leverage=5.0, thesis="t", invalidation="i")
    assert r.leverage is not None
    text = it.brief(r)
    assert "5x" in text and ("liquidat" in text or "perpetual" in text)
    assert any(x.rule == "liquidation" for x in r.gate.rules)
    assert _report(seeded_store, thesis="t", invalidation="i").leverage is None


def test_hours_until_a_weekday_open_and_close():
    from datetime import UTC, datetime

    from nightwatch.api.intake import hours_until_weekday

    sunday_night = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)  # 22:00 ET Sunday
    assert hours_until_weekday(2, "open", sunday_night) == 59.5  # Wednesday 09:30 ET
    assert hours_until_weekday(4, "close", sunday_night) == 114.0  # Friday 16:00 ET
    wed_noon = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)  # Wednesday 12:00 ET, after the open
    assert hours_until_weekday(2, "open", wed_noon) > 6 * 24  # so next Wednesday


def test_stress_preset_names_are_chinese_in_a_chinese_reply():
    from nightwatch.api.intake import preset_zh

    assert preset_zh("closed_window_gap_p1", "Closed-window gap, 1st percentile") == "休市期间跳空（第 1 百分位）"
    assert preset_zh("vol_spike_x3", "Volatility spike x3") == "波动率骤升 ×3"
    assert preset_zh("something_new", "Something new") == "Something new"  # unknown ids keep their name


def test_named_margin_is_multiplied_by_the_leverage():
    p = parse_message("5x long NVDA with 20k margin over the weekend", ["NVDA"])
    assert p.leverage == 5.0 and p.notional_quote == 100_000.0
    q = parse_message("long TSLA 10x, margin 5000, overnight", ["TSLA"])
    assert q.leverage == 10.0 and q.notional_quote == 50_000.0
    assert parse_message("5x long NVDA 20k over the weekend", ["NVDA"]).notional_quote == 20_000.0  # no "margin": the position


def test_a_partial_fill_is_said_once_not_contradicted(seeded_store):  # noqa: F811
    from nightwatch.api import intake as it
    from nightwatch.execution.exit_cost import ExitQuote

    r = _report(seeded_store, thesis="t", invalidation="i")
    r.execution.exit_quote = ExitQuote(5_000_000.0, "sell", 100.0, 120.0, 130.0, 10.0, 60000.0, 65000.0, 20, False, "2026-09-12T14:00:00+00:00")
    text = it.brief(r)
    assert "takes only part of this size" in text and "Getting out costs" not in text


def test_the_first_reply_is_short_and_leads_with_what_matters(seeded_store):  # noqa: F811
    """A judge called the ten-paragraph reply a wall of text. The chat leads with the verdict,
    the one failure mode to watch and an offer of the follow-ups; the page keeps the rest."""
    from nightwatch.api import intake as it

    r = _report(seeded_store, thesis="t", invalidation="i")
    short, full = it.brief_short(r), it.brief(r)
    assert short.split("\n\n")[0] == full.split("\n\n")[0]  # the verdict line, unchanged
    assert len(short) < len(full) and "Ask me:" in short and "what about 5x?" in short
    assert "可以接着问我" in it.brief_short(r, "zh")
    lev = _report(seeded_store, thesis="t", invalidation="i", leverage=5.0)
    assert "no leverage?" in it.brief_short(lev)


def test_a_chinese_trader_saying_na_means_long_and_is_not_asked_the_same_thing_twice():
    """"我想周末拿点特斯拉" is a long. Read as no side, the desk asked 做多还是做空 on every
    turn, byte for byte, and a trader who never types 做多 never got past the first message."""
    from nightwatch.api import intake_zh

    got = intake_zh.read("我想周末拿点特斯拉", set(TICKERS))
    assert got["side"] == "long" and got["ticker"] == "TSLA" and got["horizon_kind"] == "through_weekend"
    assert intake_zh.read("多", set(TICKERS))["side"] == "long" and intake_zh.read("空。", set(TICKERS))["side"] == "short"
    first = intake_zh.ask(["notional_quote"], got)
    assert "特斯拉" in first and "做多" in first and "过周末" in first and "仓位" in first
    assert first != intake_zh.ask(["side", "notional_quote"], {"ticker": "TSLA"})


def test_an_english_clarify_says_back_what_it_has():
    out = read_conversation([{"role": "user", "content": "thinking of holding some nvda over the weekend"}], TICKERS)
    assert out.kind == "clarify" and out.missing_fields == ["notional_quote"]
    assert out.reply.startswith("Got NVDA, long.") and "size" in out.reply


KNOWN = ["TSLA", "AAPL", "NVDA"]


def test_chinese_bare_kong_before_a_stock_is_a_short_with_its_leverage():
    r = parse_message("空特斯拉5千 杠杆3倍", KNOWN)
    assert (r.kind, r.side, r.ticker, r.notional_quote, r.leverage) == ("analyze", "short", "TSLA", 5000.0, 3.0)
    assert parse_message("清空特斯拉", KNOWN).side is None  # clearing a position is not opening a short


def test_chinese_bare_number_after_the_name_is_the_size():
    r = parse_message("拿 苹果 5000 到周三", KNOWN)
    assert (r.kind, r.side, r.ticker, r.notional_quote) == ("analyze", "long", "AAPL", 5000.0)
    # With a price context the number is a level, not a size.
    assert parse_message("拿苹果 止损 190", KNOWN).notional_quote is None


def test_a_negative_size_is_asked_about_not_used():
    for text in ("long tsla -5000", "做多特斯拉 -5000"):
        r = parse_message(text, KNOWN)
        assert r.kind == "clarify" and r.notional_quote is None and r.negative_size
        assert "negative" in r.reply or "负数" in r.reply
    assert parse_message("long TSLA - 5000", KNOWN).notional_quote == 5000.0  # a separator, not a sign
    assert parse_message("long tsla 5k stop -3%", KNOWN).notional_quote == 5000.0


def test_a_stop_at_zero_is_ignored_and_said():
    for text, word in (("long tsla 5000 stop 0", "ignored the stop"), ("做多特斯拉5千 止损0", "忽略")):
        r = parse_message(text, KNOWN)
        assert r.stop_price is None and r.kind == "analyze" and any(word in n for n in r.notes)


def test_leverage_below_one_is_no_leverage_and_said():
    for text in ("long tsla 5k 0.5x", "做多特斯拉5千 杠杆0.5倍"):
        r = parse_message(text, KNOWN)
        assert r.leverage is None and r.notes


def test_an_absurd_hold_is_capped_and_said_and_is_not_read_as_a_size():
    r = parse_message("long tsla 5k for 5000 hours", KNOWN)
    assert r.horizon_hours == 720.0 and r.notional_quote == 5000.0 and r.notes
    assert parse_message("long tsla 5000 hours", KNOWN).notional_quote is None
    assert parse_message("做多特斯拉5千 持有5000小时", KNOWN).horizon_hours == 720.0


def test_the_brief_names_the_verdict_and_cap_in_words_not_identifiers(seeded_store):  # noqa: F811
    from dataclasses import replace

    from nightwatch.api import intake as it
    from nightwatch.decision.sizing import Cap, Verdict

    r = _report(seeded_store, stop_price=100.0, thesis="t", invalidation="i")
    caps = [Cap("exit_liquidity", 715.0, "largest size the live book absorbs within 25 bps")]
    r.verdict = replace(r.verdict, verdict=Verdict.REDUCE_TO, recommended_notional=715.0, caps=caps,
                        reasons=["Size held at 715 USDT: the live order book can absorb only that much within the 25 bps exit-cost budget (requested 10,000)."])
    en, zh = it.brief(r), it.brief(r, "zh")
    assert en.startswith("REDUCE TO on") and "REDUCE_TO" not in en and "exit_liquidity" not in en
    assert "Size held at 715 USDT: the live order book" in en
    assert zh.startswith("建议减仓") and "REDUCE_TO" not in zh


def _lev_dict(**over):
    rungs = [
        {"leverage": 2.0, "margin_quote": 5_000.0, "analog_of": 40, "analog_hits": 0},
        {"leverage": 3.0, "margin_quote": 3_333.333, "analog_of": 40, "analog_hits": 0},
        {"leverage": 10.0, "margin_quote": 1_000.0, "analog_of": 40, "analog_hits": 6},
    ]
    base = {
        "leverage": 10.0, "perp_symbol": "TSLAUSDT", "allowed": True, "margin_quote": 1_000.0, "liquidation_price": 91.0,
        "liquidation_distance_pct": 9.0, "analog_hits": 6, "analog_of": 40, "mc_share": None, "presets_hit": [],
        "tiers_source": "bitget", "mmr": 0.005, "ladder": rungs, "safest_leverage": 3.0, "safest_extra_margin_quote": 2_333.333,
    }
    return {**base, **over}


def test_the_leverage_line_says_what_would_be_safer_and_what_it_costs():
    from nightwatch.api import intake as it

    en = it._leverage_line(_lev_dict(), "en")
    assert "Safer: at 3x (3,333 USDT margin, 2,333 more than now) none of 40 past moments like this reached liquidation." in en
    zh = it._leverage_line(_lev_dict(), "zh")
    assert "更稳妥：3 倍（保证金 3,333 USDT，比现在多 2,333）" in zh and "40 个相似时刻" in zh


def test_no_safer_sentence_when_the_requested_level_is_already_safe_or_there_is_no_ladder():
    from nightwatch.api import intake as it

    assert "Safer" not in it._leverage_line(_lev_dict(safest_extra_margin_quote=None), "en")
    assert "Safer" not in it._leverage_line(_lev_dict(ladder=[], safest_leverage=None), "en")


def test_when_no_level_is_safe_the_chat_says_so():
    from nightwatch.api import intake as it

    line = it._leverage_line(_lev_dict(safest_leverage=None, safest_extra_margin_quote=None), "en")
    assert "No leverage level from 2x to 10x came through clean." in line


def test_a_leveraged_report_carries_the_ladder(seeded_store):  # noqa: F811
    r = _report(seeded_store, leverage=5.0, thesis="t", invalidation="i")
    assert r.leverage is not None and r.leverage.get("ladder")
    levels = [x["leverage"] for x in r.leverage["ladder"]]
    assert 5.0 in levels and levels == sorted(levels)
    assert sum(1 for x in r.leverage["ladder"] if x["requested"]) == 1
    req = next(x for x in r.leverage["ladder"] if x["requested"])
    assert req["analog_hits"] == r.leverage["analog_hits"]  # the ladder agrees with the headline count
