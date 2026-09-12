"""The language layer: understand a trade idea, run the numbers, explain them.

Division of labour (deliberate):
* The model **parses** free text into a structured ticket and asks for what is missing.
* The pipeline **computes** every number.
* The model **narrates** the report — and is told it may only use numbers that appear
  in the report. A post-check lists any figure in the narrative that cannot be found
  in the report so the UI can flag it.

Model: Claude Opus 5 with server-side refusal fallbacks enabled (``fallbacks="default"``).
Credentials come from ``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.pipeline.analyze import AnalysisReport, analyze
from nightwatch.pipeline.render import render_text
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ParsedIntent(BaseModel):
    """What the trader wants, as far as the conversation makes clear."""

    kind: str = Field(description="'analyze' when a trade idea is specified well enough to run; 'clarify' when required fields are missing; 'question' for anything else")
    ticker: str | None = Field(default=None, description="US ticker of the tokenized stock, e.g. TSLA, NVDA")
    side: str | None = Field(default=None, description="'long' or 'short'")
    notional_quote: float | None = Field(default=None, description="position size in USDT")
    account_equity_quote: float | None = Field(default=None, description="trader's account equity in USDT, if stated")
    horizon_kind: str | None = Field(default=None, description="'next_open' (hold until the next US regular open), 'window_end', or 'hours'")
    horizon_hours: float | None = Field(default=None, description="only when horizon_kind is 'hours'")
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str | None = Field(default=None, description="the trader's stated reason for the trade, verbatim or lightly cleaned")
    invalidation: str | None = Field(default=None, description="what would prove the idea wrong, if stated")
    hedge_ratio: float | None = Field(default=None, description="share of the position to hedge with the perp, 0..1, if the trader asked for a hedge")
    missing_fields: list[str] = Field(default_factory=list, description="required fields still missing: ticker, side, notional_quote")
    reply: str = Field(description="a short reply to the trader: a clarifying question when kind is 'clarify', an answer when 'question', or a one-line acknowledgement when 'analyze'")


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _parse_system(tickers: list[str], account_equity: float | None) -> str:
    now = utc_now()
    return (
        "You are the intake desk for Nightwatch, a decision stress tester for tokenized US stocks (rTokens) traded 24/7 on Bitget. "
        "Turn the trader's latest message, in the context of the conversation, into a structured ticket. "
        f"Current time: {now:%Y-%m-%d %H:%M} UTC. Available tickers (only these can be analysed): {', '.join(tickers)}. "
        "Defaults when unstated: side long; horizon_kind next_open (hold until the next US regular open) — use 'window_end' if the trader says 'until the close' during a session, "
        "and 'hours' with horizon_hours when they give a number of hours or days (24h per day). "
        + (f"The trader's account equity is {account_equity:,.0f} USDT unless they say otherwise. " if account_equity else "")
        + "Required to analyse: ticker, side, notional_quote. If any is missing, set kind='clarify', list them in missing_fields and ask for them in reply (one short question). "
        "Never invent a stop, a size or a thesis the trader did not give. Keep reply under 40 words."
    )


def parse_intent(client: anthropic.Anthropic, messages: list[dict[str, str]], tickers: list[str], account_equity: float | None) -> ParsedIntent:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        system=_parse_system(tickers, account_equity),
        messages=[{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")],
        output_format=ParsedIntent,
    )
    if response.stop_reason == "refusal":
        return ParsedIntent(kind="question", reply="I can't help with that request.")
    parsed = response.parsed_output
    if parsed is None:
        return ParsedIntent(kind="clarify", missing_fields=["ticker", "side", "notional_quote"], reply="Which token, which direction, and what size?")
    return parsed


def intent_to_ticket(p: ParsedIntent, account_equity: float | None) -> TradeTicket:
    kind = HorizonKind(p.horizon_kind) if p.horizon_kind in ("next_open", "window_end", "hours") else HorizonKind.NEXT_OPEN
    return TradeTicket(
        ticker=(p.ticker or "").upper(), side=Side(p.side or "long"), notional_quote=float(p.notional_quote or 0.0),
        account_equity_quote=p.account_equity_quote or account_equity, horizon_kind=kind, horizon_hours=p.horizon_hours,
        stop_price=p.stop_price, target_price=p.target_price, thesis=p.thesis or "", invalidation=p.invalidation or "", hedge_ratio=p.hedge_ratio,
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


def narrate(client: anthropic.Anthropic, report: AnalysisReport) -> tuple[str, str]:
    text = render_text(report)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=1500,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=NARRATE_SYSTEM,
        messages=[{"role": "user", "content": f"REPORT\n\n{text}"}],
    )
    if response.stop_reason == "refusal":
        return "The explainer declined to narrate this report; the numbers above stand on their own.", text
    narrative = "".join(block.text for block in response.content if block.type == "text").strip()
    return narrative, text


_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def unverified_numbers(narrative: str, report_text: str) -> list[str]:
    """Numbers in the narrative that do not appear in the report text (tolerant of sign/format)."""
    have = {n.replace(",", "").lstrip("+") for n in _NUM.findall(report_text)}
    have_abs = {h.lstrip("-") for h in have}
    out = []
    for n in _NUM.findall(narrative):
        clean = n.replace(",", "").lstrip("+")
        if clean in have or clean.lstrip("-") in have_abs:
            continue
        # allow trailing-zero differences (5 vs 5.0) and enumerations 1-6
        if clean.rstrip("0").rstrip(".") in {h.rstrip("0").rstrip(".") for h in have_abs} or clean in {"1", "2", "3", "4", "5", "6"}:
            continue
        out.append(n)
    return out


def chat_turn(state: Any, messages: list[dict[str, str]], *, account_equity: float | None = None) -> dict[str, Any]:
    client = _client()
    tickers = list(state.ctx.tickers_with_data())
    try:
        intent = parse_intent(client, messages, tickers, account_equity)
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("Anthropic credentials missing or invalid (set ANTHROPIC_API_KEY or run `ant auth login`)") from exc
    result: dict[str, Any] = {"intent": intent.model_dump(), "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": []}
    if intent.kind != "analyze" or intent.missing_fields or not intent.ticker or not intent.notional_quote:
        result["reply"] = intent.reply
        return result
    if intent.ticker.upper() not in tickers:
        result["reply"] = f"{intent.ticker.upper()} is not in the tokenized-stock universe I have data for. Available: {', '.join(tickers[:20])}{'…' if len(tickers) > 20 else ''}."
        result["intent"]["kind"] = "clarify"
        return result
    ticket = intent_to_ticket(intent, account_equity)
    with state.lock:
        report = analyze(state.ctx, ticket)
    narrative, text = narrate(client, report)
    result.update({
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": report.to_dict(),
        "report_text": text,
        "narrative": narrative,
        "unverified_numbers": unverified_numbers(narrative, text),
        "reply": narrative,
    })
    return result
