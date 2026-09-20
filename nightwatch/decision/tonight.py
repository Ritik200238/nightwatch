"""What in this book needs looking at before the US market shuts.

The desk answers a question you bring it. This answers the one you would not have thought
to ask: of the positions you are already holding, which one is the problem tonight.

It is the same machinery pointed the other way. For each held position it takes the
window between now and the next regular open, asks what past moments like this one did
over exactly that window, prices the presets at the size actually held, walks the live
book for that size, and looks up what the recorded archive says the book does at those
hours of the week. Then it says which of those is worth being woken for.

The ranking is by money, not by drama. A five per cent tail on a small position matters
less than a two per cent tail on a large one, and a book that cannot absorb a position at
three in the morning is a problem whatever the distribution says. Anything that reaches
the top of this list is something a person could act on before they go to bed: cut it,
hedge it, or set the stop somewhere the overnight band does not reach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from nightwatch.time_utils import classify_session, ensure_utc, utc_now

# How wide an overnight window has to be before it is worth mentioning on its own, as a
# share of the position. Below this the tail is ordinary and the row says so.
WIDE_TAIL_PCT = 3.0
# How often the recorded book has to have failed to absorb the size, in these hours of the
# week, before "you may not get out" is a fair thing to say.
THIN_SHARE = 0.2
# An event this close to the window counts as landing inside it.
EVENT_HOURS = 1.0


@dataclass(frozen=True)
class Watch:
    """One held position, judged over tonight's window."""

    ticker: str
    side: str
    notional_quote: float
    p5_pct: float | None  # the calibrated bad case over this window
    p5_quote: float | None  # what that costs, in money
    worst_preset: str | None
    worst_preset_quote: float | None
    exit_cost_bps: float | None
    exit_fills: bool
    thin_share: float | None  # how often the archive could not take this size now
    regime_label: str | None
    events: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    headline: str = ""
    attention: float = 0.0
    forecast_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "events": list(self.events), "flags": list(self.flags)}


@dataclass(frozen=True)
class Tonight:
    as_of: datetime
    window_end: datetime | None
    hours: float
    market_is_open: bool
    items: list[Watch] = field(default_factory=list)
    gross_quote: float = 0.0
    tail_quote: float | None = None  # the book's own bad case, correlations included
    summary: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "hours": self.hours,
            "market_is_open": self.market_is_open,
            "items": [i.to_dict() for i in self.items],
            "gross_quote": self.gross_quote,
            "tail_quote": self.tail_quote,
            "summary": self.summary,
            "note": self.note,
        }


def window(as_of: datetime | None = None) -> tuple[datetime | None, float, bool]:
    """The stretch between now and the next US regular open.

    While the market is open there is no overnight window yet, and the honest answer is
    to say so and measure to the close instead: a position held into the close is the one
    that will be carried overnight, so the numbers are still the ones that matter.
    """
    at = ensure_utc(as_of or utc_now())
    info = classify_session(at)
    if info.is_closed:
        end = info.regular_open_utc
        return end, max(0.5, (end - at).total_seconds() / 3600.0), False
    end = info.regular_close_utc
    return end, max(0.5, (end - at).total_seconds() / 3600.0), True


def _events(features: dict[str, float | None], hours: float) -> tuple[list[str], list[str]]:
    """What lands inside the window, said the way a person would say it."""
    said: list[str] = []
    flags: list[str] = []
    limit = hours + EVENT_HOURS

    to_earnings = features.get("hours_to_earnings")
    if to_earnings is not None and to_earnings <= limit:
        said.append(f"earnings in {to_earnings:.0f}h, inside this window")
        flags.append("earnings_in_window")

    since_filing = features.get("hours_since_filing")
    if since_filing is not None and since_filing <= 24:
        said.append(f"an SEC filing landed {since_filing:.0f}h ago")
        flags.append("fresh_filing")

    to_fomc = features.get("hours_to_fomc")
    if to_fomc is not None and to_fomc <= limit:
        said.append(f"an FOMC decision in {to_fomc:.0f}h")
        flags.append("fomc_in_window")

    macro = features.get("macro_events_72h")
    if macro and macro >= 2:
        said.append(f"{macro:.0f} macro releases within three days")

    return said, flags


def _headline(w: dict[str, Any]) -> str:
    """One sentence, leading with whichever thing is actually wrong."""
    money = f"{abs(w['p5_quote']):,.0f} USDT" if w.get("p5_quote") is not None else "an unknown amount"
    if "earnings_in_window" in w["flags"]:
        return f"Earnings land while you hold it. The calibrated bad case over the window is {money}."
    if "cannot_exit" in w["flags"]:
        return f"The book will not absorb this size right now. The bad case over the window is {money}."
    if "thin_book" in w["flags"]:
        return f"At these hours the book often cannot take this size. The bad case over the window is {money}."
    if "fomc_in_window" in w["flags"]:
        return f"An FOMC decision lands while you hold it. The bad case over the window is {money}."
    if "fresh_filing" in w["flags"]:
        return f"A filing has just landed. The bad case over the window is {money}."
    if "wide_tail" in w["flags"]:
        return f"The overnight band is wider than usual here: one night in twenty costs {money} or more."
    if "hostile_regime" in w["flags"]:
        return f"A hostile regime, with {money} in the bad case over the window."
    return f"Nothing unusual. One night in twenty costs {money} or more."


def judge(
    ticker: str,
    side: str,
    notional_quote: float,
    *,
    p5_pct: float | None,
    features: dict[str, float | None],
    labels: dict[str, str],
    hours: float,
    worst_preset: tuple[str, float] | None = None,
    exit_cost_bps: float | None = None,
    exit_fills: bool = True,
    thin_share: float | None = None,
    forecast_id: int | None = None,
) -> Watch:
    """One position, judged. Everything here is handed in; nothing is fetched."""
    said, flags = _events(features, hours)

    regime = labels.get("regime_label")
    if regime == "hostile":
        flags.append("hostile_regime")
    if not exit_fills:
        flags.append("cannot_exit")
    elif thin_share is not None and thin_share >= THIN_SHARE:
        flags.append("thin_book")
    if p5_pct is not None and abs(p5_pct) >= WIDE_TAIL_PCT:
        flags.append("wide_tail")

    p5_quote = None if p5_pct is None else notional_quote * p5_pct / 100.0

    # Attention is money first: the tail this position actually carries, raised by each
    # thing that makes the tail an understatement. A big quiet position outranks a small
    # noisy one, which is the order a person would work down the list in.
    attention = abs(p5_quote or 0.0)
    for flag, multiplier in (("earnings_in_window", 2.0), ("cannot_exit", 2.0), ("fomc_in_window", 1.6), ("thin_book", 1.5), ("fresh_filing", 1.4), ("hostile_regime", 1.3)):
        if flag in flags:
            attention *= multiplier

    w = Watch(
        ticker=ticker, side=side, notional_quote=notional_quote,
        p5_pct=p5_pct, p5_quote=p5_quote,
        worst_preset=worst_preset[0] if worst_preset else None,
        worst_preset_quote=worst_preset[1] if worst_preset else None,
        exit_cost_bps=exit_cost_bps, exit_fills=exit_fills, thin_share=thin_share,
        regime_label=regime, events=tuple(said), flags=tuple(dict.fromkeys(flags)),
        attention=attention, forecast_id=forecast_id,
    )
    return Watch(**{**w.__dict__, "headline": _headline(w.to_dict())})


def summarise(items: list[Watch], hours: float, market_is_open: bool) -> str:
    if not items:
        return "Nothing held, so nothing to watch. Add what you are carrying and this page will tell you which of it needs you tonight."
    worst = items[0]
    tails = sum(abs(i.p5_quote or 0.0) for i in items)
    when = "before the close" if market_is_open else "before the open"
    flagged = [i for i in items if i.flags and i.flags != ("wide_tail",)]
    if not flagged:
        return (
            f"{len(items)} position{'' if len(items) == 1 else 's'} over the next {hours:.0f} hours. "
            f"Nothing needs you {when}: added up, the bad case across them is {tails:,.0f} USDT."
        )
    # The headline's first sentence, as written: lowercasing it turns USDT into usdt and
    # runs two sentences together.
    lead = worst.headline.split(". ")[0].rstrip(".")
    return (
        f"{len(items)} position{'' if len(items) == 1 else 's'} over the next {hours:.0f} hours, "
        f"{len(flagged)} of which want a look {when}. Start with {worst.ticker} - {lead}."
    )


def build(
    as_of: datetime | None,
    judged: list[Watch],
    *,
    tail_quote: float | None = None,
    note: str = "",
) -> Tonight:
    """Rank what has been judged and say what it adds up to."""
    at = ensure_utc(as_of or utc_now())
    end, hours, open_now = window(at)
    items = sorted(judged, key=lambda w: w.attention, reverse=True)
    return Tonight(
        as_of=at,
        window_end=end,
        hours=hours,
        market_is_open=open_now,
        items=items,
        gross_quote=sum(abs(i.notional_quote) for i in items),
        tail_quote=tail_quote,
        summary=summarise(items, hours, open_now),
        note=note,
    )


def stale(as_of: datetime, bar_ts: datetime, limit_h: float = 6.0) -> bool:
    """Whether a token's own data is too old for tonight's answer to mean anything."""
    return (ensure_utc(as_of) - ensure_utc(bar_ts)) > timedelta(hours=limit_h)
