"""What the street and the insiders are doing, from Bitget's US-stock data.

Context, not signal. Analyst ratings, price targets and insider trades are the things a
trader looks up before holding a stock overnight, and a research desk that makes them
look it up elsewhere is doing half the job. So they are here, summarised and labelled.

What they are not is an input to the size. Nothing in this desk's history says whether a
fresh downgrade or an officer's sale predicts the next overnight move, and the rule every
other number follows is that it reaches the verdict only after it has been measured to
help. Until then they are shown beside the verdict and said to be context.

One part does do work: Bitget's own quote for the underlying stock. Fair value, and with
it the basis the search and the stress presets lean on, is built from a native price the
desk fetches elsewhere. An independent quote from a second source catches that price
being wrong or stale, and a disagreement is raised as a warning rather than trusted.
And while the US market is shut, Bitget's quote keeps moving with the stock's overnight
trading, which makes it a live fair value where the desk otherwise only has yesterday's
close: the report shows how far the token sits from each.

All of it is current data. It describes today, so it is only attached to an analysis of
today - a replay of a past night showing today's analyst targets would be lookahead.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from nightwatch.time_utils import UTC, utc_now

WINDOW_DAYS = 90
RECENT_DAYS = 30
# Past this gap between Bitget's quote and the native price the desk is using, one of
# them is wrong or stale and the basis built on it should not be taken on trust.
QUOTE_DISAGREE_BPS = 75.0

# The ratings arrive in Chinese brokerage vocabulary. Grouped the way a reader would:
BULLISH = {"买入", "跑赢大盘", "增持", "最佳选择", "强力买入", "优于大市", "表现优于大盘"}
NEUTRAL = {"中性", "持有", "持股观望", "市场持平", "行业一致", "大市表现", "同业一致", "与大市同步"}
BEARISH = {"卖出", "减持", "逊于大盘", "表现逊于大盘", "强力卖出"}
RATING_EN = {
    "买入": "Buy", "跑赢大盘": "Outperform", "增持": "Overweight", "最佳选择": "Top pick", "强力买入": "Strong buy",
    "中性": "Neutral", "持有": "Hold", "持股观望": "Hold", "市场持平": "Market perform", "行业一致": "Sector perform",
    "大市表现": "Market perform", "同业一致": "Peer perform", "卖出": "Sell", "减持": "Underweight", "逊于大盘": "Underperform",
    "不评级": "Not rated",
}
ACTION_EN = {
    "维持": "maintained", "重申": "reiterated", "下调评级": "downgraded", "调高评级": "upgraded", "首次覆盖": "initiated",
    "恢复": "resumed", "假设": "assumed", "暂停评级": "suspended",
}
# Open-market trades only. Awards, option exercises and tax withholding are compensation
# mechanics, not someone choosing to buy or sell.
INSIDER_BUY, INSIDER_SELL = "P", "S"


def _day(value: Any) -> datetime | None:  # noqa: ANN401
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass
class RatingChange:
    date: str
    firm: str
    action: str
    rating: str
    target: float | None


@dataclass
class InsiderTrade:
    date: str
    name: str
    title: str
    side: str  # "buy" | "sell"
    shares: float
    price: float | None

    @property
    def value(self) -> float:
        return self.shares * (self.price or 0.0)


@dataclass
class StreetView:
    ticker: str
    fetched_at: str
    last_price: float | None = None
    prev_close: float | None = None
    n_ratings: int = 0
    n_firms: int = 0
    bullish: int = 0
    neutral: int = 0
    bearish: int = 0
    median_target: float | None = None
    target_gap_pct: float | None = None
    upgrades_recent: int = 0
    downgrades_recent: int = 0
    recent_changes: list[RatingChange] = field(default_factory=list)
    insider_buys: int = 0
    insider_sells: int = 0
    insider_bought_value: float = 0.0
    insider_sold_value: float = 0.0
    insider_latest: list[InsiderTrade] = field(default_factory=list)
    mood_score: float | None = None
    mood_rating: str | None = None
    mood_week_ago: float | None = None
    mood_month_ago: float | None = None
    source: str = "Bitget US-stock data (bitget-mcp-server)"

    @property
    def empty(self) -> bool:
        return self.last_price is None and not self.n_ratings and not (self.insider_buys or self.insider_sells) and self.mood_score is None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarise_ratings(view: StreetView, rows: list[dict[str, Any]], now: datetime) -> None:
    since, recent = now - timedelta(days=WINDOW_DAYS), now - timedelta(days=RECENT_DAYS)
    window = [r for r in rows if (d := _day(r.get("published_date") or r.get("rating_date"))) and d >= since]
    if not window:
        return
    # One view per firm: its latest. A firm that reiterated four times is one opinion.
    latest: dict[str, dict[str, Any]] = {}
    for r in sorted(window, key=lambda r: str(r.get("published_date") or ""), reverse=True):
        latest.setdefault(str(r.get("analyst_firm") or r.get("rating_org") or "?"), r)
    view.n_ratings = len(window)
    view.n_firms = len(latest)
    for r in latest.values():
        rating = r.get("rating_current") or r.get("latest_rating_cn")
        view.bullish += rating in BULLISH
        view.neutral += rating in NEUTRAL
        view.bearish += rating in BEARISH
    targets = [float(r["price_target"]) for r in latest.values() if r.get("price_target")]
    if targets:
        view.median_target = statistics.median(targets)
        if view.last_price:
            view.target_gap_pct = (view.median_target / view.last_price - 1.0) * 100.0
    for r in window:
        d = _day(r.get("published_date"))
        if d and d >= recent:
            view.upgrades_recent += r.get("action") == "调高评级"
            view.downgrades_recent += r.get("action") == "下调评级"
    notable = [r for r in window if r.get("action") in ("调高评级", "下调评级", "首次覆盖")] or window
    for r in sorted(notable, key=lambda r: str(r.get("published_date") or ""), reverse=True)[:4]:
        view.recent_changes.append(RatingChange(
            date=str(r.get("published_date") or "")[:10],
            firm=str(r.get("analyst_firm") or r.get("rating_org") or ""),
            action=ACTION_EN.get(str(r.get("action")), "rated"),
            rating=RATING_EN.get(str(r.get("rating_current")), str(r.get("rating_current") or "")),
            target=float(r["price_target"]) if r.get("price_target") else None,
        ))


def summarise_insiders(view: StreetView, rows: list[dict[str, Any]], now: datetime) -> None:
    since = now - timedelta(days=WINDOW_DAYS)
    trades: list[InsiderTrade] = []
    for r in rows:
        kind = r.get("transaction_type")
        d = _day(r.get("transaction_date") or r.get("filing_date"))
        if kind not in (INSIDER_BUY, INSIDER_SELL) or not d or d < since:
            continue
        trades.append(InsiderTrade(
            date=d.date().isoformat(), name=str(r.get("owner_name") or ""), title=str(r.get("owner_title") or r.get("ownership_type") or ""),
            side="buy" if kind == INSIDER_BUY else "sell",
            shares=float(r.get("securities_transacted") or 0.0),
            price=float(r["transaction_price"]) if r.get("transaction_price") else None,
        ))
    view.insider_buys = sum(t.side == "buy" for t in trades)
    view.insider_sells = sum(t.side == "sell" for t in trades)
    view.insider_bought_value = sum(t.value for t in trades if t.side == "buy")
    view.insider_sold_value = sum(t.value for t in trades if t.side == "sell")
    view.insider_latest = sorted(trades, key=lambda t: t.date, reverse=True)[:3]


def build(client: Any, ticker: str, *, now: datetime | None = None) -> StreetView:  # noqa: ANN401
    """Everything the desk shows about the street for one ticker, fetched now.

    ``client`` is a ``BitgetMcpClient`` or anything with its ``query`` method. Each
    part fails on its own: no analyst coverage (an ETF) still leaves the quote and the
    insider record.
    """
    now = now or utc_now()
    view = StreetView(ticker=ticker, fetched_at=now.isoformat())
    quote = client.query("equity_price_quote", symbol=ticker)
    if quote:
        q = quote[0]
        view.last_price = float(q["last_price"]) if q.get("last_price") else None
        view.prev_close = float(q["prev_close"]) if q.get("prev_close") else None
    summarise_ratings(view, client.query("equity_estimates_price_target", symbol=ticker, limit=200), now)
    summarise_insiders(view, client.query("equity_ownership_insider_trading", symbol=ticker, limit=50), now)
    mood = client.query("sentiment_market_fear_greed")
    if mood:
        m = mood[0]
        view.mood_score = float(m["score"]) if m.get("score") is not None else None
        view.mood_rating = str(m.get("rating") or "") or None
        view.mood_week_ago = float(m["previous_1_week"]) if m.get("previous_1_week") is not None else None
        view.mood_month_ago = float(m["previous_1_month"]) if m.get("previous_1_month") is not None else None
    return view


def quote_disagreement_bps(view: StreetView | None, native_close: float | None, native_age_h: float | None) -> float | None:
    """How far the native price fair value uses is from Bitget's quote for the same close.

    Like for like, or the check raises alarms about nothing: while the market is shut the
    desk's native price is the last session's close and Bitget's comparable figure is its
    previous close, not its live price. During a session both are current.
    """
    if view is None or not native_close:
        return None
    ref = view.prev_close if (native_age_h is not None and native_age_h >= 1.0) else view.last_price
    if not ref:
        return None
    return (native_close / ref - 1.0) * 10_000.0


def token_vs_live_bps(view: StreetView | None, token_price: float | None) -> float | None:
    """How far the token trades from the stock's live price, where Bitget has one.

    Measured on 2026-09-24 with the US market shut, the token sat 6-46 bps from Bitget's
    live quote across five names and 55-196 bps from the last close - the close is a
    stale anchor at night and the live quote is not. This is the gap the product exists
    to watch: how far the token has moved from where the stock actually is.
    """
    if view is None or not view.last_price or not token_price:
        return None
    return (token_price / view.last_price - 1.0) * 10_000.0
