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
