"""Company filings from SEC EDGAR, timed to the second they were accepted.

Why this source: an 8-K is how a US company tells the market something material, and
most of them are accepted after 4 p.m. Eastern, when the stock cannot trade and the token
can. The acceptance timestamp is exact, so "was there a filing in the last day" is a
question we can answer point-in-time for any hour in our history, not just for now.

EDGAR's rules: identify yourself in the User-Agent, stay under ten requests a second. The
submissions endpoint returns a company's recent filings in one call, which for a large
issuer is years of them.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta

from nightwatch.data.http import HttpClient
from nightwatch.data.models import Filing
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov"
DATA_URL = "https://data.sec.gov"
# EDGAR wants "Name contact@address" and answers 403 with an HTML page otherwise. It also
# rejects addresses that mention github, so the contact is a plain mailbox, overridable.
CONTACT = os.environ.get("NIGHTWATCH_SEC_CONTACT", "nightwatch-desk@example.com")
USER_AGENT = f"Nightwatch decision desk {CONTACT}"
# The forms that carry news, not administrative paperwork. 6-K is the foreign-issuer 8-K.
FORMS = frozenset({"8-K", "8-K/A", "6-K", "10-Q", "10-K", "10-K/A", "10-Q/A"})


class SecFilingsClient:
    def __init__(self, *, http_www: HttpClient | None = None, http_data: HttpClient | None = None):
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        self._www = http_www or HttpClient(TICKERS_URL, headers=headers, rate_per_sec=4.0, burst=2, timeout=40.0)
        self._data = http_data or HttpClient(DATA_URL, headers=headers, rate_per_sec=4.0, burst=2, timeout=40.0)
        self._ciks: dict[str, str] | None = None

    def close(self) -> None:
        self._www.close()
        self._data.close()

    # ------------------------------------------------------------------ lookup

    def cik_map(self) -> dict[str, str]:
        """Ticker -> zero-padded CIK, from EDGAR's own list. Fetched once per client."""
        if self._ciks is None:
            raw = self._www.get_json("/files/company_tickers.json")
            self._ciks = {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
        return self._ciks

    def cik_for(self, ticker: str) -> str | None:
        return self.cik_map().get(ticker.upper())

    # ----------------------------------------------------------------- filings

    def get_filings(self, ticker: str, *, since: datetime | None = None) -> list[Filing]:
        """Every news-bearing filing for a ticker, newest last."""
        cik = self.cik_for(ticker)
        if cik is None:
            log.info("no CIK for %s (not an SEC registrant, or a different symbol on EDGAR)", ticker)
            return []
        payload = self._data.get_json(f"/submissions/CIK{cik}.json")
        recent = payload.get("filings", {}).get("recent", {})
        observed = utc_now()
        out: list[Filing] = []
        forms = recent.get("form", [])
        for i, form in enumerate(forms):
            if form not in FORMS:
                continue
            accepted = _parse(recent["acceptanceDateTime"][i])
            if accepted is None or (since is not None and accepted < since):
                continue
            filed = datetime.fromisoformat(recent["filingDate"][i]).replace(tzinfo=UTC)
            out.append(
                Filing(
                    ticker=ticker.upper(), cik=cik, form=form, accepted_at=accepted, filed_date=filed,
                    accession=recent["accessionNumber"][i],
                    description=(recent.get("primaryDocDescription", [None] * len(forms))[i] or None),
                    items=(recent.get("items", [None] * len(forms))[i] or None),
                    observed_at=observed,
                )
            )
        out.sort(key=lambda f: f.accepted_at)
        return out


    # -------------------------------------------------------------- documents

    def document_text(self, cik: str, accession: str, *, max_chars: int = 40_000) -> str | None:
        """The filing's own words, stripped to plain text.

        The index we already store says *when* a filing landed and which items it
        touched; it does not say what it said. For an 8-K those are different things -
        item 5.02 covers both a routine board appointment and a chief executive leaving
        overnight - and the difference is only in the prose.

        Returns ``None`` when the primary document cannot be identified rather than
        guessing at one, because the wrong document read confidently is worse than a
        filing left unread.
        """
        base = f"/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
        try:
            listing = self._www.get_json(f"{base}/index.json")
        except Exception:  # noqa: BLE001 - a missing filing is not a reason to stop a batch
            log.info("sec: no index for %s", accession)
            return None
        names = [str(i.get("name", "")) for i in (listing.get("directory", {}).get("item") or [])]
        wanted = readable_documents(names)
        if not wanted:
            return None
        parts: list[str] = []
        for name in wanted:
            try:
                parts.append(strip_html(self._www.get_text(f"{base}/{name}")))
            except Exception:  # noqa: BLE001
                log.info("sec: could not read %s/%s", accession, name)
            if sum(len(p) for p in parts) >= max_chars:
                break
        text = "\n\n".join(p for p in parts if p).strip()
        return text[:max_chars] or None


# EDGAR renders every filing into per-fact XBRL viewer pages called R1.htm, R2.htm and
# so on. They are a table of tagged values, not the filing, and picking one up instead of
# the document is how you end up reading "Document Type 8-K Entity Registrant Name ...".
_XBRL_RENDER = re.compile(r"^R\d+\.htm$", re.I)
# The substance of an 8-K is often not in the 8-K. The shell says "see Exhibit 99.1" and
# the press release underneath it is where the news actually is, so both are read.
_EXHIBIT = re.compile(r"ex[-_]?99", re.I)


def readable_documents(names: list[str], *, limit: int = 3) -> list[str]:
    """The files in a filing worth reading, most substantive first.

    Skips EDGAR's own index pages and its XBRL renderings, and puts any Exhibit 99
    press release ahead of the 8-K shell that points at it.
    """
    candidates = [
        n for n in names
        if n.lower().endswith((".htm", ".html"))
        and "index" not in n.lower()
        and not _XBRL_RENDER.match(n)
    ]
    exhibits = [n for n in candidates if _EXHIBIT.search(n)]
    rest = [n for n in candidates if n not in exhibits]
    return (exhibits + rest)[:limit]


_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", re.I)
_SPACE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    """Filing HTML as readable prose.

    Deliberately not a full parser: EDGAR documents are generated HTML with inline XBRL
    tags, and everything that matters here is the visible text. Script and style bodies
    go first so their contents do not survive as words.
    """
    text = _TAG.sub(" ", html)
    text = _ENTITY.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def after_hours(f: Filing) -> bool:
    """Accepted outside 09:30–16:00 Eastern on a weekday: the token alone can react."""
    et = f.accepted_at.astimezone(_ET)
    if et.weekday() >= 5:
        return True
    minutes = et.hour * 60 + et.minute
    return not (9 * 60 + 30 <= minutes < 16 * 60)


try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 - tzdata is a declared dependency; this is belt and braces
    _ET = UTC


def history_start(years: int = 2) -> datetime:
    return utc_now() - timedelta(days=365 * years)
