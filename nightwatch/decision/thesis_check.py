"""Checking the trader's reason against what was actually reported.

A written thesis already clears the gate and is already held against the calendar (an
"earnings" reason with no earnings near the hold is flagged in ``story.premise``). What
nothing checked was the *news* in it: "Nvidia just hit record highs", "Tesla deliveries
beat". A trade opened on a story that never ran, or that ran the other way, is the
cheapest mistake to catch before the position exists.

How it works, and what the model is allowed to do
-------------------------------------------------
1. **Retrieval is ours.** The candidates are the headlines and SEC filings the desk had
   stored for this token in the 14 days before the report, as observed then - so a
   replayed report is checked against what was knowable at that moment, never later news.
2. **The model only matches.** It splits the reason into factual claims and, for each,
   names which numbered items say the same thing or the opposite. It never writes a
   quote: every quote shown is the stored headline, by the id the model named, with its
   source, time and link. An id that was not offered is discarded, and a "supported" or
   "contradicted" with no surviving evidence becomes "not found".
3. **A claim must come from the reason.** One that shares no content word with what the
   trader wrote is dropped, so the model cannot add claims of its own.
4. **Without a model** the check still runs, as a keyword match that lists related
   headlines and never says "supported".

"Not found" means not in these feeds, not false - the page says so.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms

WINDOW = timedelta(days=14)
MAX_ITEMS = 30
MAX_CLAIMS = 5
# Keyword fallback: a headline must share this many content words with the reason.
KEYWORD_MIN_OVERLAP = 2

_STOP = set(
    "a an and are as at be because but by for from has have i if in into is it its it's my "
    "of on or over so that the their this to was were will with would just very really "
    "long short buy sell hold holding position trade weekend overnight tonight stock token "
    "think thesis wrong closes close below above should could going up down".split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9.%$-]*|[㐀-鿿]{2,}", re.I)


_CJK = re.compile(r"[㐀-鿿]")


def _words(text: str) -> set[str]:
    """Content words; Chinese has no spaces, so a run of characters counts by its pairs."""
    out: set[str] = set()
    for w in _WORD.findall(text or ""):
        w = w.lower().strip(".")
        if _CJK.match(w):
            out.update(w[i:i + 2] for i in range(len(w) - 1))
        elif w not in _STOP and len(w) > 1:
            out.add(w)
    return out


@dataclass
class Item:
    """One stored headline or filing the reason can be checked against."""

    id: str  # "N3" for news, "F2" for a filing: what the model refers to
    kind: Literal["news", "filing"]
    title: str
    source: str
    published_at: str
    link: str | None = None


@dataclass
class Claim:
    claim: str
    status: Literal["supported", "contradicted", "not_found", "related"]
    evidence: list[Item] = field(default_factory=list)
    note: str = ""


@dataclass
class ThesisCheck:
    state: Literal["checked", "no_thesis", "no_items"]
    method: Literal["model", "keyword", "none"]
    ticker: str
    window_days: int
    items_considered: int
    claims: list[Claim] = field(default_factory=list)
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------- retrieval

# The feed ids the recorder stores under, as a reader would name the publisher.
_SOURCES = {"cnbc": "CNBC", "marketwatch": "MarketWatch", "cointelegraph": "Cointelegraph", "fed": "Federal Reserve", "sec": "SEC"}


def source_name(feed: str) -> str:
    return _SOURCES.get((feed or "").split("_", 1)[0].lower(), feed)



def candidates(conn: sqlite3.Connection, ticker: str, as_of: datetime, thesis: str = "") -> list[Item]:
    """Headlines and filings for the token in the window before ``as_of``, as known then.

    Ranked by how many content words they share with the reason, then by recency, and
    capped, so a busy fortnight does not crowd the relevant line out of the prompt."""
    end = ensure_utc(as_of)
    start_ms, end_ms = to_epoch_ms(end - WINDOW), to_epoch_ms(end)
    rows: list[tuple[str, str, str, int, str | None]] = []
    for source, title, link, published, tickers in conn.execute(
        "SELECT source, title, link, published_at, tickers FROM news WHERE published_at >= ? AND published_at <= ? AND observed_at <= ?",
        (start_ms, end_ms, end_ms),
    ).fetchall():
        try:
            tagged = ticker in json.loads(tickers or "[]")
        except ValueError:
            tagged = False
        if tagged:
            rows.append(("news", title, source_name(source), int(published), link))
    window = (ticker, start_ms, end_ms, end_ms)
    try:
        filings = conn.execute(
            "SELECT f.form, f.accepted_at, f.description, r.headline FROM filings f LEFT JOIN filing_reads r ON r.accession = f.accession "
            "WHERE f.ticker = ? AND f.accepted_at >= ? AND f.accepted_at <= ? AND f.observed_at <= ?", window,
        ).fetchall()
    except sqlite3.OperationalError:  # no filing reads yet: the filing's own description
        filings = conn.execute(
            "SELECT form, accepted_at, description, NULL FROM filings WHERE ticker = ? AND accepted_at >= ? AND accepted_at <= ? AND observed_at <= ?", window,
        ).fetchall()
    for form, accepted, desc, headline in filings:
        text = headline or desc
        if text:
            rows.append(("filing", f"{form}: {text}", "SEC EDGAR", int(accepted), None))
    want = _words(thesis)
    rows.sort(key=lambda r: (len(want & _words(r[1])), r[3]), reverse=True)
    out: list[Item] = []
    n = f = 0
    for kind, title, source, published, link in rows[:MAX_ITEMS]:
        if kind == "news":
            n += 1
            iid = f"N{n}"
        else:
            f += 1
            iid = f"F{f}"
        out.append(Item(id=iid, kind=kind, title=title.strip(), source=source, published_at=from_epoch_ms(published).isoformat(), link=link))
    return out


# --------------------------------------------------------------------- the model


_STATUS = {"supported": "supported", "support": "supported", "confirmed": "supported", "contradicted": "contradicted",
           "contradict": "contradicted", "refuted": "contradicted", "not_found": "not_found", "not found": "not_found", "unknown": "not_found"}


class _ClaimOut(BaseModel):
    # The provider's shape hint only names top-level fields, so the model has been seen
    # answering "judgment" and "items" for these; the other names are accepted, and
    # lengths are trimmed here rather than failing a whole answer over one long note.
    claim: str
    status: str = Field(default="not_found", validation_alias=AliasChoices("status", "judgment", "verdict", "result"))
    evidence: list[str] = Field(default_factory=list, validation_alias=AliasChoices("evidence", "items", "ids", "evidence_ids"))
    note: str = Field(default="", validation_alias=AliasChoices("note", "reason", "why"))

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v: Any) -> str:  # noqa: ANN401
        return _STATUS.get(str(v or "").strip().lower().replace("-", "_"), "not_found")

    @field_validator("evidence", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> list[str]:  # noqa: ANN401
        if isinstance(v, str):
            v = re.findall(r"[NF]\d+", v, re.I)
        return [str(x) for x in (v or [])][:3]


class _Out(BaseModel):
    claims: list[_ClaimOut] = Field(default_factory=list)


SYSTEM = (
    "You check a trader's stated reason for a trade against a numbered list of news headlines and SEC filings. "
    "Step 1: split the reason into factual claims about events that a headline could confirm (a company announcement, "
    "a price record, a report, a deal, a data release). Skip opinions, feelings, price targets, chart levels and the "
    "'wrong if' condition. Quote each claim in the trader's own words, shortened if needed. At most five. "
    "Step 2: for each claim, judge ONLY from the numbered items. 'supported' if an item reports the same thing; "
    "'contradicted' if an item reports the opposite; otherwise 'not_found'. Never use outside knowledge, never guess. "
    "List the ids of the items you relied on (e.g. N2, F1). 'note' is one short sentence saying why, in {lang}. "
    "If the reason has no factual claims, return an empty claims list. "
    'Exact shape: {{"claims": [{{"claim": "...", "status": "supported|contradicted|not_found", "evidence": ["N1"], "note": "..."}}]}}'
)


def _prompt(thesis: str, ticker: str, items: list[Item]) -> str:
    lines = [f"TOKEN: {ticker}", f"REASON: {thesis}", "", "ITEMS:"]
    lines += [f"{i.id} [{i.published_at[:10]}, {i.source}] {i.title}" for i in items]
    return "\n".join(lines)


_ID_REF = re.compile(r"(?<![A-Za-z0-9])(?:(?:headlines?|items?|filings?)\s+)?([NF])\d+(?![0-9])(?:标题|新闻)?", re.I)


def _plain_note(note: str, lang_zh: bool) -> str:
    """The model refers to items by our ids ("N2 states..."), which mean nothing on the page."""
    def name(m: re.Match[str]) -> str:
        if lang_zh:
            return "该新闻" if m.group(1).upper() == "N" else "该文件"
        return "the headline" if m.group(1).upper() == "N" else "the filing"
    text = _ID_REF.sub(name, note).strip()
    # "Both N1 and N2 report..." became "both the headline and the headline report...".
    for one, many in (("the headline", "headlines"), ("the filing", "filings")):
        text = re.sub(rf"\b[Bb]oth {one} and {one}\b", f"both {many}", text)
        text = re.sub(rf"\b{one}(?:, {one})* and {one}\b", f"these {many}", text)
    for one, many in (("该新闻", "这些新闻"), ("该文件", "这些文件")):
        text = re.sub(rf"{one}(?:[、,，和及与]{one})+", many, text)
    return text[:1].upper() + text[1:] if text and not lang_zh else text


def _accept(out: _Out, thesis: str, items: list[Item], lang: str = "en") -> list[Claim]:
    by_id = {i.id: i for i in items}
    said = _words(thesis)
    claims: list[Claim] = []
    for c in out.claims:
        if not (_words(c.claim) & said):
            continue  # not something the trader said
        evidence = [by_id[e.strip().upper()] for e in c.evidence if e.strip().upper() in by_id]
        status = c.status if evidence or c.status == "not_found" else "not_found"
        claims.append(Claim(claim=c.claim.strip()[:240], status=status, evidence=evidence if status != "not_found" else [], note=_plain_note(c.note, lang == "zh")[:240]))
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


def _keyword(thesis: str, items: list[Item]) -> list[Claim]:
    want = _words(thesis)
    related = [i for i in items if len(want & _words(i.title)) >= KEYWORD_MIN_OVERLAP][:3]
    return [Claim(claim=thesis.strip(), status="related" if related else "not_found", evidence=related,
                  note="Matched by shared words only; no model read these." if related else "")]


def check(
    conn: sqlite3.Connection, *, ticker: str, thesis: str, as_of: datetime,
    parse: Callable[[str, str], _Out | None] | None = None, model: str | None = None, lang: str = "en",
) -> ThesisCheck:
    """Check ``thesis`` for ``ticker`` against what was stored before ``as_of``.

    ``parse(system, user)`` asks a model for an ``_Out``; None (or a failure) falls back
    to the keyword match."""
    ticker = ticker.upper()
    base = {"ticker": ticker, "window_days": WINDOW.days}
    if not (thesis or "").strip():
        return ThesisCheck(state="no_thesis", method="none", items_considered=0, **base)
    items = candidates(conn, ticker, as_of, thesis)
    if not items:
        return ThesisCheck(state="no_items", method="none", items_considered=0, **base)
    if parse is not None:
        try:
            out = parse(SYSTEM.format(lang="Chinese" if lang == "zh" else "English"), _prompt(thesis, ticker, items))
        except Exception:  # noqa: BLE001 - a failed model call falls back, never fails the page
            out = None
        if out is not None:
            return ThesisCheck(state="checked", method="model", items_considered=len(items), claims=_accept(out, thesis, items, lang), model=model, **base)
    return ThesisCheck(state="checked", method="keyword", items_considered=len(items), claims=_keyword(thesis, items), **base)


def parser_for(provider: Any) -> Callable[[str, str], _Out | None]:  # noqa: ANN401
    """Adapt a provider (nightwatch.api.providers) to ``check``'s ``parse``."""
    def parse(system: str, user: str) -> _Out | None:
        return provider.parse([{"role": "user", "content": user}], system=system, schema=_Out, max_tokens=1200)

    return parse


# ------------------------------------------------------------------------ chat

ASKS = re.compile(
    r"\b(?:is|was) my (?:reason|thesis|idea|story)\b|\b(?:check|verify|fact[- ]?check) (?:my |the )?(?:reason|thesis|claim|story|news)"
    r"|\bis (?:the|that|this) news (?:true|real|right)|\bam i right about\b"
    r"|我的(?:理由|逻辑|判断)(?:对|成立|靠谱)|核实(?:一下)?(?:我的)?(?:理由|逻辑|新闻)|新闻是真的吗",
    re.I,
)

_WORD_EN = {"supported": "In the news", "contradicted": "The news says otherwise", "not_found": "Not in our feeds", "related": "Related headlines"}
_WORD_ZH = {"supported": "新闻中有", "contradicted": "新闻说法相反", "not_found": "数据源中没有", "related": "相关标题"}


def reply_text(got: dict[str, Any] | None, lang: str = "en") -> str:
    """The check as a chat answer. Every quote is a stored headline, as on the report."""
    zh = lang == "zh"
    if got is None or got.get("state") == "no_thesis":
        return ("这笔交易没有写理由。告诉我你为什么做，例如“因为……，如果收盘跌破……就算错”，我会把理由和新闻对照。" if zh else
                'This trade has no written reason to check. Tell me why you want it - e.g. "because ..., wrong if it closes below ..." - and I will hold it against the news.')
    if got["state"] == "no_items":
        return (f"本报告之前 {got['window_days']} 天内，我们的数据源中没有 {got['ticker']} 的新闻或公告，无从对照你的理由。" if zh else
                f"There are no {got['ticker']} headlines or filings in our feeds in the {got['window_days']} days before this report, so there is nothing to check your reason against.")
    if not got["claims"]:
        return "你的理由没有可由新闻证实的事实陈述（更像观点而非报道）。" if zh else "Your reason makes no claim a headline could confirm; it reads as a view, not a report."
    words = _WORD_ZH if zh else _WORD_EN
    lines = [f"你的理由与过去 {got['window_days']} 天 {got['ticker']} 新闻和公告的对照：" if zh else
             f"Your reason against {got['window_days']} days of {got['ticker']} headlines and filings:"]
    for c in got["claims"]:
        ev = "; ".join(f"{e['title']} ({e['source']}, {e['published_at'][:10]})" for e in c["evidence"])
        lines.append(f"- {words[c['status']]}：“{c['claim']}”" + (f" —— {ev}" if ev else "") if zh else
                     f"- {words[c['status']]}: \"{c['claim']}\"" + (f" - {ev}" if ev else ""))
    lines.append("“数据源中没有”表示我们没看到，不代表它是假的。" if zh else "\"Not in our feeds\" means we did not see it, not that it is false.")
    return "\n".join(lines)
