"""The analyst's take: the model reads the finished report and says what matters.

Everything else on the desk is computed. This is the one place the model is asked to
think in public - to read a report the way a senior desk analyst would and say, in
plain words, what the call is, what matters most tonight, what would change its mind and
what to watch. That is the job a language model is actually good at, and the one a
trader cannot get from a table.

Two constraints make it safe to show:

* **It cannot introduce a number.** It is given a fact sheet built from the report's own
  fields, told to quote only those, and checked afterwards: any sentence carrying a
  figure that is not on the sheet is removed before the take is shown, and the page says
  how many were removed. The verdict and the size stay the engine's.
* **Nobody waits for it.** Qwen takes 30-90 s to write, measured. The desk answers at
  once from its own fields and the take is written in the background; the page shows it
  when it arrives.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)

SYSTEM_EN = (
    "You are the senior analyst on a trading desk for tokenized US stocks that trade 24/7 while the real stock "
    "market is shut. You are given a FACT SHEET the desk computed for one proposed trade. Write the analyst's take "
    "a trader reads before deciding, in four short parts with these exact headings on their own lines:\n"
    "The call\nWhat matters most tonight\nWhat would change my mind\nWhat I'd watch\n"
    "Do not list the facts back - the trader can read the sheet. Your job is judgement: connect them. Which risk "
    "actually dominates this trade and why; whether the stop, the trader's own invalidation and the bad-night loss "
    "agree or contradict each other; whether the street and the market mood support or cut against the position; "
    "and where the evidence is too thin to lean on. Plain language, no jargon (say 'a bad night, one in twenty' rather "
    "than 'p5'). Two or three short sentences or bullets per part, 170 words at most. Quote only numbers that appear "
    "on the fact sheet, exactly as written; never compute, round differently or estimate a new one. Do not change the "
    "desk's verdict or size. Never tell the trader what to do; they decide."
)
SYSTEM_ZH = SYSTEM_EN.replace(
    "four short parts with these exact headings on their own lines:\nThe call\nWhat matters most tonight\nWhat would change my mind\nWhat I'd watch\n",
    "four short parts with these exact Chinese headings on their own lines:\n结论\n今晚最重要的\n什么会改变我的看法\n我会盯着什么\n",
) + " Write the whole take in Simplified Chinese."

_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?。！？])\s+|\n")


def _pct(v: Any, d: int = 1) -> str:  # noqa: ANN401
    return "n/a" if v is None else f"{v:+.{d}f}%"


def fact_sheet(r: dict[str, Any]) -> str:
    """The report's decision-relevant facts, compact enough to keep the model quick."""
    t = r.get("ticket") or {}
    v = r.get("verdict") or {}
    a = r.get("analog") or {}
    ph = r.get("primary_horizon")
    h = (a.get("horizons") or {}).get(ph) or {}
    c = h.get("cohort") or {}
    p5 = h.get("p5_adjusted") if h.get("p5_adjusted") is not None else c.get("p5")
    lines = [
        f"Trade: {t.get('side')} {t.get('notional_quote'):,.0f} USDT of {t.get('ticker')}, held {r.get('horizon_h', 0):.0f} hours.",
        f"Desk verdict: {v.get('verdict')}; size the desk allows: {v.get('recommended_notional') or 0:,.0f} USDT; "
        f"binding cap: {(r.get('sizing') or {}).get('binding_cap') or 'none'}.",
    ]
    if c.get("n"):
        lens = (a.get("lens") or {})
        narrowed = f" (compared only against {lens.get('description')})" if lens.get("applied") and lens.get("description") else ""
        lines.append(
            f"History{narrowed}: {c['n']} similar past moments; typical outcome {_pct(c.get('median_pct'))}; "
            f"a bad night, one in twenty, worse than {_pct(p5)}; ended up {c.get('win_rate', 0) * 100:.0f}% of the time."
        )
    paths = a.get("paths") or {}
    if t.get("stop_price") and paths.get("stop_pct") is not None:
        lines.append(f"Stop at {t['stop_price']:.2f}, {abs(paths['stop_pct']):.1f}% away; {paths.get('stopped')} of {len(paths.get('paths') or [])} past moments hit it.")
    plan = r.get("plan_check") or {}
    if plan.get("distance_pct") is not None and plan.get("kind") in ("level", "moving_average", "move"):
        lines.append(f"Trader's own invalidation '{plan.get('invalidation')}' is {abs(plan['distance_pct']):.1f}% away"
                     + (f"; {plan['crossed']} of {plan['of']} past moments crossed it." if plan.get("crossed") is not None else "."))
    if plan.get("thesis_mismatch"):
        lines.append(f"Warning: {plan['thesis_mismatch']}.")
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pnl_quote") is not None]
    if rows:
        p, i = min(rows, key=lambda x: x[1]["total_pnl_quote"])
        lines.append(f"Worst stress test: {p['name']}, {_pct(i.get('total_pct_of_notional'))} of the position, {i['total_pnl_quote']:,.0f} USDT.")
    if (st.get("inputs_summary") or {}).get("earnings_in_window") is False:
        lines.append("No earnings report falls inside this hold.")
    q = (r.get("execution") or {}).get("exit_quote") or {}
    if q.get("total_cost_bps") is not None:
        lines.append(f"Getting out costs {q['total_cost_bps']:.0f} bps on the order book.")
    s = r.get("street") or {}
    if s:
        if s.get("token_vs_live_bps") is not None:
            lines.append(f"The token trades {s['token_vs_live_bps']:+.0f} bps from the real stock's live price.")
        if s.get("n_firms"):
            lines.append(f"Analysts, last 90 days: {s['bullish']} buy, {s['neutral']} hold, {s['bearish']} sell; median target {s.get('median_target') or 0:,.0f}.")
        if s.get("insider_sells") or s.get("insider_buys"):
            lines.append(f"Insiders, last 90 days: {s.get('insider_sells', 0)} sales, {s.get('insider_buys', 0)} purchases.")
        if s.get("mood_score") is not None:
            lines.append(f"Market fear and greed: {s['mood_score']:.0f} ({s.get('mood_rating')}).")
    for f in (r.get("filings") or [])[:2]:
        lines.append(f"Fresh filing: {f.get('headline')} ({f.get('market_moving')} impact).")
    for w in (r.get("warnings") or [])[:3]:
        lines.append(f"Caveat: {w}.")
    return "\n".join(lines)


def strip_unverified(text: str, sheet: str) -> tuple[str, int]:
    """Drop every sentence carrying a number the fact sheet does not contain."""
    allowed = {x.replace(",", "").lstrip("+-") for x in _NUM.findall(sheet)}
    kept, removed = [], 0
    for line in text.splitlines():
        parts = [p for p in _SENTENCE.split(line) if p is not None]
        good = []
        for p in parts:
            nums = [x.replace(",", "").lstrip("+-") for x in _NUM.findall(p)]
            # Small integers are headings, counts of bullets and the like.
            if any(n not in allowed and not (n.isdigit() and int(n) <= 5) for n in nums):
                removed += 1
                continue
            good.append(p)
        kept.append(" ".join(good).rstrip())
    return "\n".join(kept).strip(), removed


@dataclass
class Take:
    status: str  # "pending" | "done" | "failed" | "unavailable"
    text: str = ""
    removed: int = 0
    model: str = ""
    seconds: float = 0.0
    lang: str = "en"
    started: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("started", None)
        return d


def write(provider: Any, report: dict[str, Any], lang: str = "en") -> Take:  # noqa: ANN401
    """One take, written now. Blocking; the job runner calls it off the request path."""
    sheet = fact_sheet(report)
    t0 = time.time()
    text = provider.write(system=SYSTEM_ZH if lang == "zh" else SYSTEM_EN, user=f"FACT SHEET\n\n{sheet}", max_tokens=2500)
    if not text:
        return Take(status="failed", lang=lang, seconds=time.time() - t0)
    clean, removed = strip_unverified(text, sheet)
    return Take(status="done", text=clean, removed=removed, model=getattr(provider, "model", ""), seconds=round(time.time() - t0, 1), lang=lang)


class AnalystJobs:
    """Takes being written in the background, one per report and language."""

    def __init__(self, max_workers: int = 2, keep: int = 300):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analyst")
        self._takes: dict[tuple[int, str], Take] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def get(self, forecast_id: int, lang: str = "en") -> Take | None:
        return self._takes.get((forecast_id, lang))

    def start(self, forecast_id: int, report: dict[str, Any], provider: Any, lang: str = "en") -> Take:  # noqa: ANN401
        key = (forecast_id, lang)
        with self._lock:
            existing = self._takes.get(key)
            if existing and (existing.status in ("pending", "done") or time.time() - existing.started < 60):
                return existing
            if provider is None:
                take = Take(status="unavailable", lang=lang)
                self._takes[key] = take
                return take
            take = Take(status="pending", lang=lang)
            self._takes[key] = take
            while len(self._takes) > self._keep:
                self._takes.pop(next(iter(self._takes)))

        def run() -> None:
            try:
                done = write(provider, report, lang)
            except Exception:  # noqa: BLE001 - a take that fails must not take anything else down
                log.exception("analyst take for %s failed", forecast_id)
                done = Take(status="failed", lang=lang)
            with self._lock:
                self._takes[key] = done

        self._pool.submit(run)
        return take
