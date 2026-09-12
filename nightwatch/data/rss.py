"""News headlines from RSS/Atom feeds, with ticker tagging.

Verified working feeds (2026-09-12): CNBC top news, MarketWatch top stories,
Cointelegraph, Federal Reserve press releases. Reuters' public feed is dead.
Feeds are fetched raw through our transport (so retries/limits apply) and parsed
with feedparser; items are tagged with tickers by matching symbols and company
aliases in the title/summary.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from time import mktime

import feedparser

from nightwatch.data.http import HttpClient
from nightwatch.data.models import NewsItem
from nightwatch.time_utils import utc_now

log = logging.getLogger(__name__)

DEFAULT_FEEDS: dict[str, str] = {
    "cnbc_top": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "cnbc_markets": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "marketwatch_top": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "marketwatch_markets": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
    "cointelegraph": "https://cointelegraph.com/rss",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
    "sec_press": "https://www.sec.gov/news/pressreleases.rss",
}

# Company aliases for the tokenized names; extend as instruments are added.
COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "TSLA": ("tesla", "musk"),
    "NVDA": ("nvidia", "jensen huang"),
    "AAPL": ("apple",),
    "MSFT": ("microsoft",),
    "AMZN": ("amazon",),
    "GOOGL": ("alphabet", "google"),
    "META": ("meta platforms", "facebook", "zuckerberg"),
    "NFLX": ("netflix",),
    "AMD": ("advanced micro devices",),
    "PLTR": ("palantir",),
    "MSTR": ("microstrategy", "strategy inc", "saylor"),
    "HOOD": ("robinhood",),
    "BABA": ("alibaba",),
    "CRCL": ("circle internet", "circle's usdc"),
    "SPY": ("s&p 500", "s&p500"),
    "QQQ": ("nasdaq-100", "nasdaq 100"),
}


class RssNewsClient:
    """Implements ``NewsSource``."""

    def __init__(
        self,
        feeds: Mapping[str, str] | None = None,
        *,
        tickers: Iterable[str] = (),
        http: HttpClient | None = None,
    ):
        self.feeds = dict(feeds or DEFAULT_FEEDS)
        self._http = http or HttpClient(headers={"User-Agent": "Mozilla/5.0 nightwatch/0.1"}, rate_per_sec=2.0, burst=4)
        self._patterns = _build_patterns(tickers)

    def close(self) -> None:
        self._http.close()

    def fetch(self, feeds: Iterable[str] | None = None) -> list[NewsItem]:
        names = list(feeds) if feeds is not None else list(self.feeds)
        observed = utc_now()
        out: list[NewsItem] = []
        for name in names:
            url = self.feeds.get(name)
            if not url:
                log.warning("unknown feed %s", name)
                continue
            try:
                # Raw bytes: feedparser reads the XML encoding declaration itself, which
                # avoids mojibake when a publisher's HTTP charset header is wrong.
                body = self._http.get_bytes(url)
            except Exception as exc:  # noqa: BLE001 - one dead feed must not stop the rest
                log.warning("feed %s failed: %s", name, exc)
                continue
            parsed = feedparser.parse(body)
            for entry in parsed.entries:
                item = self._to_item(name, entry, observed)
                if item is not None:
                    out.append(item)
        out.sort(key=lambda n: n.published_at)
        return out

    def _to_item(self, source: str, entry, observed: datetime) -> NewsItem | None:  # noqa: ANN001
        title = (getattr(entry, "title", "") or "").strip()
        if not title:
            return None
        link = getattr(entry, "link", None)
        guid = getattr(entry, "id", None) or link or title
        item_id = hashlib.sha1(str(guid).encode("utf-8")).hexdigest()[:20]
        struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if struct is None:
            published = observed
        else:
            published = datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
        summary = (getattr(entry, "summary", "") or "").strip() or None
        text = f"{title}\n{summary or ''}"
        tickers = tuple(sorted(t for t, pat in self._patterns.items() if pat.search(text)))
        return NewsItem(
            source=source, id=item_id, published_at=published, title=title, link=link,
            summary=summary[:2000] if summary else None, tickers=tickers, observed_at=observed,
        )


def _build_patterns(tickers: Iterable[str]) -> dict[str, re.Pattern[str]]:
    patterns: dict[str, re.Pattern[str]] = {}
    for t in tickers:
        t = t.upper()
        words = [re.escape(t)] + [re.escape(a) for a in COMPANY_ALIASES.get(t, ())]
        # Ticker symbol must appear as its own token (avoid AMD inside "AMDOCS"); aliases are case-insensitive.
        symbol_part = rf"(?<![A-Z0-9]){re.escape(t)}(?![A-Z0-9])"
        alias_part = "|".join(words[1:])
        pattern = symbol_part if not alias_part else rf"{symbol_part}|(?i:{alias_part})"
        patterns[t] = re.compile(pattern)
    return patterns
