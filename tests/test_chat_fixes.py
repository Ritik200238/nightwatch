"""Chat problems a judge hit on the live desk, each with the audit's exact input."""

import pytest
from fastapi.testclient import TestClient

from nightwatch.api.app import create_app
from nightwatch.config import Settings
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: False)
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "off")  # the analyst's background take must not reach a real model


@pytest.fixture
def client(seeded_store, monkeypatch):  # noqa: F811
    monkeypatch.setenv("NIGHTWATCH_LIVE_BOOK", "0")
    settings = Settings(data_dir=seeded_store.parent, db_filename=seeded_store.name, core_tickers=("TSLA", "NVDA", "AAPL"))
    with TestClient(create_app(settings, warm=False)) as c:
        yield c


def say(client, *texts, ctx=None, equity=None):
    body = {"messages": [{"role": "user", "content": t} for t in texts]}
    if ctx:
        body["context_forecast_id"] = ctx
    if equity:
        body["account_equity_quote"] = equity
    r = client.post("/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_account_prompt_is_not_repeated_once_the_account_is_known(client):
    """After "account 50k" the reply still said "tell me your account size": the check
    matched the word "equity" in "position is 100% of equity" and took it for a missing one."""
    known = say(client, "long 40000 TSLA overnight, account 50k")
    assert known["ticket"]["account_equity_quote"] == 50000
    assert "account size" not in known["reply"] and "账户规模" not in known["reply"]
    unknown = say(client, "long 40000 TSLA overnight")
    assert "account size" in unknown["reply"]


# --- 1. amounts written the Chinese way -------------------------------------------------

AMOUNTS = [
    ("周末做多特斯拉 2万U", 20000), ("周末做多特斯拉 2万", 20000), ("周末做多特斯拉 2w", 20000), ("做多特斯拉 2W", 20000),
    ("周末做多特斯拉 两万", 20000), ("周末做多特斯拉 1.5万U", 15000), ("周末做多特斯拉 3千U", 3000),
    ("做多特斯拉 2万美金", 20000), ("周末做多特斯拉 ２万Ｕ", 20000), ("long tsla 2w overnight", 20000),
    ("long tsla 10k", 10000), ("long tsla 20K", 20000),
]


@pytest.mark.parametrize(("text", "size"), AMOUNTS)
def test_amounts_and_names_are_read_exactly(client, text, size):
    r = say(client, text)
    assert r["ticket"]["ticker"] == "TSLA" and r["ticket"]["notional_quote"] == size, r["reply"]
    assert r["ticket"]["side"] == "long"


def test_a_duration_in_weeks_is_not_a_size():
    from nightwatch.api import intake

    assert intake.parse_message("long tsla for 2w", ["TSLA"]).notional_quote is None


class _Fake:
    name, model, narrates = "fake", "fake", False

    def __init__(self, parsed=None):
        self.parsed, self.calls = parsed, 0

    def parse(self, messages, *, system, schema, max_tokens=2000):
        self.calls += 1
        return self.parsed

    def write(self, **kw):
        return None


def test_the_standard_chinese_prompt_never_waits_for_the_model(client, monkeypatch):
    fake = _Fake()
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "周末做多特斯拉 2万U")
    assert fake.calls == 0 and r["ticket"]["notional_quote"] == 20000 and r["ticket"]["ticker"] == "TSLA"


def test_when_the_model_misreads_the_amount_the_rules_reading_stands(client, monkeypatch):
    """The audit saw Qwen answer "Which ticker and side?" to this text."""
    from nightwatch.api.llm import ParsedIntent

    wrong = ParsedIntent(kind="clarify", notional_quote=2.0, missing_fields=["ticker", "side"], reply="Which ticker and side?")
    fake = _Fake(wrong)
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "周末做多特斯拉 2万U，只对比周末")  # "只" asks to narrow, so the model is consulted
    assert fake.calls == 1
    assert r["ticket"]["notional_quote"] == 20000 and r["ticket"]["ticker"] == "TSLA"


# --- 4. "I have 100k" is the account, not the position -----------------------------------

@pytest.mark.parametrize("phrase", ["I have 100k", "my account is 100k", "account is 100k", "equity 100k", "I've got 100k"])
def test_money_on_hand_is_the_account_not_a_position(phrase):
    from nightwatch.api import intake

    p = intake.parse_message(f"long tsla 20k overnight, {phrase}", ["TSLA"])
    assert p.account_equity_quote == 100000 and p.notional_quote == 20000


@pytest.mark.parametrize("phrase", ["本金10万U", "账户10万U", "我有10万U", "余额10万"])
def test_chinese_money_on_hand_is_the_account(phrase):
    from nightwatch.api import intake

    p = intake.parse_message(f"周末做多特斯拉 2万U，{phrase}", ["TSLA"])
    assert p.account_equity_quote == 100000 and p.notional_quote == 20000


def test_a_holding_is_not_taken_for_the_account():
    from nightwatch.api import intake

    assert intake.parse_message("I have 20k of tsla", ["TSLA"]).account_equity_quote is None
    assert intake.parse_message("我有2万U的特斯拉", ["TSLA"]).account_equity_quote is None


def test_switching_ticker_with_same_size_and_a_new_account_keeps_the_size(client):
    """"tsla instead, same size, I have 100k" ran a 100,000 USDT TSLA long on the live desk."""
    first = say(client, "long 20000 NVDA overnight")
    fid = first["report"]["forecast_id"]
    moved = say(client, "long 20000 NVDA overnight", "actually what about tsla instead, same size, I have 100k", ctx=fid)
    t = moved["ticket"]
    assert t["ticker"] == "TSLA" and t["notional_quote"] == 20000 and t["account_equity_quote"] == 100000, moved["reply"]


def test_an_account_said_on_its_own_reruns_the_trade_on_screen(client):
    first = say(client, "long 20000 TSLA overnight")
    assert first["ticket"]["account_equity_quote"] is None
    fid = first["report"]["forecast_id"]
    after = say(client, "long 20000 TSLA overnight", "my account is 100k", ctx=fid)
    t = after["ticket"]
    assert t["ticker"] == "TSLA" and t["notional_quote"] == 20000 and t["account_equity_quote"] == 100000, after["reply"]
    assert "account" in after["reply"].lower()


def test_chinese_account_on_the_trade_on_screen(client):
    first = say(client, "周末做多特斯拉 2万U")
    after = say(client, "周末做多特斯拉 2万U", "我有10万U", ctx=first["report"]["forecast_id"])
    assert after["ticket"]["notional_quote"] == 20000 and after["ticket"]["account_equity_quote"] == 100000, after["reply"]


# --- 7. the rate limit a fast human cannot hit --------------------------------------------

def test_a_judge_clicking_quickly_is_not_limited_but_a_script_is():
    """Five to eight quick messages got "Too many requests". Uses the real production rules."""
    from nightwatch.api import guard

    now = [0.0]
    rl = guard.RateLimiter(clock=lambda: now[0])
    for path in ("/chat", "/analyze"):
        group, rate, burst = guard.rule_for("POST", path)
        waits = []
        for _ in range(8):  # eight clicks inside two seconds
            waits.append(rl.take(group, "judge", rate, burst))
            now[0] += 0.25
        assert waits == [0.0] * 8, path
        spam = [rl.take(group, "script", rate, burst) for _ in range(60)]  # 60 in the same instant
        assert spam.count(0.0) == burst and all(w > 0 for w in spam[burst:])
        now[0] += 3.0  # one token comes back every three seconds
        assert rl.take(group, "script", rate, burst) == 0.0 and rl.take(group, "script", rate, burst) > 0


def test_the_limit_is_still_a_real_ceiling():
    from nightwatch.api import guard

    _, rate, burst = guard.rule_for("POST", "/chat")
    assert burst >= 12 and rate <= 30  # loose for a hand, closed to a loop


# --- 2. a token, a side and an account but no size ----------------------------------------

def test_no_size_runs_the_largest_size_the_desk_allows_and_says_so(client):
    r = say(client, "5x long TSLA overnight, my account is 50k")
    assumed = r["size_assumed"]
    size = assumed["notional_quote"]
    assert assumed["basis"] in ("largest_go", "desk_cap") and 0 < size <= 0.25 * 50000
    assert r["ticket"]["notional_quote"] == size and r["ticket"]["account_equity_quote"] == 50000 and r["ticket"]["leverage"] == 5
    assert "You didn't give a size" in r["reply"] and f"{size:,.0f} USDT" in r["reply"] and "50k account" in r["reply"]
    assert "run that instead" in r["reply"]  # invites the trader's own size
    assert r["report"] is not None


def test_the_assumed_size_is_one_that_passes(client):
    r = say(client, "long TSLA overnight, account 50k")
    if r["size_assumed"]["basis"] == "largest_go":
        assert r["report"]["verdict"]["verdict"] == "GO"


def test_no_size_in_chinese(client):
    r = say(client, "5倍杠杆做多特斯拉 过夜 账户5万U")
    size = r["size_assumed"]["notional_quote"]
    assert r["ticket"]["notional_quote"] == size and r["ticket"]["leverage"] == 5 and r["ticket"]["account_equity_quote"] == 50000
    assert "你没有给仓位" in r["reply"] and "5万U 账户" in r["reply"]
    assert f"{size:,.0f} USDT" in r["reply"]


def test_a_given_size_is_never_replaced(client):
    r = say(client, "long 8000 TSLA overnight, account 50k")
    assert "size_assumed" not in r and r["ticket"]["notional_quote"] == 8000


def test_no_size_and_no_account_still_asks(client):
    r = say(client, "long TSLA overnight")
    assert r["ticket"] is None and "size" in r["reply"] and "size_assumed" not in r


def test_the_model_is_not_asked_for_a_missing_size(client, monkeypatch):
    fake = _Fake()
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "5x long TSLA overnight, my account is 50k")
    assert fake.calls == 0 and r["size_assumed"]["notional_quote"] > 0 and "You didn't give a size" in r["reply"]


# --- 5. an unknown ticker is not a dead end -----------------------------------------------

def test_an_unknown_ticker_lists_the_covered_ones(client):
    r = say(client, "long 5k XYZQ over the weekend")
    assert r["ticket"] is None and "XYZQ" in r["reply"]
    assert "AAPL, NVDA, TSLA" in r["reply"]


def test_an_unknown_ticker_without_a_model_call(client, monkeypatch):
    fake = _Fake()
    monkeypatch.setattr("nightwatch.api.llm.credentials_present", lambda: True)
    monkeypatch.setattr("nightwatch.api.llm.select", lambda *a, **k: fake)
    r = say(client, "long 5k XYZQ over the weekend")
    assert fake.calls == 0 and "AAPL, NVDA, TSLA" in r["reply"]


def test_an_unnamed_token_lists_the_covered_ones_too(client):
    r = say(client, "long 5k over the weekend")
    assert "AAPL, NVDA, TSLA" in r["reply"]


def test_ordinary_capitals_are_not_unknown_tokens(client):
    r = say(client, "LONG 5k TSLA OVERNIGHT")
    assert r["ticket"]["ticker"] == "TSLA"


# --- 6. "should I buy?" -------------------------------------------------------------------

def test_should_i_buy_on_the_trade_on_screen_answers_with_the_verdict(client):
    first = say(client, "long 20000 TSLA overnight, account 200k")
    fid = first["report"]["forecast_id"]
    verdict = first["report"]["verdict"]["verdict"].replace("_", " ")
    r = say(client, "long 20000 TSLA overnight, account 200k", "should I buy?", ctx=fid)
    assert r["answer_kind"] == "decide" and verdict in r["reply"] and "20,000 USDT" in r["reply"]
    assert "no edge on direction" in r["reply"]  # never a prediction


def test_chinese_should_i_buy_on_the_trade_on_screen(client):
    first = say(client, "周末做多特斯拉 2万U，账户20万U")
    r = say(client, "周末做多特斯拉 2万U，账户20万U", "该买吗", ctx=first["report"]["forecast_id"])
    assert r["answer_kind"] == "decide" and "系统的回答" in r["reply"] and "没有优势" in r["reply"]


def test_should_i_buy_a_token_runs_it_at_a_stated_stand_in_size(client):
    r = say(client, "should I buy nvda?")
    assert r["size_assumed"]["basis"] == "stand_in" and r["ticket"]["ticker"] == "NVDA"
    assert "I don't predict direction" in r["reply"] and "stand-in of 10,000 USDT" in r["reply"]
    assert r["report"]["verdict"]["verdict"]


def test_should_i_buy_with_an_account_uses_the_largest_allowed_size(client):
    r = say(client, "should I buy nvda? I have 50k")
    assert r["size_assumed"]["basis"] in ("largest_go", "desk_cap") and "I don't predict direction" in r["reply"]


def test_should_i_buy_without_a_token_says_what_the_desk_can_do(client):
    r = say(client, "should I buy?")
    assert r["ticket"] is None and "I don't predict direction" in r["reply"] and "AAPL, NVDA, TSLA" in r["reply"]
    z = say(client, "该买吗")
    assert z["ticket"] is None and "我不预测涨跌" in z["reply"] and "AAPL, NVDA, TSLA" in z["reply"]


def test_shorting_and_buying_are_sides_too(client):
    """"thinking of shorting aapl tonite maybe 10k?? worst case?" asked "long or short?" and went to the model."""
    r = say(client, "thinking of shorting aapl tonite maybe 10k?? worst case?")
    assert r["ticket"]["side"] == "short" and r["ticket"]["ticker"] == "AAPL" and r["ticket"]["notional_quote"] == 10000
    assert say(client, "buying 5k nvda overnight")["ticket"]["side"] == "long"
