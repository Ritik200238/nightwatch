"""The stress-test agent: the model plans and runs a few tool calls against the desk's own
engine, then writes a cited conclusion.

The model never computes anything. Its five tools wrap code that already exists and is
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
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any

from nightwatch.api import analyst
from nightwatch.features import bitget_data
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

MAX_CALLS = 5
TIME_BUDGET_S = 45.0
# One slow call must not eat the whole budget: a live run took 83 s for two checks. Each model
# call and each tool call gets its own cap, and the run as a whole ends by HARD_STOP_S with
# whatever it has found so far.
MODEL_TIMEOUT_S = 25.0
TOOL_TIMEOUT_S = 30.0
HARD_STOP_S = 70.0
MAX_TOKENS = 900
RESULT_CHARS = 1200  # what is fed back to the model per tool call

EXPLAIN_KINDS = ("why", "worst", "exit", "history", "hedge", "premise")
HORIZON_KINDS = ("hours", "next_open", "window_end", "through_weekend")

# The section id a tool's result is filed under, so the model can cite it like a sheet line.
SECTION = {"rerun": "rerun", "base_rate": "base rate", "safest_ways": "safest ways", "explain": "explain", "bitget_data": "bitget"}

TOOLS_DOC = (
    "TOOLS (call at most one per turn; all are exact engine runs on this same moment):\n"
    '- rerun: args {"notional_quote": number, "horizon_kind": "hours|next_open|window_end|through_weekend", '
    '"horizon_hours": number, "leverage": number, "side": "long|short", "lenses": ["earnings_soon"]} - set only the fields '
    "to change; returns verdict, size, one-in-twenty loss and worst stress for the changed trade.\n"
    '- base_rate: args {"move_pct": number, "up": true|false, "weekend": true|false} - how often this token moved that much '
    "over past closed windows.\n"
    "- safest_ways: args {} - the same idea run several ways (half size, hedged, ...).\n"
    "- explain: args {\"kind\": \"" + "|".join(EXPLAIN_KINDS) + "\"} - the desk's own answer on that topic.\n"
    '- bitget_data: args {"entry": "' + "|".join(bitget_data.ALLOWED) + '", "ticker": "<optional, default the ticket\'s>"} - one entry '
    "of Bitget's US-stock data service: earnings calendar, valuation ratios, dividends, analyst consensus, company profile, the "
    "stock's live quote, analyst ratings, insider trades, market fear and greed. Cached reads, so it is fast; cite its numbers as [bitget].\n"
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
    "the desk's verdict or size; restate them. Never tell the trader what to do; they decide. Each call must test something "
    "different from the ticket and from earlier calls (size, hold, leverage, side, a condition, the base rate of a move); each "
    "thought must say what that call can reveal, in new words - do not repeat an earlier thought."
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


def _word(v: Any) -> str:  # noqa: ANN401
    """A verdict or cap code as the words a trader reads: REDUCE_TO -> REDUCE TO."""
    return str(v).replace("_", " ")


def _summarise_report(p: dict[str, Any]) -> str:
    v = p.get("verdict") or {}
    ph = p.get("primary_horizon")
    h = ((p.get("analog") or {}).get("horizons") or {}).get(ph) or {}
    p5 = analyst._loss_p5(h)  # noqa: SLF001
    st = p.get("stress") or {}
    rows = [(a, b) for a, b in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if b.get("total_pnl_quote") is not None]
    bits = [f"verdict {_word(v.get('verdict'))}", f"size {_usd(v.get('recommended_notional') or 0)} USDT"]
    if p5 is not None:
        bits.append(f"one-in-twenty loss {p5:+.1f}%")
    if rows:
        a, b = min(rows, key=lambda x: x[1]["total_pnl_quote"])
        bits.append(f"worst stress {a['name']} {_usd(b['total_pnl_quote'])} USDT")
    return ", ".join(bits)


def _within(fn: Callable[[], Any], timeout_s: float) -> Any:  # noqa: ANN401
    """Run ``fn`` and give up on it after ``timeout_s`` seconds (raises TimeoutError).

    The abandoned call is left to finish on its own thread; it cannot be killed, but the run
    no longer waits for it."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-call")
    try:
        return pool.submit(fn).result(timeout=max(1.0, timeout_s))
    except FuturesTimeout as exc:
        raise TimeoutError(f"no answer within {timeout_s:.0f} s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def partial_final(run: Any, report: dict[str, Any], lang: str) -> dict[str, Any]:  # noqa: ANN401
    """The conclusion when time ran out: what was checked, the desk's own verdict, and no
    model-written number. The steps above it carry the results."""
    done = [x for x in run.steps if not x.get("refused") and not str(x.get("result_summary", "")).startswith("error")]
    n = len(done)
    if lang == "zh":
        summary = f"时间用完了，只完成了 {n} 项检查；各项结果见上方步骤。" if n else "时间用完了，没有完成任何检查。"
    else:
        summary = f"Time ran out after {n} check{'s' if n != 1 else ''}; each result is in the steps above." if n else "Time ran out before any check finished."
    return {"summary": summary, "findings": [], "verdict_restated": analyst._fixed_reconcile(report, lang), "partial": True}  # noqa: SLF001


class NoOpCall(ValueError):
    """A call that would only re-run the ticket as it stands. Refused, and not counted as a check."""


# Refusals that do not use up one of the checks; past this they do, so a model that keeps
# asking for the same thing still reaches the end.
MAX_FREE_REFUSALS = 2


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
    # A change to what the ticket already is re-runs the same report and wastes a call:
    # live, the agent spent one of its five checks re-running "to the next open" on an
    # overnight ticket. Say so, so it picks something that can tell it something new.
    t = report.get("ticket") or {}
    # A weekend ticket is stored as an hours hold with a weekend label.
    weekend_now = "weekend" in str(((t.get("extra") or {}) if isinstance(t.get("extra"), dict) else {}).get("horizon_label") or "")
    side_eq = change.side is not None and change.side == t.get("side")
    # Hours only matter for an "hours" hold: "next_open, 6 h" is still the next-open hold.
    hold_eq = change.horizon_kind is not None and (
        (change.horizon_kind == "through_weekend" and weekend_now)
        or (change.horizon_kind == t.get("horizon_kind") and (change.horizon_kind != "hours" or change.horizon_hours in (None, t.get("horizon_hours")))))
    size_eq = change.notional_quote is not None and abs(change.notional_quote - float(t.get("notional_quote") or 0)) < 1
    lev_eq = change.leverage is not None and change.leverage == (t.get("leverage") or 1.0)
    same = ((change.side is None or side_eq) and (change.horizon_kind is None or hold_eq)
            and (change.notional_quote is None or size_eq) and (change.leverage is None or lev_eq) and not change.lenses)
    if same:
        equal = [name for name, hit in (("side", side_eq), ("hold", hold_eq), ("size", size_eq), ("leverage", lev_eq)) if hit]
        raise NoOpCall("that is the trade as it already stands" + (f" (the {', '.join(equal)} you gave equal the ticket's)" if equal else "")
                       + "; change something that is different from the ticket")
    with state.lock:
        payload = analyze(state.ctx, change.apply_to(base, entry=((report.get("snapshot") or {}).get("prices") or {}).get("spot_close")), as_of=whatif.as_of_of(report), record=False).to_dict()
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
        bit = f"{x['label']}: {_word(x['verdict'])} at {_usd(x['size'])} USDT"
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


BITGET_TIMEOUT_S = 6.0  # the longest the chat waits for one cold entry; the cache answers the rest instantly
BITGET_RESULT_CHARS = 700


def tool_bitget_data(state: Any, report: dict[str, Any], args: dict[str, Any]) -> str:  # noqa: ANN401
    """One allow-listed Bitget catalogue entry for a ticker, as one plain sentence.

    Cache first. A cold entry is fetched once, with a timeout, through the same refresher the
    background uses - so the one-call-per-entry-per-hour limit holds here too - and a slow or
    failing service is reported as such, never waited on."""
    entry = str(args.get("entry") or "")
    if entry not in bitget_data.ALLOWED:
        raise ValueError(f"entry must be one of {', '.join(bitget_data.ALLOWED)}")
    ticker = str(args.get("ticker") or (report.get("ticket") or {}).get("ticker") or "").upper()
    ctx = state.ctx
    if not ticker or ticker not in ctx.tickers_with_data():
        raise ValueError(f"'{ticker}' is not a ticker the desk covers")
    if entry in bitget_data.STREET_ENTRIES:
        data = bitget_data.street_entry_data(entry, ctx.street_for(ticker, fetch=False))
        text = bitget_data.describe_street(entry, data) if data else ""
    else:
        bd = ctx.bitget_data
        if bd is None:
            raise ValueError("Bitget data is switched off on this desk")
        cell = bd.get(ticker, entry)
        if cell is None and bd.due(ticker, entry, utc_now()):
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                pool.submit(bd.refresh, ticker, entry).result(timeout=BITGET_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - slow or failing: say so below
                log.info("bitget_data %s %s did not answer in time", entry, ticker)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            cell = bd.get(ticker, entry)
        text = bitget_data.describe(entry, cell.data) if cell and cell.data else ""
    if not text:
        raise ValueError(f"Bitget has no {entry} data for {ticker} right now (not delivered yet, no coverage, or the service is not answering)")
    return text[:BITGET_RESULT_CHARS]


TOOLS: dict[str, Callable[[Any, dict[str, Any], dict[str, Any]], str]] = {
    "rerun": tool_rerun, "base_rate": tool_base_rate, "safest_ways": tool_safest_ways, "explain": tool_explain, "bitget_data": tool_bitget_data,
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


def _words(text: str) -> str:
    """Verdict codes as words: NO_GO -> NO GO, REDUCE_TO -> REDUCE TO."""
    return text.replace("NO_GO", "NO GO").replace("REDUCE_TO", "REDUCE TO")


def _final(obj: dict[str, Any], report: dict[str, Any], sheet: str, lang: str) -> tuple[dict[str, Any], int]:
    removed = 0
    summary, n, _ = analyst.verify_tagged(analyst._as_text(obj.get("summary")), sheet)  # noqa: SLF001
    summary = _words(summary)
    removed += n
    findings = []
    raw = obj.get("findings")
    for item in (raw if isinstance(raw, list) else [raw])[:4]:
        clean, n, _ = analyst.verify_tagged(analyst._as_text(item), sheet)  # noqa: SLF001
        removed += n
        if clean:
            findings.append(_words(clean))
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
    free_refusals = 0
    try:
        while True:
            calls = sum(1 for x in run.steps if not x.get("refused"))
            wrap_up = calls >= max_calls or time.time() - t0 > budget_s
            user = f"{TOOLS_DOC}\nFACT SHEET\n\n{sheet}\n"
            if transcript:
                user += ("\nTOOL CALLS SO FAR (each with the thought you gave; do not repeat a check or reuse a thought)\n"
                         + "\n".join(transcript) + "\n")
            user += ("\nNo more tool calls are allowed. Reply with the final JSON now.\n" if wrap_up
                     else f"\nYou have {max_calls - calls} tool call(s) left. Reply with one JSON object.\n")
            left = HARD_STOP_S - (time.time() - t0)
            if left <= 3:
                raise TimeoutError("out of time")
            raw = _within(lambda u=user: provider.write(system=system, user=u, max_tokens=MAX_TOKENS), min(MODEL_TIMEOUT_S, left))
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
            refused = False
            if name not in TOOLS:
                text, ok = f"unknown tool '{name}'; use one of {', '.join(TOOLS)}", False
            else:
                try:
                    text, ok = _within(lambda fn=TOOLS[name], a=args: fn(state, report, a), min(TOOL_TIMEOUT_S, max(5.0, HARD_STOP_S - 10 - (time.time() - t0)))), True
                except NoOpCall as exc:
                    text, ok = f"error: {exc}", False
                    if free_refusals < MAX_FREE_REFUSALS:
                        free_refusals += 1
                        refused = True
                except Exception as exc:  # noqa: BLE001 - a bad call is a result the model can read
                    log.info("agent tool %s failed: %s", name, exc)
                    text, ok = f"error: {exc}", False
            thought, nrm = analyst.strip_unverified(analyst._as_text(obj.get("thought")), checked)  # noqa: SLF001
            run.removed += nrm
            if ok:
                results.append(f"[{SECTION[name]}] {_compact(text)}")
                transcript.append(f"{len(run.steps) + 1}. [thought: {thought}] {name} {json.dumps(args, ensure_ascii=False)} ->\n{results[-1]}")
            else:
                transcript.append(f"{len(run.steps) + 1}. {name} {json.dumps(args, ensure_ascii=False)} -> {text}")
            run.steps.append({"n": len(run.steps) + 1, "thought": thought, "tool": name, "args": args,
                              "result_summary": _compact(text, 400), "seconds": round(time.time() - ts, 1),
                              **({"refused": True} if refused else {})})
    except Exception as exc:  # noqa: BLE001 - a failed agent keeps the steps it completed
        log.exception("stress-test agent failed")
        if run.steps and (isinstance(exc, TimeoutError) or time.time() - t0 > budget_s):
            # Out of time with checks done: answer with those rather than with an error.
            run.final, run.status = partial_final(run, report, lang), "done"
        else:
            run.status, run.error = "failed", str(exc)[:200]
    return run


class AgentJobs:
    """Agent runs in the background, one per report and language."""

    def __init__(self, max_workers: int = 2, keep: int = 300):
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
