"""Which model answers, and the two things any of them has to be able to do.

The desk's language layer was written against one vendor's SDK, which made "is the
chat live" the same question as "is there an Anthropic key". On the deployed box there
was not one, so every conversational answer was being produced by the rule-based
fallback - working, but not a model, on a product whose whole category is AI.

So the layer is a provider now. A provider does exactly two jobs:

* ``parse`` - turn a conversation into a typed object, validated against a Pydantic
  model. Anthropic does this natively; Qwen is asked for one JSON object and the result
  is validated here, which is the same contract arrived at differently.
* ``write`` - turn a system prompt and a report into English.

Nothing else is allowed through. A provider never computes, never sees a price it was
not handed, and its arithmetic is checked downstream either way.

Selection is deliberate rather than clever: an explicit ``NIGHTWATCH_LLM_PROVIDER``
wins, otherwise the first one whose credentials exist, and if none do the caller falls
back to the rules and says so. Both paths are held to the same number-verification, so
which one answered changes the prose and not the facts.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# "I could not turn that into the shape you asked for" - the model tried and the answer
# did not validate. The caller asks for the missing fields.
UNPARSEABLE = None


class ProviderRefusal(RuntimeError):
    """The model declined the request outright.

    Deliberately distinct from an answer that failed to validate. A refusal means the
    model would not engage; an unparseable answer means it tried and produced the wrong
    shape. Telling a trader "which token, which direction, what size?" when the model
    actually refused would be a lie about what happened, so the two do not share a path.
    """ 


class Provider(Protocol):
    name: str
    model: str
    # Whether this provider is quick enough to rewrite a whole report while a person
    # waits. Not every model is, and the desk must never make someone sit through one.
    narrates: bool

    def parse(self, messages: list[dict[str, str]], *, system: str, schema: type[T], max_tokens: int = 2000) -> T | None: ...

    def write(self, *, system: str, user: str, max_tokens: int = 1500) -> str | None: ...


# ----------------------------------------------------------------------- anthropic


class AnthropicProvider:
    """Claude, through the official SDK's structured output and fallback betas."""

    name = "anthropic"
    narrates = True
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, client: Any = None, model: str = "claude-opus-5"):  # noqa: ANN401
        import anthropic

        self._client = client or anthropic.Anthropic()
        self.model = model

    def parse(self, messages: list[dict[str, str]], *, system: str, schema: type[T], max_tokens: int = 2000) -> T | None:
        response = self._client.messages.parse(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")],
            output_format=schema,
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderRefusal("the model declined the request")
        return response.parsed_output

    def write(self, *, system: str, user: str, max_tokens: int = 1500) -> str | None:
        response = self._client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, betas=[self.FALLBACK_BETA], fallbacks="default",
            system=system, messages=[{"role": "user", "content": user}],
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderRefusal("the model declined to write")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or UNPARSEABLE


# ---------------------------------------------------------------------------- qwen


def _schema_hint(schema: type[BaseModel]) -> str:
    """The shape to answer in, written for a model that has no native typed output.

    Field descriptions are carried through because they are where the actual rules live
    ("'long' or 'short'", "only when horizon_kind is 'hours'"); a bare type list would
    throw away the half of the schema that matters.
    """
    lines = []
    for name, field in schema.model_fields.items():
        kind = getattr(field.annotation, "__name__", str(field.annotation)).replace("Optional", "")
        note = f" - {field.description}" if field.description else ""
        required = "" if not field.is_required() else " (required)"
        lines.append(f'  "{name}": {kind}{required}{note}')
    return "{\n" + "\n".join(lines) + "\n}"


class QwenProvider:
    """Qwen through the hackathon gateway: one JSON object, validated here."""

    name = "qwen"
    # Measured, not assumed. Qwen 3.8 Max reasons before it answers, and the reasoning
    # dominates: rewriting a full report took 88s (3,311 of 3,562 completion tokens were
    # reasoning), and the gateway itself returns 504 at about 120s. Even a stripped-down
    # instruction over a 739-character digest took 34s.
    #
    # Thirty-four seconds to rephrase text the desk already has instantly is a bad trade,
    # so this provider does not narrate. It still parses - 12s to turn "im nervous about
    # the fed thing wednesday, thinking 15k nvidia short overnight" into a short NVDA
    # ticket with the thesis kept, which no rule was ever going to do.
    narrates = False

    def __init__(self, client: Any = None):  # noqa: ANN401
        from nightwatch.data.qwen import QwenClient

        self._client = client or QwenClient()
        self.model = getattr(self._client, "model", "qwen3.8-max")

    def parse(self, messages: list[dict[str, str]], *, system: str, schema: type[T], max_tokens: int = 2000) -> T | None:
        from nightwatch.data.qwen import QwenError

        conversation = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages if m["role"] in ("user", "assistant"))
        instruction = (
            f"{system}\n\n"
            "Answer with one JSON object and nothing else, in exactly this shape. Omit a field or use null "
            "when you do not know it; never invent a value the conversation does not contain.\n\n"
            f"{_schema_hint(schema)}"
        )
        try:
            payload, _ = self._client.chat_json(
                [{"role": "user", "content": f"CONVERSATION\n\n{conversation}"}],
                system=instruction, max_tokens=max_tokens,
            )
        except QwenError as exc:
            # The gateway's content filter answers 400 with an explicit code; that is a
            # refusal. Anything else that comes back malformed is a failed parse.
            if "data_inspection_failed" in str(exc).lower():
                raise ProviderRefusal("the gateway's content filter declined the request") from exc
            log.info("qwen could not parse: %s", exc)
            return UNPARSEABLE
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            # One retry's worth of leniency: drop the fields it got wrong and keep the rest,
            # because a good ticker and size should not be lost to a bad horizon_kind.
            bad = {e["loc"][0] for e in exc.errors() if e.get("loc")}
            cleaned = {k: v for k, v in payload.items() if k not in bad}
            try:
                return schema.model_validate(cleaned)
            except ValidationError:
                log.info("qwen answer did not validate: %s", str(exc)[:200])
                return UNPARSEABLE

    def write(self, *, system: str, user: str, max_tokens: int = 1500) -> str | None:
        from nightwatch.data.qwen import QwenError

        try:
            answer = self._client.chat([{"role": "user", "content": user}], system=system, max_tokens=max_tokens)
        except QwenError as exc:
            if "data_inspection_failed" in str(exc).lower():
                raise ProviderRefusal("the gateway's content filter declined the request") from exc
            log.info("qwen could not write: %s", exc)
            return UNPARSEABLE
        return answer.text.strip() or UNPARSEABLE


# ----------------------------------------------------------------------- selection

ORDER = ("anthropic", "qwen")


def available() -> list[str]:
    """Which providers have credentials, in preference order."""
    out = []
    for name in ORDER:
        if name == "anthropic":
            try:
                import anthropic

                if anthropic.Anthropic().api_key:
                    out.append(name)
            except Exception:  # noqa: BLE001 - no key, no SDK, no profile: all mean the same
                pass
        elif name == "qwen":
            from nightwatch.data.qwen import credentials_present

            if credentials_present():
                out.append(name)
    return out


def select(preferred: str | None = None) -> Provider | None:
    """The provider to answer with, or None when the caller should use the rules."""
    want = (preferred or os.environ.get("NIGHTWATCH_LLM_PROVIDER") or "").strip().lower()
    names = available()
    if want and want not in ("auto", ""):
        if want not in names:
            log.warning("NIGHTWATCH_LLM_PROVIDER=%s has no credentials; available: %s", want, names or "none")
            return None
        names = [want]
    for name in names:
        try:
            return AnthropicProvider() if name == "anthropic" else QwenProvider()
        except Exception:  # noqa: BLE001 - a provider that cannot be built is not available
            log.exception("could not build the %s provider", name)
    return None


def credentials_present() -> bool:
    return bool(available())


def describe() -> dict[str, Any]:
    """What the health endpoint says about the language layer."""
    names = available()
    chosen = select()
    return {
        "ready": bool(names),
        "available": names,
        "preferred": (os.environ.get("NIGHTWATCH_LLM_PROVIDER") or "auto"),
        "provider": chosen.name if chosen else None,
        "model": chosen.model if chosen else None,
        # Said out loud so nobody has to guess which half of the answer a model wrote.
        "parses": bool(chosen),
        "narrates": bool(chosen and getattr(chosen, "narrates", False)),
    }


def as_provider(client: Any) -> Provider:  # noqa: ANN401
    """Wrap whatever a caller injected.

    Tests and the existing call sites pass an Anthropic-shaped client; production passes
    a provider. Accepting both keeps the seam narrow and the tests honest - they still
    exercise the real dispatch rather than a parallel one written for them.
    """
    if hasattr(client, "parse") and hasattr(client, "write") and hasattr(client, "name"):
        return client
    return AnthropicProvider(client)


def json_dumps(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, default=str)
