"""The stress-test agent: the model plans and runs a few tool calls against the desk's own
engine, then writes a cited conclusion.

The model never computes anything. Its four tools wrap code that already exists and is
deterministic (a what-if re-run, the base-rate query, the safest-ways sweep, the follow-up
answers), so every figure it can see comes from the engine. The loop is bounded and the
conclusion is held to the same rule as the analyst's take:

* at most ``MAX_CALLS`` tool calls and about ``TIME_BUDGET_S`` seconds;
* every number in the conclusion must sit on the report's fact sheet or in a tool result,
  tagged with the section it came from, or its sentence is removed (and counted);
* the desk's verdict is restated from the report, never from the model.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from nightwatch.api import analyst

log = logging.getLogger(__name__)

MAX_CALLS = 5
TIME_BUDGET_S = 45.0
MAX_TOKENS = 900
RESULT_CHARS = 1200  # what is fed back to the model per tool call

EXPLAIN_KINDS = ("why", "worst", "exit", "history", "hedge", "premise")
HORIZON_KINDS = ("hours", "next_open", "window_end", "through_weekend")

# The section id a tool's result is filed under, so the model can cite it like a sheet line.
SECTION = {"rerun": "rerun", "base_rate": "base rate", "safest_ways": "safest ways", "explain": "explain"}

TOOLS_DOC = (
    "TOOLS (call at most one per turn; all are exact engine runs on this same moment):\n"
    '- rerun: args {"notional_quote": number, "horizon_kind": "hours|next_open|window_end|through_weekend", '
    '"horizon_hours": number, "leverage": number, "side": "long|short", "lenses": ["earnings_soon"]} - set only the fields '
    "to change; returns verdict, size, one-in-twenty loss and worst stress for the changed trade.\n"
    '- base_rate: args {"move_pct": number, "up": true|false, "weekend": true|false} - how often this token moved that much '
    "over past closed windows.\n"
    "- safest_ways: args {} - the same idea run several ways (half size, hedged, ...).\n"
    "- explain: args {\"kind\": \"" + "|".join(EXPLAIN_KINDS) + "\"} - the desk's own answer on that topic.\n"
)

SYSTEM_EN = (
    "You are a stress-test agent on a trading desk for tokenized US stocks. You are given the desk's FACT SHEET for one "
    "proposed trade. Try to break it: pick the calls that would most change a trader's mind. Reply with ONE JSON object and "
    'nothing else. Either {"thought": "<one short sentence on why this call>", "tool": "<name>", "args": {...}} to run a tool, '
    'or, when you have enough (or are told to stop), {"final": {"summary": "<2-3 sentences>", "findings": ["<one finding>", ...], '
    '"verdict_restated": "<the desk\'s verdict and size exactly as the sheet gives them>"}} with at most 4 findings.\n'
    "CITATIONS: quote only numbers that appear on the fact sheet or in a tool result, exactly as written, and put the [section] "
    "id right after every number, for example: -2.7% [history], 12 bps [order book], 4,200 USDT [rerun]. An untagged or "
    "unsupported number is deleted with its sentence. Never compute a new number. Do not predict direction. You cannot change "
    "the desk's verdict or size; restate them. Never tell the trader what to do; they decide."
)
SYSTEM_ZH = SYSTEM_EN + (
    " Write thought, summary and findings in Simplified Chinese, but keep the [section] ids, tool names, JSON keys and the "
    "verdict word exactly as given."
)


def _num(v: Any, lo: float, hi: float) -> float | None:  # noqa: ANN401
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if lo < x <= hi else None


def _usd(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.0f}"


def _summarise_report(p: dict[str, Any]) -> str:
    v = p.get("verdict") or {}
    ph = p.get("primary_horizon")
    h = ((p.get("analog") or {}).get("horizons") or {}).get(ph) or {}
    p5 = analyst._loss_p5(h)  # noqa: SLF001
    st = p.get("stress") or {}
    rows = [(a, b) for a, b in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if b.get("total_pnl_quote") is not None]
    bits = [f"verdict {v.get('verdict')}", f"size {_usd(v.get('recommended_notional') or 0)} USDT"]
    if p5 is not None:
        bits.append(f"loss_p5_pct (one-in-twenty loss) {p5:+.1f}%")
    if rows:
        a, b = min(rows, key=lambda x: x[1]["total_pnl_quote"])
        bits.append(f"worst stress {a['name']} {_usd(b['total_pnl_quote'])} USDT")
    return ", ".join(bits)


def tool_rerun(state: Any, report: dict[str, Any], args: dict[str, Any]) -> str:  # noqa: ANN401
    from nightwatch.api import whatif
    from nightwatch.pipeline.analyze import analyze

    base = whatif.ticket_from(report)
    if base is None:
        raise ValueError("this report has no ticket to re-run")
    kind = args.get("horizon_kind")
    side = args.get("side")
    lenses = args.get("lenses") or []
    change = whatif.Change(
        notional_quote=_num(args.get("notional_quote"), 0, 1e9),
        horizon_kind=kind if kind in HORIZON_KINDS else None,
        horizon_hours=_num(args.get("horizon_hours"), 0, 24 * 30),
        leverage=_num(args.get("leverage"), 0, 125),
        side=side if side in ("long", "short") else None,
        lenses=tuple(str(x) for x in lenses[:3]) if isinstance(lenses, list) else (),
    )
    if change.empty:
        raise ValueError("no valid change given; set at least one field")
    with state.lock:
        payload = analyze(state.ctx, change.apply_to(base), as_of=whatif.as_of_of(report), record=False).to_dict()
    return f"Change: {change.describe()}. Result: {_summarise_report(payload)}."


def tool_base_rate(state: Any, report: dict[str, Any], args: dict[str, Any]) -> str:  # noqa: ANN401
    from nightwatch.api import baserate, whatif

    move = _num(args.get("move_pct"), 0, 100)
    ticker = (report.get("ticket") or {}).get("ticker")
    if move is None or not ticker:
        raise ValueError("move_pct (above 0, at most 100) is required")
    q = baserate.BaseRateQuestion(str(ticker).upper(), move, bool(args.get("up")), bool(args.get("weekend")))
    out = baserate.answer(state, q, as_of=whatif.as_of_of(report))
    return str((out.get("intent") or {}).get("reply") or "")


def tool_safest_ways(state: Any, report: dict[str, Any], _args: dict[str, Any]) -> str:  # noqa: ANN401
    from nightwatch.api import ways

    out = ways.answer(state, report)
    if not out:
        raise ValueError("could not run the alternatives")
    lines = []
    for x in out.get("ways") or []:
        bit = f"{x['label']}: {x['verdict']} at {_usd(x['size'])} USDT"
        if x.get("p5_quote") is not None:
            bit += f", one-in-twenty loss {_usd(x['p5_quote'])} USDT ({x['p5_pct']:+.1f}%)"
        if x.get("worst_quote") is not None:
            bit += f", worst stress {_usd(x['worst_quote'])} USDT"
        lines.append(bit)
    return "; ".join(lines) + "."


def tool_explain(_state: Any, report: dict[str, Any], args: dict[str, Any]) -> str:  # noqa: ANN401
    from nightwatch.api import followup

    kind = args.get("kind")
    if kind not in EXPLAIN_KINDS:
        raise ValueError(f"kind must be one of {', '.join(EXPLAIN_KINDS)}")
    fn = next(f for k, _p, f in followup.ROUTES if k == kind)
    got = fn(report, "")
    if got is None:
        raise ValueError(f"the report has nothing on '{kind}'")
    return got.text


TOOLS: dict[str, Callable[[Any, dict[str, Any], dict[str, Any]], str]] = {
    "rerun": tool_rerun, "base_rate": tool_base_rate, "safest_ways": tool_safest_ways, "explain": tool_explain,
}


def _compact(text: str, n: int = RESULT_CHARS) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


@dataclass
class Run:
    status: str = "running"  # running | done | failed
    lang: str = "en"
    steps: list[dict[str, Any]] = field(default_factory=list)
    final: dict[str, Any] | None = None
    removed: int = 0
    error: str = ""
    model: str = ""
    started: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = {"status": self.status, "steps": list(self.steps), "final": self.final, "removed": self.removed, "model": self.model}
        if self.error:
            d["error"] = self.error
        return d


def _final(obj: dict[str, Any], report: dict[str, Any], sheet: str, lang: str) -> tuple[dict[str, Any], int]:
    removed = 0
    summary, n, _ = analyst.verify_tagged(analyst._as_text(obj.get("summary")), sheet)  # noqa: SLF001
    removed += n
    findings = []
    raw = obj.get("findings")
    for item in (raw if isinstance(raw, list) else [raw])[:4]:
        clean, n, _ = analyst.verify_tagged(analyst._as_text(item), sheet)  # noqa: SLF001
        removed += n
        if clean:
            findings.append(clean)
    restated = analyst._reconcile(analyst._as_text(obj.get("verdict_restated")), report, sheet, lang)  # noqa: SLF001
    return {"summary": summary, "findings": findings, "verdict_restated": restated}, removed


def run_agent(provider: Any, state: Any, report: dict[str, Any], run: Run, *, budget_s: float = TIME_BUDGET_S, max_calls: int = MAX_CALLS) -> Run:  # noqa: ANN401, C901
    """Drive the loop, appending to ``run.steps`` as each call completes. Blocking."""
    lang = run.lang
    run.model = getattr(provider, "model", "") or ""
    sheet = analyst.fact_sheet(report)
    results: list[str] = []  # tool results as sheet lines, so citations check against them
    transcript: list[str] = []
    system = SYSTEM_ZH if lang == "zh" else SYSTEM_EN
    t0 = time.time()
    bad = 0
    try:
        while True:
            calls = len(run.steps)
            wrap_up = calls >= max_calls or time.time() - t0 > budget_s
            user = f"{TOOLS_DOC}\nFACT SHEET\n\n{sheet}\n"
            if transcript:
                user += "\nTOOL CALLS SO FAR\n" + "\n".join(transcript) + "\n"
            user += ("\nNo more tool calls are allowed. Reply with the final JSON now.\n" if wrap_up
                     else f"\nYou have {max_calls - calls} tool call(s) left. Reply with one JSON object.\n")
            raw = provider.write(system=system, user=user, max_tokens=MAX_TOKENS)
            obj = analyst.parse_reply(raw) if raw else None
            if obj is None:
                bad += 1
                if bad > 1 or not raw:
                    raise RuntimeError("the model did not return usable JSON")
                transcript.append("(your last reply was not one JSON object; reply with exactly one)")
                continue
            checked = sheet + "\n" + "\n".join(results)
            if isinstance(obj.get("final"), dict):
                run.final, removed = _final(obj["final"], report, checked, lang)
                run.removed += removed
                run.status = "done"
                return run
            if wrap_up:
                bad += 1  # asked to stop and called a tool anyway: one more nudge, then give up
                if bad > 1:
                    raise RuntimeError("the model kept calling tools after the cap")
                continue
            name = obj.get("tool")
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            ts = time.time()
            if name not in TOOLS:
                text, ok = f"unknown tool '{name}'; use one of {', '.join(TOOLS)}", False
            else:
                try:
                    text, ok = TOOLS[name](state, report, args), True
                except Exception as exc:  # noqa: BLE001 - a bad call is a result the model can read
                    log.info("agent tool %s failed: %s", name, exc)
                    text, ok = f"error: {exc}", False
            thought, nrm = analyst.strip_unverified(analyst._as_text(obj.get("thought")), checked)  # noqa: SLF001
            run.removed += nrm
            if ok:
                results.append(f"[{SECTION[name]}] {_compact(text)}")
                transcript.append(f"{calls + 1}. {name} {json.dumps(args, ensure_ascii=False)} ->\n{results[-1]}")
            else:
                transcript.append(f"{calls + 1}. {name} {json.dumps(args, ensure_ascii=False)} -> {text}")
            run.steps.append({"n": calls + 1, "thought": thought, "tool": name, "args": args,
                              "result_summary": _compact(text, 400), "seconds": round(time.time() - ts, 1)})
    except Exception as exc:  # noqa: BLE001 - a failed agent keeps the steps it completed
        log.exception("stress-test agent failed")
        run.status, run.error = "failed", str(exc)[:200]
    return run


class AgentJobs:
    """Agent runs in the background, one per report and language."""

    def __init__(self, max_workers: int = 2, keep: int = 100):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agent")
        self._runs: dict[tuple[int, str], Run] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def get(self, forecast_id: int, lang: str = "en") -> Run | None:
        return self._runs.get((forecast_id, lang))

    def start(self, forecast_id: int, report: dict[str, Any], provider: Any, state: Any, lang: str = "en") -> Run:  # noqa: ANN401
        key = (forecast_id, lang)
        with self._lock:
            old = self._runs.get(key)
            if old and (old.status in ("running", "done") or time.time() - old.started < 30):
                return old
            run = Run(lang=lang)
            self._runs[key] = run
            while len(self._runs) > self._keep:
                self._runs.pop(next(iter(self._runs)))
        if provider is None:
            run.status, run.error = "failed", "no model is configured"
            return run

        def work() -> None:
            try:
                run_agent(provider, state, report, run)
            except Exception as exc:  # noqa: BLE001
                run.status, run.error = "failed", str(exc)[:200]

        self._pool.submit(work)
        return run
