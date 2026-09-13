"""The language layer, driven by a fake model client: no credentials, no network.

What matters here is the division of labour: the model only parses and narrates, the
pipeline owns every number, and a number the model invents is reported as unverified.
"""

from types import SimpleNamespace

import pytest

from nightwatch.analog.engine import AnalogConfig
from nightwatch.api.llm import ParsedIntent, chat_turn, intent_to_ticket, parse_intent, unverified_numbers
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.decision.ticket import HorizonKind
from nightwatch.pipeline.analyze import AnalysisContext
from nightwatch.stress.scenarios import Side
from tests.test_pipeline import AS_OF, seeded_store  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    """The chat entry has no as_of parameter: it always analyses "now". The seeded store
    ends at a fixed instant, so without pinning the clock these tests pass on the day
    they are written and fail the next morning on the staleness guard."""
    monkeypatch.setattr("nightwatch.pipeline.analyze.utc_now", lambda: AS_OF)


class FakeMessages:
    def __init__(self, intent: ParsedIntent | None, stop_reason: str = "end_turn"):
        self.intent = intent
        self.stop_reason = stop_reason
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.intent)


class FakeBetaMessages:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.text = text
        self.stop_reason = stop_reason
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


class FakeClient:
    def __init__(self, intent: ParsedIntent | None = None, narrative: str = "ok", parse_stop: str = "end_turn", narrate_stop: str = "end_turn"):
        self.messages = FakeMessages(intent, parse_stop)
        self.beta = SimpleNamespace(messages=FakeBetaMessages(narrative, narrate_stop))


@pytest.fixture
def state(seeded_store):  # noqa: F811
    store = Store(seeded_store)
    entries = [UniverseEntry(t, f"R{t}USDT", f"{t}USDT", t, True) for t in ("TSLA", "NVDA", "AAPL")]
    ctx = AnalysisContext(store=store, entries=entries, analog_config=AnalogConfig(k=30, min_matches=10, min_separation_h=36, min_age_h=96))
    import threading

    yield SimpleNamespace(ctx=ctx, lock=threading.Lock())
    store.close()


def test_missing_fields_ask_instead_of_analysing(state):
    intent = ParsedIntent(kind="clarify", ticker="TSLA", missing_fields=["notional_quote"], reply="How big?")
    out = chat_turn(state, [{"role": "user", "content": "thinking about TSLA"}], client=FakeClient(intent))
    assert out["reply"] == "How big?" and out["report"] is None and out["ticket"] is None


def test_unknown_ticker_is_refused_with_the_available_list(state):
    intent = ParsedIntent(kind="analyze", ticker="DOGE", side="long", notional_quote=1000.0, reply="ok")
    out = chat_turn(state, [{"role": "user", "content": "long 1k DOGE"}], client=FakeClient(intent))
    assert "not in the tokenized-stock universe" in out["reply"] and out["intent"]["kind"] == "clarify"
    assert out["report"] is None


def test_full_turn_runs_the_pipeline_and_flags_invented_numbers(state):
    intent = ParsedIntent(kind="analyze", ticker="TSLA", side="long", notional_quote=20_000.0, account_equity_quote=200_000.0, thesis="momentum", invalidation="close below", reply="running it")
    client = FakeClient(intent, narrative="Verdict stands. Sharpe of 4.9137 says buy.")
    out = chat_turn(state, [{"role": "user", "content": "long 20k TSLA into Monday"}], account_equity=200_000.0, client=client)
    assert out["report"] is not None and out["ticket"]["ticker"] == "TSLA"
    assert "VERDICT:" in out["report_text"]
    assert "4.9137" in out["unverified_numbers"]  # a number the report never contained
    # The narrator is shown the rendered report and nothing else.
    assert client.beta.messages.calls[0]["messages"][0]["content"].startswith("REPORT")
    # Available tickers are given to the parser so it cannot invent one.
    assert "TSLA" in client.messages.calls[0]["system"]
    # Narration asks for the server-side refusal fallback.
    assert client.beta.messages.calls[0]["betas"] == ["server-side-fallback-2026-07-01"] and client.beta.messages.calls[0]["fallbacks"] == "default"


def test_refusals_degrade_to_a_plain_answer(state):
    refusing = FakeClient(None, parse_stop="refusal")
    out = chat_turn(state, [{"role": "user", "content": "..."}], client=refusing)
    assert out["intent"]["kind"] == "question" and "can't help" in out["reply"]

    intent = ParsedIntent(kind="analyze", ticker="TSLA", side="long", notional_quote=5_000.0, reply="ok")
    client = FakeClient(intent, narrate_stop="refusal")
    out = chat_turn(state, [{"role": "user", "content": "long 5k TSLA"}], client=client)
    assert out["report"] is not None and "numbers above stand on their own" in out["narrative"]


def test_unparseable_response_asks_for_the_three_required_fields(state):
    out = chat_turn(state, [{"role": "user", "content": "??"}], client=FakeClient(None))
    assert out["intent"]["missing_fields"] == ["ticker", "side", "notional_quote"]


def test_parse_intent_passes_the_conversation_and_drops_other_roles():
    client = FakeClient(ParsedIntent(kind="question", reply="hi"))
    parse_intent(client, [{"role": "user", "content": "a"}, {"role": "system", "content": "x"}, {"role": "assistant", "content": "b"}], ["TSLA"], 100.0)
    sent = client.messages.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant"]
    assert "100 USDT" in client.messages.calls[0]["system"]


def test_intent_defaults_are_conservative():
    t = intent_to_ticket(ParsedIntent(kind="analyze", ticker="tsla", notional_quote=100.0, reply=""), 5_000.0)
    assert t.ticker == "TSLA" and t.side is Side.LONG and t.horizon_kind is HorizonKind.NEXT_OPEN
    assert t.account_equity_quote == 5_000.0 and t.thesis == "" and t.stop_price is None


def test_unverified_numbers_tolerates_formatting_but_catches_invention():
    report = "p5 -6.16% size 16,338 fee 10 bps"
    assert unverified_numbers("loss -6.16% on 16338 at 10 bps", report) == []
    assert unverified_numbers("loss 6.160% ", report) == []  # trailing zeros, sign dropped
    assert unverified_numbers("+16,338 at 10 bps", report) == []  # separators and a leading plus
    assert unverified_numbers("Sharpe 1.87 and 42 trades", report) == ["1.87", "42"]
    assert unverified_numbers("(1) verdict (2) history", report) == []  # numbered parts
    assert unverified_numbers("size 1 lot", report) == []  # 1 is allowed, 16,338 is not 1
    assert unverified_numbers("size 100", report) == ["100"]  # not a truncation of 10
