# ruff: noqa: F811
"""QA round 5: a long chat, bare "weekend", "acct", honest origin labels, and a new trade after a context."""

import pytest

from nightwatch.api import intake
from tests.test_pipeline import seeded_store  # noqa: F401 - fixture
from tests.test_qa4_chat import _frozen_clock, client, say  # noqa: F401, F811 - fixtures

KNOWN = ["TSLA", "NVDA", "AAPL", "AMD", "META"]


def _u(text):
    return {"role": "user", "content": text}


def test_a_long_conversation_is_trimmed_not_refused(client):
    # 60 turns of scroll-back used to answer "Too many messages entries" and stay dead.
    filler = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(60)]
    r = client.post("/chat", json={"messages": filler + [_u("long 5k NVDA overnight, account 50k")]})
    assert r.status_code == 200, r.text
    assert r.json()["ticket"]["ticker"] == "NVDA"


def test_the_server_keeps_the_newest_messages():
    from nightwatch.api.app import CHAT_KEEP, ChatIn

    body = ChatIn(messages=[{"role": "user", "content": str(i)} for i in range(CHAT_KEEP + 25)])
    assert len(body.messages) == CHAT_KEEP and body.messages[-1].content == str(CHAT_KEEP + 24)


@pytest.mark.parametrize("text", ["short 5k AMD weekend account 30k", "short 5k AMD this weekend", "short 5k AMD the weekend", "short 5k AMD over the weekend"])
def test_a_bare_weekend_is_the_weekend_hold(text):
    got = intake.parse_message(text, KNOWN)
    assert got.horizon_kind == intake.THROUGH_WEEKEND


def test_a_chinese_weekend_is_the_weekend_hold():
    assert intake.parse_message("周末做空 AMD 5000U", KNOWN).horizon_kind == intake.THROUGH_WEEKEND


@pytest.mark.parametrize("text,value", [("long 6k NVDA, acct 60k", 60000), ("long 6k NVDA, acc 45k", 45000), ("long 6k NVDA equity 80k", 80000),
                                        ("long 6k NVDA capital 70k", 70000), ("long 6k NVDA account 30k", 30000), ("做多 6000U NVDA 本金 5万", 50000)])
def test_account_spellings_are_read(text, value):
    got = intake.parse_message(text, KNOWN)
    assert got.account_equity_quote == value and got.notional_quote == 6000


def test_into_earnings_does_not_keep_a_hold_from_an_earlier_message():
    got = intake.read_conversation([_u("long 5k TSLA overnight"), _u("thinking of shorting meta into earnings 15k")], KNOWN)
    assert got.through_earnings and got.horizon_kind is None and got.ticker == "META"


def test_the_echo_quotes_the_message_that_gave_a_carried_field(client):
    first = "long 5000 NVDA for 40 hours, account 100k"
    echo = say(client, first, "short 5k TSLA")["reply"]
    assert f'for 40h - typed earlier, in "{first}"' in echo
    assert f'account 100,000 - typed earlier, in "{first}"' in echo


def test_a_hold_nobody_gave_is_labelled_as_the_desks_default(client):
    echo = say(client, "long 5k NVDA, account 50k")["reply"]
    assert "the desk's default, you gave no hold" in echo and "earlier" not in echo


def test_a_field_typed_now_has_no_origin_label(client):
    echo = say(client, "long 5k TSLA overnight, account 20k", "short 5k NVDA for 12 hours, account 60k")["reply"]
    assert "account 60,000" in echo and "account 60,000 -" not in echo
    assert "for 12h -" not in echo


def test_a_new_whole_trade_after_a_report_is_not_a_what_if_on_it(client):
    first = say(client, "5x long TSLA 6k overnight, account 50k")
    fid = first["report"]["forecast_id"]
    out = say(client, "5x long TSLA 6k overnight, account 50k", "5x long TSLA 20k over the weekend", ctx=fid)
    assert out["ticket"] is not None and out["ticket"]["notional_quote"] == 20_000
    assert out.get("mode") != "what_if"


def test_a_change_to_the_report_on_screen_is_still_a_what_if(client):
    first = say(client, "long 10k TSLA overnight, account 50k")
    out = say(client, "long 10k TSLA overnight, account 50k", "halve it", ctx=first["report"]["forecast_id"])
    assert out.get("mode") == "what_if"
