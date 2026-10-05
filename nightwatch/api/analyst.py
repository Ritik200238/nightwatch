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

import json
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from nightwatch.features.phrases import earnings_ahead

log = logging.getLogger(__name__)

SECTION_IDS = ("desk", "checks", "market", "leverage", "failure mode", "premise", "history", "stop", "plan", "stress", "order book", "street", "bitget", "filing", "caveat", "relations")

_HEADINGS_EN = "The call\nWhat matters most tonight\nWhat would change my mind\nWhat I'd watch\n"
_HEADINGS_ZH = "结论\n今晚最重要的\n什么会改变我的看法\n我会盯着什么\n"

SYSTEM_EN = (
    "You are the senior analyst on a trading desk for tokenized US stocks that trade 24/7 while the real stock "
    "market is shut. You are given a FACT SHEET the desk computed for one proposed trade; every line starts with a "
    "[section] id. Answer with ONE JSON object and nothing else, with exactly these keys:\n"
    '"for": the case for the trade, at most 2 sentences.\n'
    '"against": the case against the trade, at most 2 sentences.\n'
    '"reconcile": one sentence that restates the desk\'s verdict and the size the desk allows exactly as the sheet gives them.\n'
    '"take": the analyst\'s take as plain text, four short parts with these exact headings on their own lines '
    "(use \\n for line breaks):\n" + _HEADINGS_EN +
    "Do not list the facts back - the trader can read the sheet. Your job is judgement: connect them. Which risk "
    "actually dominates this trade and why; whether the stop, the trader's own invalidation and the bad-night loss "
    "agree or contradict each other; whether the street and the market mood support or cut against the position; "
    "and where the evidence is too thin to lean on. Plain language, no jargon (say 'a bad night, one in twenty' rather "
    "than 'p5'). Two or three short sentences or bullets per part; the take is 170 words at most.\n"
    "CITATIONS: quote only numbers that appear on the fact sheet, exactly as written; never compute, round differently or "
    "estimate a new one. Directly after EVERY number you write, in all four keys, put the [section] id of the sheet line it "
    "came from, for example: -2.7% [history], 12 bps [order book], $330 target [street]. A number without its tag, or with "
    "a tag from a section that does not contain it, will be deleted along with its sentence.\n"
    "CALIBRATION: never claim more than the evidence shows. Do not predict direction (no 'will rise', 'will fall', "
    "'likely to gain'). Say 'coin flip' or 'no clear edge' only if the sheet's edge check says the history shows no edge over "
    "random hours, and then say it neutrally (for example 'history shows no clear edge over random hours'), never "
    "dismissively. When you quote how often a past moment went the position's way, quote the typical outcome next to it, "
    "because a win rate alone can mislead. Where the sample is small or the edge check is weak, say the evidence is thin. "
    "Under 'What would change my mind' write exactly one sentence naming a concrete condition that could really happen and "
    "would really change the verdict or the size: a number on the sheet moving past a level other than zero, or a missing input "
    "(account size, a stop, an invalidation level) being supplied. Never use a threshold of zero.\n"
    "PLAIN WORDS: write for a trader who has not read the desk's papers. Do not use unexplained jargon such as 'liquidity gap', "
    "'basis', 'tail', 'drawdown' or 'p5'. Name the main risk as the item on the sheet's [failure mode] line, which is the "
    "largest loss, not a different one. Where the sheet says 'about flat', write 'about flat'; never write '-0.0%' or '+0.0%'. "
    "Where the sheet says no account size was given, say 'no account size was given'; never write 'unstated equity' or make a "
    "condition depend on an account size you were not given. Never write a [section] tag anywhere except directly after a number.\n"
    "Do not change the desk's verdict or size; 'reconcile' must restate them. Where the sheet lists computed relations, "
    "use them as given and do not infer your own comparisons between numbers. Never tell the trader what to do; they decide."
)
SYSTEM_ZH = SYSTEM_EN.replace(_HEADINGS_EN, _HEADINGS_ZH).replace("these exact headings", "these exact Chinese headings") + (
    " Write for, against, reconcile and take in Simplified Chinese, but keep the [section] ids and the verdict word "
    "exactly as the sheet gives it. EVERY sentence must be Chinese: translate scenario, crisis and failure-mode names (the sheet "
    "gives Chinese names where they exist) and never copy English phrases from the sheet. Only the [section] ids, ticker symbols, "
    "units such as USDT and bps, and the verdict word may stay in English. Write amounts in plain digits (20000, not 2万) and "
    "percentages with the % sign, exactly as on the sheet."
)
_RETRY_ZH = "\n\nThe previous answer was not written in Chinese. Write every sentence of every key in Simplified Chinese this time."
_RETRY_NUMBERS = "\n\nThe previous answer had several sentences deleted for numbers that were not on the sheet or had no [section] tag. Quote only numbers that are on the sheet, each directly followed by its [section] id."
# One call, thinking off: measured 2026-09-25 at 6.5-7.5 s for a take with the old prose-only
# prompt. Enough room for the JSON and its tags, not for the model to ramble.
MAX_TOKENS = 1100

_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
# Chinese sentences end in 。！？ with no space after them, so split there as well; a Chinese
# paragraph used to count as one sentence, and one bad number deleted all of it.
_SENTENCE = re.compile(r"(?<=[.!?])\s+|(?<=[。！？；])|\n")


def _pct(v: Any, d: int = 1) -> str:  # noqa: ANN401
    """A signed percent; a value that rounds to zero is "about flat", never "-0.0%"."""
    if v is None:
        return "n/a"
    return "about flat" if round(v, d) == 0 else f"{v:+.{d}f}%"


def _loss_p5(h: dict[str, Any]) -> float | None:
    """The position's one-in-twenty loss: the token's upper tail turned over for a short."""
    if "loss_p5_pct" in h:
        return h["loss_p5_pct"]
    c = h.get("cohort") or {}
    return h.get("p5_adjusted") if h.get("p5_adjusted") is not None else c.get("p5")


def fact_sheet(r: dict[str, Any], lang: str = "en") -> str:
    """The report's decision-relevant facts, compact enough to keep the model quick.

    For ``zh`` the scenario and failure-mode names are the report's Chinese ones, so the model has
    no English phrase to copy into a Chinese take.
    """
    zh = lang == "zh"
    t = r.get("ticket") or {}
    v = r.get("verdict") or {}
    a = r.get("analog") or {}
    ph = r.get("primary_horizon")
    h = (a.get("horizons") or {}).get(ph) or {}
    c = h.get("cohort") or {}
    p5 = _loss_p5(h)
    lines = [
        f"[desk] Trade: {t.get('side')} {t.get('notional_quote'):,.0f} USDT of {t.get('ticker')}, held {r.get('horizon_h', 0):.0f} hours.",
        f"[desk] Desk verdict: {v.get('verdict')}; size the desk allows: {v.get('recommended_notional') or 0:,.0f} USDT; "
        f"binding cap: {(r.get('sizing') or {}).get('binding_cap') or 'none'}.",
    ]
    if not t.get("account_equity_quote"):
        lines.append("[desk] No account size was given, so the size limits that depend on it were not checked.")
    # The actual reasons, so the take cannot guess one. On a live test it wrote "REVIEW
    # because the regime cap binds, meaning conditions are fragile" when the regime was
    # favourable and the review was for a missing account size.
    failed = [x for x in ((r.get("gate") or {}).get("rules") or []) if x.get("decision") != "GO"]
    if failed:
        lines.append("[checks] Checks that did not pass: " + "; ".join(f"{x['rule'].replace('_', ' ')} ({x['decision'].replace('_', ' ')}): {x['reason']}" for x in failed) + ".")
    else:
        lines.append("[checks] Every gate check passed.")
    caps = {cp["name"]: cp for cp in ((r.get("sizing") or {}).get("caps") or [])}
    bcap = caps.get((r.get("sizing") or {}).get("binding_cap") or "")
    if bcap and bcap.get("detail"):
        lines.append(f"[checks] The binding cap, {bcap['name'].replace('_', ' ')}, says: {bcap['detail']}.")
    labels = ((r.get("snapshot") or {}).get("labels") or {})
    feats = ((r.get("snapshot") or {}).get("features") or {})
    if labels.get("regime_label"):
        mult = feats.get("risk_multiplier")
        lines.append(f"[market] Market state: {labels['regime_label']}" + (f", size multiplier {mult:.2f}" if isinstance(mult, int | float) else "") + ".")
    lev = r.get("leverage") or {}
    if lev.get("liquidation_distance_pct") is not None:
        lines.append(f"[leverage] Leverage {lev['leverage']:g}x: liquidated about {lev['liquidation_distance_pct']:.1f}% away"
                     + (f"; {lev['analog_hits']} of {lev['analog_of']} past moments reached it" if lev.get("analog_of") else "") + ".")
    modes = [m for m in (r.get("failure_modes") or []) if m.get("loss_quote") is not None]
    if modes:
        # The largest loss, whatever order the report stored them in.
        w = min(modes, key=lambda m: m["loss_quote"])
        title = (w.get("title_zh") if zh else None) or w["title"]
        lines.append(f"[failure mode] Largest way it loses: {title} ({w['mechanism']}), about {w['loss_quote']:,.0f} USDT; {w['likelihood']}.")
    for pm in r.get("premise") or []:
        lines.append(f"[premise] Premise check: {pm}")
    if c.get("n"):
        lens = (a.get("lens") or {})
        narrowed = f" (compared only against {lens.get('description')})" if lens.get("applied") and lens.get("description") else ""
        lines.append(
            f"[history] History{narrowed}: {c['n']} similar past moments; typical outcome for this position {_pct(h.get('pnl_median_pct', c.get('median_pct')))}; "
            f"a bad night, one in twenty, worse than {_pct(p5)}; went this position's way {(h.get('pnl_win_rate', c.get('win_rate')) or 0) * 100:.0f}% of the time."
        )
    base = h.get("baseline") or {}
    if c.get("n") and base.get("permutation_p_value") is not None:
        pv = base["permutation_p_value"]
        verdict_edge = "no clear edge over random hours" if pv > EDGE_P else "the history differs from random hours"
        lines.append(f"[history] Edge check against random hours of the same kind: p = {pv:.2f}, so {verdict_edge}.")
    if c.get("n") and c["n"] < THIN_N:
        lines.append(f"[history] Only {c['n']} similar past moments: a thin sample.")
    paths = a.get("paths") or {}
    if t.get("stop_price") and paths.get("stop_pct") is not None:
        lines.append(f"[stop] Stop at {t['stop_price']:.2f}, {abs(paths['stop_pct']):.1f}% away; {paths.get('stopped')} of {len(paths.get('paths') or [])} past moments hit it.")
    plan = r.get("plan_check") or {}
    if plan.get("distance_pct") is not None and plan.get("kind") in ("level", "moving_average", "move"):
        lines.append(f"[plan] Trader's own invalidation '{plan.get('invalidation')}' is {abs(plan['distance_pct']):.1f}% away"
                     + (f"; {plan['crossed']} of {plan['of']} past moments crossed it." if plan.get("crossed") is not None else "."))
    if plan.get("thesis_mismatch"):
        lines.append(f"[plan] Warning: {plan['thesis_mismatch']}.")
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pnl_quote") is not None]
    if rows:
        p, i = min(rows, key=lambda x: x[1]["total_pnl_quote"])
        lines.append(f"[stress] Worst stress test: {(p.get('name_zh') if zh else None) or p['name']}, {_pct(i.get('total_pct_of_notional'))} of the position, {i['total_pnl_quote']:,.0f} USDT.")
    if (st.get("inputs_summary") or {}).get("earnings_in_window") is False:
        lines.append("[stress] No earnings report falls inside this hold.")
    lines.append(f"[calendar] Next earnings: {earnings_ahead(feats.get('hours_to_earnings'))}. Never quote this as a number of hours when it says no earnings in 30 days.")
    q = (r.get("execution") or {}).get("exit_quote") or {}
    if q.get("total_cost_bps") is not None:
        lines.append(f"[order book] Getting out costs {q['total_cost_bps']:.0f} bps on the order book.")
    s = r.get("street") or {}
    if s:
        if s.get("token_vs_live_bps") is not None:
            lines.append(f"[street] The token trades {s['token_vs_live_bps']:+.0f} bps from the real stock's live price.")
        if s.get("n_firms"):
            lines.append(f"[street] Analysts, last 90 days: {s['bullish']} buy, {s['neutral']} hold, {s['bearish']} sell; median target {s.get('median_target') or 0:,.0f}.")
        if s.get("insider_sells") or s.get("insider_buys"):
            sells, buys = s.get("insider_sells", 0), s.get("insider_buys", 0)
            lines.append(f"[street] Insiders, last 90 days: {sells} sale{'' if sells == 1 else 's'}, {buys} purchase{'' if buys == 1 else 's'}.")
        if s.get("mood_score") is not None:
            lines.append(f"[street] Market fear and greed: {s['mood_score']:.0f} ({s.get('mood_rating')}).")
    b = r.get("bitget") or {}
    for eid in ("equity_calendar", "equity_fundamental_ratios", "equity_fundamental_dividends", "equity_estimates_consensus"):
        text = ((b.get("entries") or {}).get(eid) or {}).get("text")
        if text:
            lines.append(f"[bitget] {text}")
    chk = b.get("earnings_check") or {}
    if chk.get("status") == "differ":
        lines.append(f"[bitget] Bitget and Nasdaq disagree on the next earnings date: {chk['bitget']} against {chk['nasdaq']}.")
    elif chk.get("status") == "agree":
        lines.append("[bitget] Bitget's and Nasdaq's earnings calendars give the same next report date.")
    for f in (r.get("filings") or [])[:2]:
        if f.get("market_moving") == "unread":
            lines.append(f"[filing] Fresh filing: a {f.get('form')} landed {f.get('hours_ago', 0):.0f}h ago; the model has not read it yet, so its impact is unknown.")
        else:
            lines.append(f"[filing] Fresh filing: {f.get('headline')} ({f.get('market_moving')} impact).")
    for w in (r.get("warnings") or [])[:3]:
        lines.append(f"[caveat] Caveat: {w}.")
    rel = relations(r, lang)
    if rel:
        lines.append("[relations] Computed relations (use these; do not work out your own comparisons):")
        lines += [f"[relations] {x}" for x in rel]
    return "\n".join(lines)


EDGE_P = 0.10  # above this the history is not distinguishable from random hours
THIN_N = 30  # fewer similar moments than this is a thin sample
SAME_LEVEL_PCT = 0.25  # stop and invalidation closer than this are one level


def relations(r: dict[str, Any], lang: str = "en") -> list[str]:
    """Comparisons between the report's own numbers, worked out here rather than by the model.

    On a live test the model read "7 of 40 crossed the invalidation at 360, 4 of 40 hit
    the stop at 350" as "once 360 breaks, price runs to 350" - backwards: 3 of those 7
    turned back in between. The figures were right and the inference was not. So every
    comparison the take is likely to lean on is computed and stated, and the model is
    told to use these rather than draw its own.
    """
    out: list[str] = []
    t = r.get("ticket") or {}
    a = r.get("analog") or {}
    h = (a.get("horizons") or {}).get(r.get("primary_horizon")) or {}
    c = h.get("cohort") or {}
    p5 = _loss_p5(h)
    paths = a.get("paths") or {}
    n = len(paths.get("paths") or [])
    stop_pct = paths.get("stop_pct") if t.get("stop_price") else None
    stopped = paths.get("stopped")
    plan = r.get("plan_check") or {}
    inv_pct = plan.get("distance_pct") if plan.get("kind") in ("level", "moving_average", "move") and not plan.get("already") else None
    crossed = plan.get("crossed")

    if stop_pct is not None and inv_pct is not None and stopped is not None and crossed is not None and n:
        if abs(abs(inv_pct) - abs(stop_pct)) < SAME_LEVEL_PCT:
            # A take once said both "they sit at the same distance" and "the stop is closer".
            out.append("The stop and the invalidation sit at essentially the same level, so crossing one is hitting the other.")
        elif abs(inv_pct) < abs(stop_pct):
            back = crossed - stopped
            out.append(
                "The invalidation is closer than the stop, so every past moment that hit the stop crossed the invalidation first: "
                f"of the {crossed} that crossed the invalidation, {stopped} went on to the stop and {back} turned back before it."
            )
        elif abs(inv_pct) > abs(stop_pct):
            out.append("The stop is closer than the invalidation, so the stop would take the trade out before the invalidation is ever tested.")
    if p5 is not None:
        for name, dist in (("stop", stop_pct), ("invalidation", inv_pct)):
            if dist is None:
                continue
            gap = abs(p5) - abs(dist)
            if abs(gap) < 0.5:
                out.append(f"The bad night (one in twenty) lands at about the same distance as the {name}.")
            elif gap > 0:
                out.append(f"The bad night (one in twenty) goes beyond the {name}.")
            else:
                out.append(f"The bad night (one in twenty) stops short of the {name}.")
    st = r.get("stress") or {}
    rows = [(p, i) for p, i in zip(st.get("presets") or [], st.get("impacts") or [], strict=False) if i.get("total_pct_of_notional") is not None]
    if rows and stop_pct is not None:
        p, i = min(rows, key=lambda x: x[1]["total_pct_of_notional"])
        if abs(i["total_pct_of_notional"]) > abs(stop_pct):
            out.append(f"The worst stress test ({(p.get('name_zh') if lang == 'zh' else None) or p['name']}) moves further than the stop: a gap while the market is shut could jump past the stop rather than fill at it.")
    s = r.get("street") or {}
    live = s.get("token_vs_live_bps")
    if live is not None:
        if abs(live) < 10:
            out.append("The token trades close to the real stock's live price.")
        else:
            out.append(f"The token trades {'above' if live > 0 else 'below'} the real stock's live price, so if the two converge a long {'loses' if live > 0 else 'gains'} that gap.")
    if c.get("win_rate") is not None:
        wr = c["win_rate"]
        if wr > 0.55:
            out.append("Past moments like this ended up more often than not.")
        elif wr < 0.45:
            out.append("Past moments like this ended down more often than not.")
        else:
            out.append("Past moments like this were split close to evenly on direction.")
    return out


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


_SHEET_LINE = re.compile(r"^\[([a-z ]+)\]\s")
# A tag must sit right behind its number: "12 bps [order book]", "$330 target [street]".
# The tag may be a Chinese name for the section ("[历史]"): the model was told to keep the id and
# sometimes translates it, so those are mapped back rather than failing a correct number.
_TAG_AFTER = re.compile(r"^[^\d\[\]\n]{0,14}?\[([A-Za-z 一-鿿]{1,12})\]")
_UNIT_AFTER = re.compile(r"^\s*(?:%|bps|x\b|usdt\b|h\b|美元|基点|个基点|小时|倍|个百分点|个点)", re.I)
_MAGNITUDE = re.compile(r"^\s*(万|千|亿)")
_MAG = {"万": 10_000, "千": 1_000, "亿": 100_000_000}
_TAG_ALIAS = {
    "交易台": "desk", "检查": "checks", "市场": "market", "杠杆": "leverage", "失效模式": "failure mode", "故障模式": "failure mode",
    "亏损方式": "failure mode", "前提": "premise", "历史": "history", "止损": "stop", "计划": "plan", "压力": "stress", "压力测试": "stress",
    "订单簿": "order book", "盘口": "order book", "市场观点": "street", "华尔街": "street", "文件": "filing", "公告": "filing",
    "提示": "caveat", "bitget数据": "bitget", "注意": "caveat", "关系": "relations", "日历": "calendar",
}


def _normalise(text: str) -> str:
    """Full-width digits, percent signs and brackets become their ASCII forms, so a number written
    the Chinese way is checked the same way as one written the English way."""
    text = unicodedata.normalize("NFKC", text).replace("【", "[").replace("】", "]").replace("−", "-")
    return text


def _tag_id(raw: str) -> str:
    raw = raw.strip().lower()
    return _TAG_ALIAS.get(raw, raw)


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.6g}"


def sheet_sections(sheet: str) -> dict[str, set[str]]:
    """Which numbers each [section] of the fact sheet contains."""
    out: dict[str, set[str]] = {}
    for line in sheet.splitlines():
        m = _SHEET_LINE.match(line)
        if m:
            body = line[m.end():]
            out.setdefault(m.group(1), set()).update(x.replace(",", "").lstrip("+-") for x in _NUM.findall(body))
    return out


def verify_tagged(text: str, sheet: str) -> tuple[str, int, list[dict[str, str]]]:
    """Keep only sentences whose every number is on the sheet AND tagged with the section it came from.

    A number passes when it is directly followed by a ``[section]`` id, that section exists,
    and the number is in that section's lines. A bare integer of 5 or less with no unit is
    a heading or a count of bullets and passes untagged. Returns the cleaned text, how many
    sentences were removed, and the ``{number, source}`` pairs that survived.
    """
    sections = sheet_sections(sheet)
    kept, removed, cites = [], 0, []
    for line in _normalise(text).splitlines():
        good = []
        for sent in [x for x in _SENTENCE.split(line) if x]:
            found, ok = [], True
            for m in _NUM.finditer(sent):
                norm = m.group().replace(",", "").lstrip("+-")
                rest = sent[m.end():]
                mag = _MAGNITUDE.match(rest)
                if mag:
                    # "2万" is 20000: compare the value, not the digit.
                    norm = _fmt_num(float(norm) * _MAG[mag.group(1)])
                    rest = rest[mag.end():]
                tag = _TAG_AFTER.match(_UNIT_AFTER.sub("", rest, count=1) if _UNIT_AFTER.match(rest) else rest)
                if tag is None:
                    if not mag and norm.isdigit() and int(norm) <= 5 and not _UNIT_AFTER.match(rest):
                        continue
                    ok = False
                    break
                src = _tag_id(tag.group(1))
                if norm not in sections.get(src, ()):
                    ok = False
                    break
                unit = _UNIT_AFTER.match(rest)
                found.append({"number": m.group().replace(",", "") + (unit.group().strip() if unit and unit.group().strip() in ("%", "bps") else ""), "source": src})
            if not ok:
                removed += 1
                continue
            cites.extend(found)
            good.append(sent)
        kept.append(_join(good))
    seen, uniq = set(), []
    for c in cites:
        k = (c["number"], c["source"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return "\n".join(kept).strip(), removed, uniq


def _join(parts: list[str]) -> str:
    """Sentences back into a line: a space between English ones, none after Chinese full stops."""
    out = ""
    for p in parts:
        p = p.strip() if out else p
        out += (p if not out or out[-1] in "。！？；" else " " + p)
    return out.rstrip()


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_reply(raw: str) -> dict[str, Any] | None:
    """The model's JSON object, tolerating a code fence or chatter around it; None if it is not one."""
    text = raw.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    if not text.startswith("{") and "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _as_text(v: Any) -> str:  # noqa: ANN401
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _verdict_word(report: dict[str, Any]) -> str:
    return str((report.get("verdict") or {}).get("verdict") or "")


def _fixed_reconcile(report: dict[str, Any], lang: str) -> str:
    v = report.get("verdict") or {}
    size = f"{v.get('recommended_notional') or 0:,.0f}"
    if lang == "zh":
        return f"本台的结论不变：{_verdict_word(report)}，允许的规模 {size} USDT。"
    return f"The desk's verdict stands: {_verdict_word(report)}, up to {size} USDT."


_VERDICT_TOKEN = re.compile(r"(?<![A-Za-z])(NO[_ -]?GO|REVIEW(?:[_ ]REQUIRED)?|GO)(?![A-Za-z])")


def _norm_verdict(tok: str) -> str:
    tok = tok.upper()
    return "NO_GO" if tok.startswith("NO") else "REVIEW_REQUIRED" if tok.startswith("REVIEW") else "GO"


def _reconcile(model_line: str, report: dict[str, Any], sheet: str, lang: str) -> str:
    """The model's reconciling line if it restates the verdict and the size and cites cleanly; otherwise the desk's own words."""
    size = f"{(report.get('verdict') or {}).get('recommended_notional') or 0:,.0f}".replace(",", "")
    clean, removed, _ = verify_tagged(model_line, sheet)
    plain = re.sub(r"\s*\[[A-Za-z ]+\]", "", clean)
    said = {_norm_verdict(m) for m in _VERDICT_TOKEN.findall(plain)}
    sizes = {x.replace(",", "") for x in _NUM.findall(plain)}
    # Exactly the desk's verdict and exactly its size, nothing else claimed.
    if clean and not removed and said == {_norm_verdict(_verdict_word(report))} and sizes == {size}:
        return clean
    return _fixed_reconcile(report, lang)


# --------------------------------------------------------------------- reading polish
# The number check proves a figure is on the sheet. It cannot tell a sentence that is true but
# unreadable from one that helps, so these rules clean what a trader would trip over.

_TAG_ANY = re.compile(r"[ \t]*\[[A-Za-z\u4e00-\u9fff][A-Za-z \u4e00-\u9fff]*\]")
# A zero printed with a sign or a percent: "-0.0%", "+0.0%", "0.0%". Not "10%" or "0.05%".
_ZERO_PCT = re.compile(r"(?<![\d.])(?:[-+]0(?:\.0+)?|0\.0+)\s?%(?![\d.])")
# Sentences that were wrong in a live audit: a condition on an equity nobody gave, and a term the
# take never defines (and which named the wrong biggest loss).
_BAD_SENTENCE = re.compile(r"unstated|unknown equity|liquidity gap|exceed(?:s|ed)? your (?:equity|account)|流动性缺口|未说明的(?:权益|资金|账户)", re.I)
_HEADING_WORDS = {
    "en": ("the call", "what matters most tonight", "what would change my mind", "what i'd watch"),
    "zh": ("结论", "今晚最重要的", "什么会改变我的看法", "我会盯着什么"),
}
_MIND_NEEDS_SUBSTANCE = re.compile(r"\d|account|stop|invalidation|order book|exit|账户|止损|失效|盘口|平仓|仓位", re.I)


def _heading_index(line: str) -> int | None:
    bare = re.sub(r"^[#*\s]+|[*:：\s]+$", "", line).lower()
    for words in _HEADING_WORDS.values():
        if bare in words:
            return words.index(bare)
    return None


def mind_line(report: dict[str, Any], lang: str = "en") -> str:
    """A concrete 'what would change my mind', built from the report itself.

    Used when the model's sentence is missing, empty, tied to a threshold of zero or to an input
    nobody gave. Every condition here is one the engine actually acts on, and every figure is the
    report's own.
    """
    zh = lang == "zh"
    t = report.get("ticket") or {}
    v = report.get("verdict") or {}
    word = _verdict_word(report)
    bps = (((report.get("execution") or {}).get("exit_quote") or {}).get("total_cost_bps"))
    cap = str((report.get("sizing") or {}).get("binding_cap") or "")
    failed = [x for x in ((report.get("gate") or {}).get("rules") or []) if x.get("decision") != "GO"]
    if not t.get("account_equity_quote") and word != "GO":
        return ("如果给出账户规模，本台就能检查与之挂钩的仓位上限，目前的复核结论可能随之改变。" if zh
                else "If you give the desk your account size, it can check the size limits that depend on it, and the review could clear.")
    if bps is not None and ("exit" in cap or "liquidity" in cap) and (v.get("recommended_notional") or 0) < (t.get("notional_quote") or 0):
        return (f"如果盘口上的平仓成本低于 {bps:.0f} 个基点，本台允许的仓位会变大。" if zh
                else f"If getting out cost less than {bps:.0f} bps on the order book, the size the desk allows would go up.")
    if failed:
        rule = failed[0]["rule"].replace("_", " ")
        return (f"如果「{rule}」这项检查通过，当前的{word}结论可能上调。" if zh
                else f"If the {rule} check passed, the {word.replace('_', ' ')} verdict could improve.")
    if bps is not None:
        return (f"如果盘口上的平仓成本升到 {bps:.0f} 个基点以上，或上面任何一项检查不再通过，这个结论就需要重新评估。" if zh
                else f"If getting out cost more than {bps:.0f} bps on the order book, or any check above stopped passing, the verdict would need re-checking.")
    return ("如果上面任何一项检查的结果变化，这个结论就需要重新评估。" if zh
            else "If the result of any check above changed, the verdict would need re-checking.")


def _fix_mind(text: str, report: dict[str, Any], lang: str) -> str:
    """Make the 'what would change my mind' part a real condition: the model's if it is, the desk's if not."""
    lines = text.splitlines()
    idx = [(i, _heading_index(ln)) for i, ln in enumerate(lines)]
    start = next((i for i, h in idx if h == 2), None)
    if start is None:
        return text
    end = next((i for i, h in idx if h is not None and i > start), len(lines))
    body = " ".join(x.strip() for x in lines[start + 1:end] if x.strip())
    plain = _TAG_ANY.sub("", body)
    ok = bool(plain) and _MIND_NEEDS_SUBSTANCE.search(plain) and not _ZERO_PCT.search(plain) and not _BAD_SENTENCE.search(plain)
    if ok:
        return text
    return "\n".join(lines[:start + 1] + [mind_line(report, lang)] + lines[end:])


def polish(text: str, report: dict[str, Any], lang: str = "en") -> str:
    """Make a checked take readable: a real change-of-mind, no source tags, no signed zero, no known-bad sentences.

    Runs after the number check, so it never lets a number through that the check refused.
    """
    if not text:
        return text
    text = _fix_mind(text, report, lang)
    out = []
    for line in text.splitlines():
        kept = [p for p in _SENTENCE.split(line) if p and not _BAD_SENTENCE.search(p)]
        out.append(_join(kept) if kept else "")
    t = "\n".join(out)
    t = _TAG_ANY.sub("", t)
    t = _ZERO_PCT.sub("基本持平" if lang == "zh" else "about flat", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    # A heading left with nothing under it reads as a fault.
    lines = [ln for ln in t.splitlines()]
    cleaned = []
    for i, ln in enumerate(lines):
        if _heading_index(ln) is not None and ln.strip():
            nxt = next((x for x in lines[i + 1:] if x.strip()), "")
            if not nxt or _heading_index(nxt) is not None:
                continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def polish_line(text: str, lang: str = "en") -> str:
    """The same cleaning for a one-part text (the case for, the case against, the reconcile line)."""
    kept = [p for line in text.splitlines() for p in _SENTENCE.split(line) if p and not _BAD_SENTENCE.search(p)]
    t = _TAG_ANY.sub("", _join(kept))
    return re.sub(r"[ \t]{2,}", " ", _ZERO_PCT.sub("基本持平" if lang == "zh" else "about flat", t)).strip()


_ASCII_WORD = re.compile(r"[A-Za-z]{2,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_KEEP_ENGLISH = {"usdt", "bps", "go", "no", "review", "reduce", "hedge", "to", "otc"}


def mostly_english(text: str, tickers: tuple[str, ...] = ()) -> bool:
    """True when text meant to be Chinese is mostly English words (a model that copied the fact sheet)."""
    plain = _TAG_ANY.sub("", text or "")
    keep = _KEEP_ENGLISH | {x.lower() for x in tickers}
    english = sum(len(w) for w in _ASCII_WORD.findall(plain) if w.lower() not in keep)
    cjk = len(_CJK.findall(plain))
    if english + cjk < 20:
        return False
    return english > cjk * 1.5 if cjk else True


@dataclass
class Take:
    status: str  # "pending" | "done" | "failed" | "unavailable"
    text: str = ""
    removed: int = 0
    model: str = ""
    seconds: float = 0.0
    lang: str = "en"
    citations: list[dict[str, str]] = field(default_factory=list)
    case_for: str = ""
    case_against: str = ""
    reconcile: str = ""
    started: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("started", None)
        # The wire names are the ones the prompt uses; "for" is not a Python identifier.
        d["for"], d["against"] = d.pop("case_for"), d.pop("case_against")
        return d


# More deleted sentences than this and the take is written again; the cleaner of the two is kept.
REGENERATE_AT = 3


def _attempt(provider: Any, report: dict[str, Any], sheet: str, lang: str, extra: str = "") -> Take | None:  # noqa: ANN401
    """One model call, checked and polished. None when the model returned nothing."""
    t0 = time.time()
    raw = provider.write(system=SYSTEM_ZH if lang == "zh" else SYSTEM_EN, user=f"FACT SHEET\n\n{sheet}{extra}", max_tokens=MAX_TOKENS)
    if not raw:
        return None
    obj = parse_reply(raw)
    model = getattr(provider, "model", "")
    if obj is None:
        # Prose instead of JSON: still a take, checked the same way, with no debate.
        clean, removed, cites = verify_tagged(raw, sheet)
        return Take(status="done", text=polish(clean, report, lang), removed=removed, citations=cites, model=model, seconds=round(time.time() - t0, 1), lang=lang)
    removed, cites, parts = 0, [], {}
    for key in ("take", "for", "against"):
        clean, n, c = verify_tagged(_as_text(obj.get(key)).replace("\\n", "\n"), sheet)
        parts[key] = clean
        removed += n
        cites += c
    parts["take"] = polish(parts["take"], report, lang)
    parts["for"], parts["against"] = polish_line(parts["for"], lang), polish_line(parts["against"], lang)
    # A side the model could not argue with checked numbers is filled from the desk's own
    # second opinion - rules over the report's fields, so nothing in it needs checking - and
    # says so, rather than showing one side of a debate.
    for side, key in (("for", "supporting"), ("against", "against")):
        if not parts[side]:
            points = [c.get("text", "") for c in ((report.get("second_opinion") or {}).get(key) or []) if c.get("text")][:2]
            if points:
                parts[side] = " ".join(points) + (" （由规则根据报告生成）" if lang == "zh" else " (from the desk's own rules)")
    reconcile = polish_line(_reconcile(_as_text(obj.get("reconcile")), report, sheet, lang), lang) if (parts["for"] or parts["against"]) else ""
    seen: set[tuple[str, str]] = set()
    uniq = [c for c in cites if not ((c["number"], c["source"]) in seen or seen.add((c["number"], c["source"])))]
    return Take(status="done", text=parts["take"], removed=removed, citations=uniq, model=model, seconds=round(time.time() - t0, 1), lang=lang,
                case_for=parts["for"], case_against=parts["against"], reconcile=reconcile)


def _all_text(take: Take) -> str:
    return "\n".join((take.text, take.case_for, take.case_against))


def write(provider: Any, report: dict[str, Any], lang: str = "en") -> Take:  # noqa: ANN401
    """One take, written now. Blocking; the job runner calls it off the request path.

    A single model call returns the debate and the take together as JSON, so there is no
    second round trip. Every part goes through the same tag-and-number check. Two things
    send it back for a second try, at most one: a Chinese request answered mostly in English,
    and a take the number check cut to pieces. The cleaner try is kept; a Chinese take that is
    still mostly English is reported as not written rather than shown half translated.
    """
    sheet = fact_sheet(report, lang)
    t0 = time.time()
    ticker = ((report.get("ticket") or {}).get("ticker") or "",)
    first = _attempt(provider, report, sheet, lang)
    if first is None:
        return Take(status="failed", lang=lang, seconds=time.time() - t0)
    best = first
    english = lang == "zh" and mostly_english(_all_text(first), ticker)
    if english or first.removed >= REGENERATE_AT:
        second = _attempt(provider, report, sheet, lang, _RETRY_ZH if english else _RETRY_NUMBERS)
        if second is not None:
            second_english = lang == "zh" and mostly_english(_all_text(second), ticker)
            if english and second_english:
                best = second
            elif english:
                best = second
            elif not second_english and second.removed < first.removed:
                best = second
    if lang == "zh" and mostly_english(_all_text(best), ticker):
        return Take(status="failed", lang=lang, seconds=round(time.time() - t0, 1), model=best.model)
    best.seconds = round(time.time() - t0, 1)
    return best


class AnalystJobs:
    """Takes being written in the background, one per report and language."""

    def __init__(self, max_workers: int = 2, keep: int = 300):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analyst")
        self._takes: dict[tuple[int, str], Take] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def get(self, forecast_id: int, lang: str = "en") -> Take | None:
        return self._takes.get((forecast_id, lang))

    def prefetch(self, forecast_id: int, report: dict[str, Any], make_provider: Callable[[], Any], lang: str = "en") -> None:
        """Start the take the moment a report exists, before anyone asks for it.

        The provider is chosen inside the worker so the request that produced the report
        does not wait on it. If there is no provider nothing is recorded, so a later
        ``start`` with one still works. A later ``start`` for the same report and language
        finds this job and joins it rather than writing a second take.
        """
        self._launch((forecast_id, lang), report, make_provider, lang, prefetch=True)

    def start(self, forecast_id: int, report: dict[str, Any], provider: Any, lang: str = "en") -> Take:  # noqa: ANN401
        return self._launch((forecast_id, lang), report, (lambda: provider) if provider is not None else None, lang)

    def _launch(self, key: tuple[int, str], report: dict[str, Any], make_provider: Callable[[], Any] | None, lang: str, prefetch: bool = False) -> Take:
        forecast_id = key[0]
        with self._lock:
            existing = self._takes.get(key)
            if existing and (existing.status in ("pending", "done") or time.time() - existing.started < 60):
                return existing
            if make_provider is None:
                take = Take(status="unavailable", lang=lang)
                self._takes[key] = take
                return take
            take = Take(status="pending", lang=lang)
            self._takes[key] = take
            while len(self._takes) > self._keep:
                self._takes.pop(next(iter(self._takes)))

        def run() -> None:
            try:
                provider = make_provider()
                if provider is None:
                    with self._lock:
                        # Nothing to write with. A prefetch leaves no trace; an explicit ask says so.
                        if prefetch:
                            self._takes.pop(key, None)
                        else:
                            self._takes[key] = Take(status="unavailable", lang=lang)
                    return
                done = write(provider, report, lang)
            except Exception:  # noqa: BLE001 - a take that fails must not take anything else down
                log.exception("analyst take for %s failed", forecast_id)
                done = Take(status="failed", lang=lang)
            with self._lock:
                self._takes[key] = done

        self._pool.submit(run)
        return take
