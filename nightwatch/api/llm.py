"""The language layer: understand a trade idea, run the numbers, explain them.

Division of labour (deliberate):
* The model **parses** free text into a structured ticket and asks for what is missing.
* The pipeline **computes** every number.
* The model **narrates** the report — and is told it may only use numbers that appear
  in the report. A post-check lists any figure in the narrative that cannot be found
  in the report so the UI can flag it.

Which model does it is not this module's business. ``providers`` picks whichever has
credentials - Claude Opus 5, or Qwen 3.8 Max through the hackathon gateway - and both
are held to the same rule: the model may read text and write English, and any figure it
prints that is not in the report is discarded rather than shown.

That separation matters beyond tidiness. The deployed box had no Anthropic key, so
every conversational answer was coming from the rule-based fallback while the product
claimed a language layer. A provider that can be swapped is how "is the chat live"
stops depending on one vendor.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from nightwatch.analog import lens as lens_mod
from nightwatch.api import whatif
from nightwatch.api.providers import Provider, ProviderRefusal, as_provider, select
from nightwatch.decision.ticket import TradeTicket
from nightwatch.pipeline.analyze import AnalysisReport, analyze
from nightwatch.pipeline.render import render_text
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)


class ParsedIntent(BaseModel):
    """What the trader wants, as far as the conversation makes clear."""

    kind: str = Field(description="'analyze' when a trade idea is specified well enough to run; 'clarify' when required fields are missing; 'question' for anything else")
    ticker: str | None = Field(default=None, description="US ticker of the tokenized stock, e.g. TSLA, NVDA")
    side: str | None = Field(default=None, description="'long' or 'short'")
    notional_quote: float | None = Field(default=None, description="position size in USDT")
    account_equity_quote: float | None = Field(default=None, description="trader's account equity in USDT, if stated")
    horizon_kind: str | None = Field(default=None, description="'next_open' (hold until the next US regular open), 'through_weekend' (until the first open after the coming weekend), 'window_end', or 'hours'")
    horizon_hours: float | None = Field(default=None, description="only when horizon_kind is 'hours'")
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str | None = Field(default=None, description="the trader's stated reason for the trade, verbatim or lightly cleaned")
    invalidation: str | None = Field(default=None, description="what would prove the idea wrong, if stated")
    hedge_ratio: float | None = Field(default=None, description="share of the position to hedge with the perp, 0..1, if the trader asked for a hedge")
    missing_fields: list[str] = Field(default_factory=list, description="required fields still missing: ticker, side, notional_quote")
    lenses: list[str] = Field(
        default_factory=list,
        description=(
            "names of conditions narrowing which past moments count as comparable, ONLY when the trader "
            "asked for a narrower comparison ('only earnings nights', 'just weekends', 'when it was volatile'). "
            "Empty unless they asked. Names only, from the list given."
        ),
    )
    reply: str = Field(description="a short reply to the trader: a clarifying question when kind is 'clarify', an answer when 'question', or a one-line acknowledgement when 'analyze'")


def credentials_present() -> bool:
    """True when any provider can answer; the caller uses the rules when it is False."""
    from nightwatch.api.providers import credentials_present as any_provider

    return any_provider()


def _parse_system(tickers: list[str], account_equity: float | None) -> str:
    now = utc_now()
    return (
        "You are the intake desk for Nightwatch, a decision stress tester for tokenized US stocks (rTokens) traded 24/7 on Bitget. "
        "Turn the trader's latest message, in the context of the conversation, into a structured ticket. "
        f"Current time: {now:%Y-%m-%d %H:%M} UTC. Available tickers (only these can be analysed): {', '.join(tickers)}. "
        "Defaults when unstated: side long; horizon_kind next_open (hold until the next US regular open) — use 'window_end' if the trader says 'until the close' during a session, "
        "and 'hours' with horizon_hours ONLY when they give an explicit number of hours or days (24h per day). "
        "'overnight' and 'until the market opens' are next_open. 'Over the weekend', 'through the weekend', 'into Monday' and "
        "'until Monday' are through_weekend: said on a Thursday they mean Monday's open, not Thursday's. Neither is a number of hours. "
        "Write `reply` in the language the trader wrote in. "
        + (f"The trader's account equity is {account_equity:,.0f} USDT unless they say otherwise. " if account_equity else "")
        + "Required to analyse: ticker, side, notional_quote. If any is missing, set kind='clarify', list them in missing_fields and ask for them in reply (one short question). "
        "Never invent a stop, a size or a thesis the trader did not give. Keep reply under 40 words.\n\n"
        'The trader may also narrow which past moments count as comparable - "only earnings nights", '
        '"just weekends", "when it was volatile". Put the matching names in `lenses`, from this list and '
        "no other. Leave it empty unless they actually asked to narrow the comparison: describing their "
        "situation is not the same as asking for a filter, and a lens nobody asked for answers a different "
        "question than the one they put.\n"
        + lens_mod.prompt_menu()
    )


def parse_intent(provider: Provider, messages: list[dict[str, str]], tickers: list[str], account_equity: float | None) -> ParsedIntent:
    """``provider`` may also be a raw vendor client; it is wrapped either way."""
    try:
        parsed = as_provider(provider).parse(messages, system=_parse_system(tickers, account_equity), schema=ParsedIntent, max_tokens=2000)
    except ProviderRefusal:
        # The model would not engage. Saying "which token and what size?" here would
        # describe a failure that did not happen.
        return ParsedIntent(kind="question", reply="I can't help with that request.")
    if parsed is None:
        return ParsedIntent(kind="clarify", missing_fields=["ticker", "side", "notional_quote"], reply="Which token, which direction, and what size?")
    return parsed


class ParsedChange(BaseModel):
    """What a trader's what-if question asks the desk to vary, and nothing else."""

    ticker: str | None = Field(default=None, description="a different token to run the same idea on, if they named one")
    side: str | None = Field(default=None, description="'long' or 'short', only if they asked about the other direction")
    horizon_kind: str | None = Field(default=None, description="'next_open', 'window_end' or 'hours', only if they asked to hold it for a different length of time")
    horizon_hours: float | None = Field(default=None, description="how many hours, when they named a number of hours")
    lenses: list[str] = Field(default_factory=list, description="names of conditions narrowing which past moments count as comparable, from the list given and no other")


def _change_system(ticket: dict, tickers: list[str]) -> str:
    """The prompt for the what-if parse.

    Every instruction here is about restraint. The failure that matters is not missing a
    change; it is inventing one, because an invented change produces a real re-run whose
    numbers are correct for a question nobody asked.
    """
    return (
        "You turn a trader's follow-up question into a list of what CHANGED about a trade the desk has already analysed. "
        "You do not answer the question and you do not compute anything.\n\n"
        f"The trade on screen: {json.dumps(ticket, default=str)}\n"
        f"Tokens with data: {', '.join(tickers)}\n\n"
        "Set ONLY the fields the trader explicitly asked to vary. Leave every other field null or empty - an unset field "
        "means 'as it already is'. If they are asking about the trade as it stands rather than a variation of it, set "
        "nothing at all; that is the correct answer and something else will handle the question.\n"
        "Never change the size or the stop here: those are answered elsewhere and setting them does nothing.\n\n"
        "They may ask to compare against a narrower slice of history - 'was it worse on earnings nights', 'only weekends'. "
        "Put those in `lenses`, from this list and no other:\n"
        + lens_mod.prompt_menu()
    )


def parse_change(provider: Provider, question: str, ticket: dict, tickers: list[str]) -> whatif.Change:
    """What the trader asked to vary, or an empty change when they did not ask for one."""
    try:
        parsed = provider.parse([{"role": "user", "content": question}], system=_change_system(ticket, tickers), schema=ParsedChange, max_tokens=600)
    except ProviderRefusal:
        return whatif.Change()
    if parsed is None:
        return whatif.Change()
    known = {t.upper() for t in tickers}
    asked = (parsed.ticker or "").upper()
    return whatif.Change(
        # A token the desk has no data for is not a what-if it can run, and running the
        # original one under that name would answer the wrong question silently.
        ticker=asked if asked in known and asked != str(ticket.get("ticker", "")).upper() else None,
        side=parsed.side if parsed.side in ("long", "short") and parsed.side != ticket.get("side") else None,
        horizon_kind=parsed.horizon_kind if parsed.horizon_kind in ("next_open", "window_end", "hours") else None,
        horizon_hours=float(parsed.horizon_hours) if parsed.horizon_hours and parsed.horizon_hours > 0 else None,
        lenses=tuple(x.name for x in lens_mod.resolve(parsed.lenses)),
    )


def intent_to_ticket(p: ParsedIntent, account_equity: float | None) -> TradeTicket:
    from nightwatch.api.intake import horizon_fields

    kind, hours, label = horizon_fields(p.horizon_kind, p.horizon_hours)
    return TradeTicket(
        ticker=(p.ticker or "").upper(), side=Side(p.side or "long"), notional_quote=float(p.notional_quote or 0.0),
        account_equity_quote=p.account_equity_quote or account_equity, horizon_kind=kind, horizon_hours=hours,
        extra={"horizon_label": label} if label else {},
        stop_price=p.stop_price, target_price=p.target_price, thesis=p.thesis or "", invalidation=p.invalidation or "", hedge_ratio=p.hedge_ratio,
        # Names the model invented are dropped here rather than reaching the engine.
        lenses=tuple(x.name for x in lens_mod.resolve(p.lenses)),
    )


NARRATE_SYSTEM = (
    "You are Nightwatch's explainer. You receive a decision report about a proposed trade in a tokenized US stock. "
    "Write a concise, plain-English briefing for the trader in this order: (1) the verdict and recommended size/hedge in one line; "
    "(2) what history says — how many similar past moments were found, the median and 5th-percentile outcome over the horizon, and whether that beats random hours; "
    "(3) the worst stress presets and the Monte Carlo tail; (4) exit cost on the live book and the hedge cost if relevant; (5) which cap binds and why; "
    "(6) any warnings or data-quality flags. Use ONLY numbers that appear in the report — copy them exactly, do not round differently, do not compute new ones, "
    "and never add facts the report does not contain. Keep it under 220 words. Do not use markdown headers; short paragraphs or dashes are fine. "
    "The human makes the decision; you inform it."
)


def narrate(provider: Provider, report: AnalysisReport) -> tuple[str, str]:
    """``provider`` may also be a raw vendor client; it is wrapped either way."""
    text = render_text(report)
    try:
        narrative = as_provider(provider).write(system=NARRATE_SYSTEM, user=f"REPORT\n\n{text}", max_tokens=1500)
    except ProviderRefusal:
        narrative = None
    if not narrative:
        # The report is complete without a narrative; the prose is the optional part.
        return "The explainer declined to narrate this report; the numbers above stand on their own.", text
    return narrative, text


FOLLOWUP_SYSTEM = (
    "You are Nightwatch's explainer. The trader is asking a question about a decision report you are given. "
    "Answer only from the report. You may quote and rearrange its numbers; you may not compute new ones, estimate, "
    "round differently, or bring in anything you know from elsewhere. If the report does not contain the answer, say so "
    "plainly and name what it does contain that is closest. You are also given the answer the deterministic layer "
    "produced from the same report: it is correct, so keep its facts and its numbers, and say them better - shorter, "
    "in the order a trader would want them, and without repeating the question back. Under 120 words. No markdown headers. "
    "The human makes the decision; you inform it."
)


def followup_turn(report: dict, question: str, grounded: Any) -> dict:  # noqa: ANN401
    """Say the deterministic answer better, and check it did not invent anything.

    The rules layer has already answered from the report's own fields. The model's job is
    fluency, not arithmetic, so it is handed that answer and told to keep its numbers; any
    figure it prints that is not in the report or in that answer comes back flagged.
    """
    provider = select()
    if provider is None or not getattr(provider, "narrates", True):
        # A provider that cannot write a paragraph while someone waits must not be asked
        # to. The grounded answer is already complete and already correct; spending a
        # minute to have it rephrased, and then discarding the result on timeout, is the
        # worst of both. Same rule the briefing path uses.
        return {}
    report_text = json.dumps(report, default=str)
    try:
        text = provider.write(
            system=FOLLOWUP_SYSTEM,
            user=f"QUESTION\n\n{question}\n\nGROUNDED ANSWER\n\n{grounded.text}\n\nREPORT\n\n{report_text[:120000]}",
            max_tokens=800,
        )
    except ProviderRefusal:
        return {}
    if not text:
        return {}
    unverified = unverified_numbers(text, f"{grounded.text} {report_text}")
    if unverified:
        # A number that is in neither the report nor the grounded answer is a number the
        # model made up. The answer that cannot do that is the one that ships.
        log.warning("model follow-up invented %s; keeping the grounded answer", unverified)
        return {}
    return {"reply": text, "mode": "model", "provider": provider.name, "model": provider.model}


_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _canonical(token: str) -> float | None:
    """A number as a comparable magnitude: commas and sign dropped, 6.160 == 6.16."""
    try:
        return abs(float(token.replace(",", "")))
    except ValueError:
        return None


def unverified_numbers(narrative: str, report_text: str) -> list[str]:
    """Numbers in the narrative that do not appear in the report.

    Comparison is on magnitude, so formatting differences (thousands separators, a
    leading plus, trailing zeros, a loss quoted without its sign) do not raise a flag
    while a genuinely different figure does. Small integers are allowed because the
    briefing is asked for in numbered parts.
    """
    have = {c for c in (_canonical(t) for t in _NUM.findall(report_text)) if c is not None}
    out: list[str] = []
    for token in _NUM.findall(narrative):
        value = _canonical(token)
        if value is None or value in have:
            continue
        if value.is_integer() and 1 <= value <= 6:
            continue
        out.append(token)
    return out


def chat_turn(state: Any, messages: list[dict[str, str]], *, account_equity: float | None = None, client: Any = None, provider: Provider | None = None) -> dict[str, Any]:  # noqa: ANN401
    """One conversational turn.

    ``provider`` is what production passes. ``client`` is still accepted and wrapped,
    because the existing tests inject an Anthropic-shaped double and it is better for
    them to exercise the real dispatch than a parallel one written to suit them.
    """
    provider = provider or (as_provider(client) if client is not None else select())
    if provider is None:
        raise RuntimeError("no language provider has credentials (set BITGET_QWEN_API_KEY or ANTHROPIC_API_KEY)")
    from nightwatch.api import intake

    tickers = list(state.ctx.tickers_with_data())
    latest = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and (m.get("content") or "").strip()), "")
    lang = intake.language_of(latest)
    # The rules read an ordinary trade message in milliseconds and the model takes
    # 10-60 s, so the model is asked only when the rules cannot finish the job: a message
    # they could not complete, one not in English, or a request to narrow the history.
    rules = intake.read_conversation(messages, tickers, account_equity)
    fast = rules.kind == "analyze" and (rules.ticker or "").upper() in tickers and not intake.needs_the_model(latest)
    if fast:
        ticket = intake.intent_to_ticket(rules, account_equity)
        parsed_by = "rules"
        result: dict[str, Any] = {"intent": rules.as_dict(), "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": [], "provider": provider.name, "model": provider.model}
    else:
        intent = parse_intent(provider, messages, tickers, account_equity)
        parsed_by = provider.name
        result = {"intent": intent.model_dump(), "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": [], "provider": provider.name, "model": provider.model}
        if intent.kind != "analyze" or intent.missing_fields or not intent.ticker or not intent.notional_quote:
            result["reply"] = intent.reply
            return result
        if intent.ticker.upper() not in tickers:
            result["reply"] = f"{intent.ticker.upper()} is not in the tokenized-stock universe I have data for. Available: {', '.join(tickers[:20])}{'…' if len(tickers) > 20 else ''}."
            result["intent"]["kind"] = "clarify"
            return result
        if intent.lenses and not intake.asks_to_narrow(latest):
            # The model narrowed a comparison nobody asked to narrow ("hold it over the
            # weekend" became "compare only against weekends"). That answers a different
            # question from the one put, so it is undone here rather than trusted.
            intent = intent.model_copy(update={"lenses": []})
        ticket = intent_to_ticket(intent, account_equity)
    with state.lock:
        report = analyze(state.ctx, ticket)
        payload = report.to_dict()
        # Keep it, so the next message can be a question about this answer.
        if report.forecast_id is not None:
            try:
                state.reports.save(report.forecast_id, payload)
            except Exception:  # noqa: BLE001 - a keepsake must not fail the turn
                pass
    # The model understood the sentence; whether it also writes the briefing depends on
    # whether it can do that while someone waits. A provider that cannot says so, and the
    # briefing is assembled from the report's own fields instead - instantly, and with
    # nothing to verify because nothing was written.
    # A trader who wrote in Chinese is answered in Chinese, from the same fields.
    if getattr(provider, "narrates", True) and lang == "en":
        narrative, text = narrate(provider, report)
        wrote = provider.name
    else:
        narrative, text = intake.brief(report, lang), render_text(report)
        wrote = "rules"
    result.update({
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": payload,
        "report_text": text,
        "narrative": narrative,
        "unverified_numbers": unverified_numbers(narrative, text) if wrote != "rules" else [],
        "reply": narrative,
        "parsed_by": parsed_by,
        "written_by": wrote,
        "language": lang,
    })
    return result
