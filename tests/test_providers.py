"""Choosing a model, and the two things every model here has to do.

The bug this layer exists to prevent: the deployed box had no Anthropic key, so
``chat_ready`` was false and every conversational answer came from the rule-based
fallback, on a product whose category is AI. Nothing was broken, nothing was logged,
and nobody noticed. So selection, refusal and the honest reporting of which half of an
answer a model wrote are all pinned here.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from nightwatch.api import providers
from nightwatch.api.providers import AnthropicProvider, ProviderRefusal, QwenProvider, as_provider, describe, select
from nightwatch.data.qwen import QwenError, Usage


class Ticket(BaseModel):
    ticker: str = Field(description="US ticker, e.g. TSLA")
    size: float | None = Field(default=None, description="position size in USDT")
    note: str = ""


# ------------------------------------------------------------------------ anthropic


def anthropic_double(*, parsed=None, stop="end_turn", text="ok", write_stop="end_turn"):  # noqa: ANN001, ANN201
    messages = SimpleNamespace(calls=[])

    def parse(**kwargs):  # noqa: ANN003
        messages.calls.append(kwargs)
        return SimpleNamespace(stop_reason=stop, parsed_output=parsed)

    messages.parse = parse
    beta_calls: list = []

    def create(**kwargs):  # noqa: ANN003
        beta_calls.append(kwargs)
        return SimpleNamespace(stop_reason=write_stop, content=[SimpleNamespace(type="text", text=text)])

    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=SimpleNamespace(create=create, calls=beta_calls)))


def test_anthropic_parses_and_drops_roles_it_was_not_asked_about():
    client = anthropic_double(parsed=Ticket(ticker="TSLA"))
    p = AnthropicProvider(client)
    out = p.parse(
        [{"role": "user", "content": "a"}, {"role": "system", "content": "x"}, {"role": "assistant", "content": "b"}],
        system="sys", schema=Ticket,
    )
    assert out is not None and out.ticker == "TSLA"
    assert [m["role"] for m in client.messages.calls[0]["messages"]] == ["user", "assistant"]


def test_a_refusal_is_raised_not_returned_as_a_blank():
    """A refusal and a failed parse mean different things to the trader, so they must
    not arrive by the same route."""
    with pytest.raises(ProviderRefusal):
        AnthropicProvider(anthropic_double(stop="refusal")).parse([{"role": "user", "content": "x"}], system="s", schema=Ticket)
    with pytest.raises(ProviderRefusal):
        AnthropicProvider(anthropic_double(write_stop="refusal")).write(system="s", user="u")


def test_an_empty_write_is_not_an_answer():
    assert AnthropicProvider(anthropic_double(text="   ")).write(system="s", user="u") is None


# ----------------------------------------------------------------------------- qwen


class QwenDouble:
    model = "qwen3.8-max"

    def __init__(self, payload=None, text="written", error: Exception | None = None):  # noqa: ANN001
        self.payload, self.text, self.error = payload, text, error
        self.seen: list[dict] = []

    def chat_json(self, messages, *, system=None, max_tokens=1200):  # noqa: ANN001, ARG002
        self.seen.append({"messages": messages, "system": system})
        if self.error:
            raise self.error
        return self.payload, Usage(prompt_tokens=10, completion_tokens=5)

    def chat(self, messages, *, system=None, max_tokens=1200):  # noqa: ANN001, ARG002
        self.seen.append({"messages": messages, "system": system})
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, usage=Usage())


def test_qwen_is_told_the_shape_and_the_field_rules():
    """It has no typed output, so the schema travels in the prompt - descriptions and
    all, because that is where the actual rules live."""
    q = QwenDouble(payload={"ticker": "NVDA", "size": 5000})
    out = QwenProvider(q).parse([{"role": "user", "content": "short 5k nvda"}], system="be the intake desk", schema=Ticket)
    assert out is not None and out.ticker == "NVDA" and out.size == 5000
    sent = q.seen[0]["system"]
    assert "be the intake desk" in sent
    assert '"ticker"' in sent and "US ticker" in sent  # the field description came too
    assert "position size in USDT" in sent


def test_a_field_qwen_got_wrong_does_not_lose_the_ones_it_got_right():
    """A bad size should not cost us a good ticker; the desk can ask for one field."""
    out = QwenProvider(QwenDouble(payload={"ticker": "TSLA", "size": "quite a lot"})).parse(
        [{"role": "user", "content": "x"}], system="s", schema=Ticket
    )
    assert out is not None and out.ticker == "TSLA" and out.size is None


def test_an_answer_that_cannot_be_salvaged_is_a_failed_parse():
    out = QwenProvider(QwenDouble(payload={"size": 10})).parse([{"role": "user", "content": "x"}], system="s", schema=Ticket)
    assert out is None  # ticker is required and was never given


def test_the_content_filter_is_a_refusal_and_a_broken_reply_is_not():
    """The gateway rejects some legitimate SEC filings outright. That is the model
    declining, and it reads differently from an answer that simply did not parse."""
    filtered = QwenDouble(error=QwenError('HTTP 400: {"error":{"code":"data_inspection_failed"}}'))
    with pytest.raises(ProviderRefusal):
        QwenProvider(filtered).parse([{"role": "user", "content": "x"}], system="s", schema=Ticket)
    with pytest.raises(ProviderRefusal):
        QwenProvider(QwenDouble(error=QwenError("data_inspection_failed"))).write(system="s", user="u")

    other = QwenDouble(error=QwenError("expected one JSON object, got 'sorry'"))
    assert QwenProvider(other).parse([{"role": "user", "content": "x"}], system="s", schema=Ticket) is None


def test_qwen_does_not_narrate_and_says_so():
    """Measured at 34-88s to rewrite a report against a gateway that times out at 120.
    A provider that cannot do a job while someone waits has to advertise that, or the
    desk will make them wait."""
    assert QwenProvider(QwenDouble()).narrates is False
    assert AnthropicProvider(anthropic_double()).narrates is True


# ------------------------------------------------------------------------ selection


def test_selection_prefers_anthropic_then_qwen_then_nothing(monkeypatch):
    monkeypatch.setattr(providers, "available", lambda: ["anthropic", "qwen"])
    monkeypatch.setattr(providers, "AnthropicProvider", lambda: SimpleNamespace(name="anthropic", model="m"))
    monkeypatch.setattr(providers, "QwenProvider", lambda: SimpleNamespace(name="qwen", model="q"))
    monkeypatch.delenv("NIGHTWATCH_LLM_PROVIDER", raising=False)
    assert select().name == "anthropic"

    monkeypatch.setattr(providers, "available", lambda: ["qwen"])
    assert select().name == "qwen"

    monkeypatch.setattr(providers, "available", lambda: [])
    assert select() is None


def test_an_explicit_choice_wins_and_is_refused_when_it_has_no_credentials(monkeypatch):
    monkeypatch.setattr(providers, "available", lambda: ["anthropic", "qwen"])
    monkeypatch.setattr(providers, "AnthropicProvider", lambda: SimpleNamespace(name="anthropic", model="m"))
    monkeypatch.setattr(providers, "QwenProvider", lambda: SimpleNamespace(name="qwen", model="q"))
    monkeypatch.setenv("NIGHTWATCH_LLM_PROVIDER", "qwen")
    assert select().name == "qwen"

    # Asking for one that is not configured returns nothing rather than quietly using
    # the other: a deployment that meant to run on Qwen should not silently run on Claude.
    monkeypatch.setattr(providers, "available", lambda: ["anthropic"])
    assert select() is None


def test_health_says_which_model_and_which_half_of_the_answer(monkeypatch):
    monkeypatch.setattr(providers, "available", lambda: ["qwen"])
    monkeypatch.setattr(providers, "QwenProvider", lambda: SimpleNamespace(name="qwen", model="qwen3.8-max", narrates=False))
    monkeypatch.delenv("NIGHTWATCH_LLM_PROVIDER", raising=False)
    d = describe()
    assert d["ready"] and d["provider"] == "qwen" and d["model"] == "qwen3.8-max"
    assert d["parses"] is True and d["narrates"] is False

    monkeypatch.setattr(providers, "available", lambda: [])
    d = describe()
    assert d["ready"] is False and d["provider"] is None and d["parses"] is False


def test_a_raw_vendor_client_is_wrapped_and_a_provider_is_left_alone():
    already = QwenProvider(QwenDouble())
    assert as_provider(already) is already
    wrapped = as_provider(anthropic_double())
    assert isinstance(wrapped, AnthropicProvider)
