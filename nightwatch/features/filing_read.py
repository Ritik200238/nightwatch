"""Reading the filing, not just timing it.

The desk already knows *when* an 8-K landed, and 99% of them land while the US market
is shut - which is the whole reason this product exists, because the stock cannot react
and the token can. What it has never known is what the filing said.

That matters because the timing is identical whatever the news is. Item 5.02 covers a
routine board appointment and a chief executive resigning overnight. Item 8.01 covers a
buyback and a plant fire. A feature built on "hours since the last filing" treats those
the same, and a trader holding the token through the night does not.

What the model does, and what it is not allowed to do
----------------------------------------------------
It reads the filing's own words and returns four things: a category, a one-line
headline, how likely this is to move the stock when the market reopens, and which way.
Nothing else. It never sees a price, never sees what happened afterwards, and never
produces a number that reaches a sizing decision.

Its judgement is then **scored, not trusted**. Every read is stored against the filing's
accession, and what actually followed each label is measured from our own bars. If the
model's "high, down" reads are followed by the same distribution as its "low" ones, the
study says so and the label stays off the report. That is the same bargain the rest of
the desk makes: the model may have an opinion, and history decides whether it counts.

Point-in-time by construction: the text was public at ``accepted_at``, so a read of it
is information that existed then, and a replay that uses it is not cheating.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from nightwatch.data.store import Store
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

# A controlled vocabulary, because a free-text label cannot be counted. These are the
# kinds of thing an 8-K or 6-K actually reports, at the grain a trader would separate.
CATEGORIES = (
    "results",  # earnings, revenue, financial results
    "guidance",  # outlook raised, cut or reaffirmed
    "leadership",  # executives and directors arriving or leaving
    "financing",  # debt, equity issuance, buybacks, dividends
    "deal",  # acquisitions, divestitures, major partnerships
    "legal",  # litigation, regulatory action, investigations
    "governance",  # charter, bylaws, shareholder votes, auditor changes
    "operations",  # products, facilities, customers, supply
    "routine",  # administrative filings with no news in them
)
MOVING = ("none", "low", "medium", "high")
DIRECTION = ("up", "down", "unclear")

# The news in a filing is at the top of it: a press release leads with the headline, and
# the forty pages underneath are the indenture. Trimming keeps the read cheap without
# losing the part that says what happened.
MAX_TEXT_CHARS = 12_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS filing_reads (
    accession TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    model TEXT NOT NULL,
    category TEXT NOT NULL,
    market_moving TEXT NOT NULL,
    direction TEXT NOT NULL,
    headline TEXT NOT NULL,
    reason TEXT NOT NULL,
    read_at INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    raw BLOB
);
CREATE INDEX IF NOT EXISTS filing_reads_ticker ON filing_reads (ticker);
"""

SYSTEM = (
    "You read US company filings for a desk that holds tokenized US stocks overnight, while the stock market is shut. "
    "You are given one filing's text. Say what it is and how much it matters, in JSON with exactly these keys:\n"
    f'  "category": one of {list(CATEGORIES)}\n'
    '  "headline": one sentence, under 20 words, saying what the filing actually reports. No preamble.\n'
    f'  "market_moving": one of {list(MOVING)} - how likely this moves the share price when the market next opens\n'
    f'  "direction": one of {list(DIRECTION)} - which way it points for the share price, "unclear" if it genuinely does not point\n'
    '  "reason": one short clause, under 15 words, for the market_moving and direction you chose\n'
    "\n"
    "Judge only from this text. Do not use anything you know about the company from elsewhere, do not guess at figures "
    'that are not in it, and do not soften a clear read: if a chief executive resigned with no successor named, that is '
    '"high" and "down". Most filings are genuinely routine and should be labelled "none" or "low" - a scale where '
    "everything is high measures nothing. Output the JSON object and nothing else."
)


@dataclass(frozen=True)
class FilingRead:
    accession: str
    ticker: str
    category: str
    market_moving: str
    direction: str
    headline: str
    reason: str
    model: str = ""
    read_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReadError(RuntimeError):
    """The model answered, but not with a read of the filing."""


def _one_of(value: Any, allowed: tuple[str, ...], field: str) -> str:  # noqa: ANN401
    got = str(value or "").strip().lower().replace(" ", "_")
    if got not in allowed:
        raise ReadError(f"{field}={value!r} is not one of {allowed}")
    return got


def parse_read(payload: dict[str, Any], *, accession: str, ticker: str, model: str) -> FilingRead:
    """Validate the model's answer into a read, or refuse it.

    A label outside the vocabulary is thrown away rather than coerced to the nearest
    one: the whole point of a controlled vocabulary is that the counts mean something,
    and a quietly remapped label makes a category that nobody asked for.
    """
    headline = str(payload.get("headline") or "").strip()
    if not headline:
        raise ReadError("no headline")
    return FilingRead(
        accession=accession,
        ticker=ticker,
        category=_one_of(payload.get("category"), CATEGORIES, "category"),
        market_moving=_one_of(payload.get("market_moving"), MOVING, "market_moving"),
        direction=_one_of(payload.get("direction"), DIRECTION, "direction"),
        headline=headline[:300],
        reason=str(payload.get("reason") or "").strip()[:200],
        model=model,
        read_at=utc_now().isoformat(),
    )


def read_filing(client: Any, *, accession: str, ticker: str, form: str, items: str | None, text: str) -> tuple[FilingRead, Any]:  # noqa: ANN401
    """One filing, read. ``client`` is a ``QwenClient`` (or anything with ``chat_json``)."""
    body = text[:MAX_TEXT_CHARS]
    prompt = (
        f"TICKER: {ticker}\nFORM: {form}\n"
        + (f"ITEMS: {items}\n" if items else "")
        + f"\nFILING TEXT\n\n{body}"
    )
    payload, usage = client.chat_json([{"role": "user", "content": prompt}], system=SYSTEM, max_tokens=700)
    return parse_read(payload, accession=accession, ticker=ticker, model=getattr(client, "model", "")), usage


class FilingReadStore:
    """Reads, kept. A filing's text does not change, so neither does its read - and at a
    few hundred filings per rerun, paying to read the same 8-K twice is just waste."""

    def __init__(self, store: Store):
        self._conn: sqlite3.Connection = store._conn
        self._conn.executescript(SCHEMA)

    def save(self, read: FilingRead, *, usage: Any = None, raw: dict | None = None) -> None:  # noqa: ANN401
        self._conn.execute(
            "INSERT INTO filing_reads (accession, ticker, model, category, market_moving, direction, headline, reason, read_at, prompt_tokens, completion_tokens, raw) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(accession) DO UPDATE SET model=excluded.model, category=excluded.category, market_moving=excluded.market_moving, "
            "direction=excluded.direction, headline=excluded.headline, reason=excluded.reason, read_at=excluded.read_at, "
            "prompt_tokens=excluded.prompt_tokens, completion_tokens=excluded.completion_tokens, raw=excluded.raw",
            (
                read.accession, read.ticker, read.model, read.category, read.market_moving, read.direction,
                read.headline, read.reason, int(utc_now().timestamp() * 1000),
                int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0),
                zlib.compress(json.dumps(raw).encode("utf-8"), 6) if raw else None,
            ),
        )
        self._conn.commit()

    def have(self) -> set[str]:
        return {r[0] for r in self._conn.execute("SELECT accession FROM filing_reads")}

    def get(self, accession: str) -> FilingRead | None:
        row = self._conn.execute(
            "SELECT accession, ticker, category, market_moving, direction, headline, reason, model, read_at FROM filing_reads WHERE accession=?",
            (accession,),
        ).fetchone()
        if row is None:
            return None
        return FilingRead(*row[:7], model=row[7], read_at=_iso(row[8]))

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM filing_reads").fetchone()[0])

    def tokens_used(self) -> tuple[int, int]:
        row = self._conn.execute("SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0) FROM filing_reads").fetchone()
        return int(row[0]), int(row[1])


def _iso(ms: Any) -> str:  # noqa: ANN401
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=utc_now().tzinfo).isoformat()
    except (TypeError, ValueError):
        return ""
