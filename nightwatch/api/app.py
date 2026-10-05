"""FastAPI application.

The API is a thin layer over the pipeline: it owns the store connection, the
universe, the journal and the feature-frame cache, and exposes analysis, snapshots,
calibration and a chat endpoint. All heavy work runs in the threadpool (plain ``def``
endpoints), so one long analysis never blocks health checks.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from nightwatch import __version__
from nightwatch.api import followup, guard
from nightwatch.api.locking import RequestFirstLock
from nightwatch.api.sources import annotate_used_for, data_sources, open_interest_row, options_row, rwa_row, street_row
from nightwatch.config import Settings, load_settings
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.models import Venue
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry, build_universe
from nightwatch.decision import tonight as tonight_mod
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.features.snapshot import InsufficientData, build_snapshot
from nightwatch.journal.calibration import calibrate
from nightwatch.journal.journal import Journal
from nightwatch.journal.postmortem import LessonBook, mature_and_learn
from nightwatch.journal.reports import ReportStore
from nightwatch.pipeline.analyze import AnalysisContext, analyze
from nightwatch.pipeline.render import render_text
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import UTC, utc_now

log = logging.getLogger(__name__)

# Past this, the API's read snapshot is stuck behind the recorder (see Store.snapshot_lag_seconds).
STALE_SNAPSHOT_S = 600.0
# Well before that, the API repairs it itself: a fresh connection, no restart. A minute
# between checks; the replaced connection is closed once no read can still be using it.
SELF_HEAL_LAG_S = 180.0
SNAPSHOT_CHECK_S = 60.0
RETIRE_GRACE_S = 300.0
HEALTH_COUNTS_TTL_S = 600.0
_health_counts: dict[int, dict[str, Any]] = {}
# How often the idle API re-reads its cached frames so they are not swapped out.
TOUCH_EVERY_S = 180.0
# Open interest is read from cache for five minutes; refreshing a little sooner keeps it always warm.
PERP_CONTEXT_EVERY_S = 240.0
CALIBRATION_TTL_SEC = 120
PAGE_CACHE_MAX = 200
CALIBRATION_CACHE_MAX = 100
THESIS_CHECK_CACHE_MAX = 200
# Query params that change what a cached page shows; anything else is not cached, so a
# caller cannot grow the cache with made-up parameters.
PAGE_CACHE_PARAMS = frozenset({"core", "ticker", "kind", "limit"})
PAGE_CACHE_TTL_S = 60.0
PAGE_CACHE_STALE_S = 6 * 3600.0  # beyond this a saved page is too old to show even while refreshing


def _closed_hours_slim() -> dict[str, Any] | None:
    from nightwatch.journal import closed_hours

    res = closed_hours.load_result()
    return closed_hours.slim(res) if res else None


# The warm-up steps aside for requests, but not forever: a steady stream of them must not
# leave every other token cold.
WARM_YIELD_MAX_S = 30.0

CACHED_PAGES = ("/sources", "/studies", "/calibration", "/misses", "/verify", "/anchors")


MAX_NOTIONAL = 10_000_000


class PositionIn(BaseModel):
    ticker: str = Field(max_length=32)
    side: Side = Side.LONG
    notional_quote: float = Field(gt=0, le=MAX_NOTIONAL)


class TicketIn(BaseModel):
    ticker: str = Field(max_length=32)
    side: Side = Side.LONG
    notional_quote: float = Field(gt=0, le=MAX_NOTIONAL)
    account_equity_quote: float | None = Field(default=None, gt=0, le=MAX_NOTIONAL * 100)
    horizon_kind: HorizonKind = HorizonKind.NEXT_OPEN
    horizon_hours: float | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str = ""
    invalidation: str = ""
    hedge_ratio: float | None = Field(default=None, ge=0, le=1)
    # Leverage on the stock's Bitget perpetual; adds the liquidation price and how often
    # history reached it. None or 1 is a plain token position.
    leverage: float | None = Field(default=None, ge=1, le=125)
    as_of: datetime | None = None
    record: bool = True
    open_positions: list[PositionIn] = Field(default_factory=list, max_length=20)
    # Named conditions narrowing which past moments count as comparable. Unknown names
    # are dropped by the engine rather than rejected, so a stale client cannot 422.
    lenses: list[str] = Field(default_factory=list)
    # False asks for the unfiltered answer even on a night the desk would narrow itself.
    auto_lens: bool = True

    def to_ticket(self) -> TradeTicket:
        return TradeTicket(
            ticker=self.ticker.upper(), side=self.side, notional_quote=self.notional_quote, account_equity_quote=self.account_equity_quote,
            horizon_kind=self.horizon_kind, horizon_hours=self.horizon_hours, entry_price=self.entry_price, stop_price=self.stop_price,
            target_price=self.target_price, thesis=self.thesis, invalidation=self.invalidation, hedge_ratio=self.hedge_ratio,
            leverage=self.leverage, open_positions=tuple((p.ticker.upper(), p.side.value, p.notional_quote) for p in self.open_positions),
            lenses=tuple(self.lenses), auto_lens=self.auto_lens,
        )


class ChatMessage(BaseModel):
    role: str = Field(max_length=32)
    content: str = Field(max_length=2000)


class TonightIn(BaseModel):
    positions: list[PositionIn] = Field(default_factory=list, max_length=20)
    account_equity_quote: float | None = Field(default=None, gt=0, le=MAX_NOTIONAL * 100)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(max_length=30)
    account_equity_quote: float | None = Field(default=None, gt=0, le=MAX_NOTIONAL * 100)
    # The report the conversation is currently about, so a question can be answered from
    # it. The desk already stores every report it produces; this is the key to one.
    context_forecast_id: int | None = None


class FeedbackIn(BaseModel):
    forecast_id: int
    useful: bool
    note: str = Field(default="", max_length=500)
    lang: str = "en"


class WatchIn(BaseModel):
    forecast_id: int
    webhook: str | None = Field(default=None, max_length=500)
    lang: str = "en"


class TripwireIn(BaseModel):
    forecast_id: int
    level: float = Field(gt=0, lt=1e9)
    label: str = Field(default="custom", max_length=20)
    webhook: str | None = Field(default=None, max_length=500)
    lang: str = "en"


class PlanIn(BaseModel):
    forecast_id: int
    choices: dict[str, str] = Field(max_length=8)
    arm: bool = True
    webhook: str | None = Field(default=None, max_length=500)
    lang: str = "en"


class _BoundedCache(dict):
    """A dict that forgets its oldest entry past ``limit``, so a cache keyed on caller
    input cannot grow without end."""

    def __init__(self, limit: int):
        super().__init__()
        self._limit = limit

    def __setitem__(self, key, value):  # noqa: ANN001, ANN204
        self.pop(key, None)
        super().__setitem__(key, value)
        while len(self) > self._limit:
            del self[next(iter(self))]


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.entries: list[UniverseEntry] = build_universe(
            self.store.list_instruments(Venue.BITGET_SPOT), self.store.list_instruments(Venue.BITGET_UMCBL), settings.core_tickers
        )
        self.journal = Journal(self.store)
        # Forecasts written before receipts existed, or by a bulk import, are chained now.
        from nightwatch.journal import engagement, plans, receipts, tripwires, watches

        self.store._conn.executescript(engagement.SCHEMA)
        self.store._conn.executescript(plans.SCHEMA)
        self.store._conn.executescript(watches.SCHEMA)
        self.store._conn.executescript(tripwires.SCHEMA)
        chained = receipts.chain_pending(self.store._conn)
        if chained:
            log.info("chained %d forecasts that had no receipt", chained)
        self.reports = ReportStore(self.store)
        from nightwatch.api.analyst import AnalystJobs

        self.analyst = AnalystJobs()
        from nightwatch.api.agent import AgentJobs

        self.agent = AgentJobs()
        live = os.environ.get("NIGHTWATCH_LIVE_BOOK", "1") == "1"
        street_client = _street_client()
        self.ctx = AnalysisContext(
            store=self.store, entries=self.entries, journal=self.journal,
            spot_client=BitgetPublicClient(Venue.BITGET_SPOT, rate_per_sec=4) if live else None,
            perp_client=BitgetPublicClient(Venue.BITGET_UMCBL, rate_per_sec=4) if live else None,
            frame_cache_size=settings.frame_cache_size,
            street_client=street_client,
            bitget_data=_bitget_data(street_client),
            signal_client=_signal_client(),
            rwa_client=_rwa_client(),
            options_client=_options_client(),
        )
        # Serialises analyses that share the frame cache; people go before the warm-up.
        self.lock = RequestFirstLock()
        # Scoring the whole journal takes seconds; it only changes when forecasts mature.
        self.calibration_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = _BoundedCache(CALIBRATION_CACHE_MAX)
        self.warm_thread: threading.Thread | None = None
        self.warm_status: dict[str, Any] = {"state": "idle", "done": 0, "total": 0}
        # A what-if is a report the trader did not ask the desk to stand behind, so it is
        # not journalled and has no forecast id. It still has to be reachable, because the
        # next question is usually about it. Negative keys say which reports those are:
        # below zero means nothing was recorded and nothing will be scored.
        self._hypothetical = 0
        # When this process came up. The box redeploys on a cron, so "is the fix live
        # yet" has no answer from the outside without it - the routes do not change on
        # most deploys, and a stale container answers exactly like a fresh one.
        self.started_at = utc_now()
        self._lens_availability: tuple[datetime, dict[str, dict[str, int]]] | None = None
        self.snapshot_heals = 0
        self.thesis_checks: dict[tuple[int, str], dict[str, Any]] = _BoundedCache(THESIS_CHECK_CACHE_MAX)
        # The trade on screen re-run with the account the page sent, keyed by (report, account).
        self.equity_runs: dict[tuple[int, float], dict[str, Any]] = _BoundedCache(THESIS_CHECK_CACHE_MAX)

    def prefetch_take(self, forecast_id: int | None, payload: dict[str, Any], lang: str = "en") -> None:
        """Start the analyst's take now, in the report's own language, so it is usually
        written by the time the page asks. The page's later request joins this job."""
        if forecast_id is None or forecast_id < 0:
            return
        try:
            from nightwatch.api.providers import select

            self.analyst.prefetch(forecast_id, payload, select, "zh" if lang == "zh" else "en")
        except Exception as exc:  # noqa: BLE001 - a head start must never fail the analysis
            log.warning("could not prefetch the analyst take: %s", exc)

    def keep_hypothetical(self, payload: dict[str, Any]) -> int:
        """Store a report that was never journalled, under a key that says so."""
        with self.lock:
            self._hypothetical -= 1
            key = self._hypothetical
        payload["forecast_id"] = key
        self.reports.save(key, payload)
        return key

    def warm(self) -> None:
        tickers = self.ctx.tickers_with_data()
        self.warm_status = {"state": "running", "done": 0, "total": len(tickers)}
        end = utc_now()
        for i, t in enumerate(tickers, 1):
            try:
                with self.lock.background(max_wait_s=WARM_YIELD_MAX_S):
                    self.ctx.feature_frame(t, end)
            except Exception as exc:  # noqa: BLE001
                log.warning("warm %s failed: %s", t, exc)
            self.warm_status["done"] = i
        self.warm_status["state"] = "done"
    def pooled_lens_availability(self) -> dict[str, dict[str, int]]:
        """Hours and separate events per condition across every token, cached per hour."""
        from nightwatch.analog import lens as lens_mod

        key = utc_now().replace(minute=0, second=0, microsecond=0)
        if self._lens_availability and self._lens_availability[0] == key:
            return self._lens_availability[1]
        frames = {}
        for t in self.ctx.tickers_with_data():
            try:
                with self.lock:
                    frames[t] = self.ctx.feature_frame(t, utc_now())
            except (InsufficientData, KeyError):
                continue
        value = lens_mod.pooled_availability(frames, self.ctx.analog_config.min_separation_h)
        self._lens_availability = (key, value)
        return value

    def refresh_street(self) -> None:
        """Street context for every token, fetched in parallel.

        Network-bound and slow per call (the analyst feed takes 1-9 s), so a handful of
        workers fill the cache in seconds rather than a sequential minute or two, and it
        runs outside the analysis lock so a request arriving meanwhile is never held up.
        """
        from concurrent.futures import ThreadPoolExecutor

        tickers = self.ctx.tickers_with_data()
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="street") as pool:
            for t in tickers:
                pool.submit(self.ctx.street_for, t, max_age=timedelta(minutes=50))

    def refresh_bitget(self) -> None:
        """The rest of the Bitget catalogue for every token, one call at a time.

        Sequential on purpose: 24 tokens x 5 entries is 120 calls an hour, and the box has 1 GB
        and the service is flaky. ``BitgetData`` itself refuses a second call for the same
        token and entry inside an hour, so this is safe to run as often as the warm-up does."""
        bd = self.ctx.bitget_data
        if bd is None:
            return
        for t in self.ctx.tickers_with_data():
            bd.refresh_ticker(t)

    def refresh_signal(self) -> None:
        """The signal skill's reading for every token, one at a time: its backend is flaky
        and slow, so it gets no parallel load, and it runs outside the analysis lock."""
        for t in self.ctx.tickers_with_data():
            self.ctx.signal_for(t, max_age=timedelta(minutes=50), fetch=True)
        self.ctx.signal_health(max_age=timedelta(minutes=50))

    def refresh_rwa(self) -> None:
        """The Bitget Wallet listing for every token, one at a time, outside the analysis lock."""
        for t in self.ctx.tickers_with_data():
            self.ctx.rwa_for(t, max_age=timedelta(minutes=25), fetch=True)

    def refresh_options(self) -> None:
        """Option chains for every token, one at a time and outside the analysis lock: each
        download is 2-5 MB parsed in memory, and the box has 1 GB. A fresh entry is skipped."""
        for t in self.ctx.tickers_with_data():
            self.ctx.options_chain_for(t, fetch=True)

    def refresh_perp_context(self) -> None:
        """Bitget's margin tiers and open interest for every token's perpetual, ahead of time.

        A leveraged chat needs both. Fetched on the request path they cost the trader the
        exchange's answer time (and its retries during an outage) on top of the analysis; here
        they are fetched with no one waiting, and the request reads the cache."""
        for t in self.ctx.tickers_with_data():
            try:
                sym = self.ctx.spec(t).perp_symbol
                if sym:
                    self.ctx.margin_tiers(sym, wait_s=30.0)
                    self.ctx.open_interest_for(sym, ttl=timedelta(seconds=1))
            except Exception as exc:  # noqa: BLE001 - warming must never stop the warm loop
                log.info("could not warm perp context for %s: %s", t, exc)

    def perp_context_forever(self) -> None:
        """Keep that cache fresh: tiers are good for a day, open interest for five minutes."""
        while True:
            self.refresh_perp_context()
            threading.Event().wait(PERP_CONTEXT_EVERY_S)

    def warm_forever(self) -> None:
        """Warm now, then again just after every hour boundary.

        Frames are keyed by end-hour, so at the top of each hour every token goes cold and
        the first request for it pays a few seconds. A judge's first click should not be
        the one that pays, so the cache is refilled in the background before they arrive."""
        while True:
            if self.ctx.street_client is not None:
                threading.Thread(target=self.refresh_street, name="street-refresh", daemon=True).start()
            if self.ctx.bitget_data is not None:
                threading.Thread(target=self.refresh_bitget, name="bitget-refresh", daemon=True).start()
            if self.ctx.signal_client is not None:
                threading.Thread(target=self.refresh_signal, name="signal-refresh", daemon=True).start()
            if self.ctx.rwa_client is not None:
                threading.Thread(target=self.refresh_rwa, name="rwa-refresh", daemon=True).start()
            if self.ctx.options_client is not None:
                threading.Thread(target=self.refresh_options, name="options-refresh", daemon=True).start()
            self.warm()
            self.warm_pages()
            now = utc_now()
            next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1, seconds=45))
            # Between rebuilds, keep the frames resident: warm is not the same as in
            # memory on a box that swaps. See AnalysisContext.touch_frames.
            while (wait := (next_hour - utc_now()).total_seconds()) > 0:
                threading.Event().wait(min(TOUCH_EVERY_S, max(1.0, wait)))
                try:
                    self.ctx.touch_frames()
                except RuntimeError:
                    pass  # the cache changed under us; the next pass catches it

    def warm_pages(self) -> None:
        """Ask this API for the pages a judge opens first, so their cache is full before
        anyone arrives. Best effort: the port is the one the container serves on."""
        import urllib.request

        for path in CACHED_PAGES:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{os.environ.get('PORT', '8000')}{path}", timeout=120).read()
            except Exception:  # noqa: BLE001 - warming must never stop the warm loop
                log.info("could not warm %s", path)

    def check_snapshot(self) -> bool:
        """Swap the shared connection if its read snapshot is stuck. True when it did.

        An unfinished statement somewhere keeps the shared connection reading the database
        as it was: once the API served a four-hour-old order book that way. Until the
        statement is found, the repair is to stop using that connection. The log line
        names what held a cursor and what every thread was doing, which is the evidence
        for finding it."""
        lag = self.store.snapshot_lag_seconds()
        self.store.close_retired(RETIRE_GRACE_S)
        if lag <= SELF_HEAL_LAG_S:
            return False
        from nightwatch.data.store import open_cursor_report

        log.error("read snapshot %.0f s behind the database; reconnecting. Evidence: %s", lag, open_cursor_report())
        self.store.reconnect()
        self.snapshot_heals += 1
        return True

    def watch_snapshot_forever(self) -> None:
        while True:
            threading.Event().wait(SNAPSHOT_CHECK_S)
            try:
                self.check_snapshot()
            except Exception as exc:  # noqa: BLE001 - the watchdog must outlive one bad check
                log.warning("snapshot check failed: %s", exc)

    def start_warm(self) -> None:
        if self.ctx.perp_client is not None:
            threading.Thread(target=self.perp_context_forever, name="perp-context", daemon=True).start()
        self.warm_thread = threading.Thread(target=self.warm_forever, name="warm-frames", daemon=True)
        self.warm_thread.start()
        threading.Thread(target=self.watch_snapshot_forever, name="snapshot-watch", daemon=True).start()

    def close(self) -> None:
        self.store.close()


def _thesis_check(s: AppState, forecast_id: int, report: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """The reason check for one stored report, cached. Shared by its route and the chat."""
    from nightwatch.api import whatif
    from nightwatch.api.providers import select
    from nightwatch.decision import thesis_check

    lang = "zh" if lang == "zh" else "en"
    key = (forecast_id, lang)
    hit = s.thesis_checks.get(key)
    if hit is not None:
        return hit
    ticket = report.get("ticket") or {}
    try:
        provider = select()
    except Exception:  # noqa: BLE001 - no model means the keyword check, not an error
        provider = None
    got = thesis_check.check(
        s.store._conn, ticker=str(ticket.get("ticker") or ""), thesis=str(ticket.get("thesis") or ""),
        as_of=whatif.as_of_of(report) or utc_now(), parse=thesis_check.parser_for(provider) if provider else None,
        model=getattr(provider, "model", None), lang=lang,
    ).to_dict()
    # A keyword result while a model exists means the model call failed this time; the
    # next visit should get another try rather than the fallback for good.
    if got["method"] != "keyword" or provider is None:
        s.thesis_checks[key] = got
    return got


def _street_client():  # noqa: ANN202
    """Bitget's US-stock data service, unless turned off (NIGHTWATCH_BITGET_MCP=0)."""
    if os.environ.get("NIGHTWATCH_BITGET_MCP", "1") != "1":
        return None
    from nightwatch.data.bitget_mcp import BitgetMcpClient

    return BitgetMcpClient()


def _bitget_data(client):  # noqa: ANN001, ANN202
    """The cache over the rest of Bitget's catalogue, sharing the street feed's client (one session)."""
    if client is None:
        return None
    from nightwatch.features.bitget_data import BitgetData

    return BitgetData(client=client)


def _options_client():  # noqa: ANN202
    """Cboe's delayed option quotes, unless turned off (NIGHTWATCH_CBOE_OPTIONS=0)."""
    if os.environ.get("NIGHTWATCH_CBOE_OPTIONS", "1") != "1":
        return None
    from nightwatch.data.cboe import CboeOptionsClient

    return CboeOptionsClient()


def _rwa_client():  # noqa: ANN202
    """Bitget Wallet's tokenized-stock market data, unless turned off (NIGHTWATCH_BITGET_RWA=0)."""
    if os.environ.get("NIGHTWATCH_BITGET_RWA", "1") != "1":
        return None
    from nightwatch.data.bitget_rwa import BitgetRwaClient

    return BitgetRwaClient()


def _signal_client():  # noqa: ANN202
    """Bitget's bitget-signal Skill backend, unless turned off (NIGHTWATCH_BITGET_SIGNAL=0)."""
    if os.environ.get("NIGHTWATCH_BITGET_SIGNAL", "1") != "1":
        return None
    from nightwatch.data.bitget_signal import BitgetSignalClient

    return BitgetSignalClient()


def _with_holdings(state: Any, context: dict[str, Any], text: str, tickers: list[str]) -> dict[str, Any] | None:  # noqa: ANN401
    """Re-run the trade on screen with the holdings a message states, when that is all it says."""
    import json

    from nightwatch.api import intake, whatif

    parsed = intake.parse_message(text, tickers)
    if not parsed.open_positions or parsed.ticker or parsed.notional_quote:
        return None
    base = whatif.ticket_from(context)
    if base is None:
        return None
    from dataclasses import replace as _replace

    ticket = _replace(base, open_positions=tuple(intake.merge_positions(list(base.open_positions), parsed.open_positions)))
    with state.lock:
        report = analyze(state.ctx, ticket, as_of=whatif.as_of_of(context), record=False)
        payload = report.to_dict()
    state.keep_hypothetical(payload)
    narrative = intake.brief_short(report, intake.language_of(text))
    return {
        "intent": {"kind": "what_if", "missing_fields": [], "reply": narrative},
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)), "report": payload, "report_text": None,
        "narrative": narrative, "unverified_numbers": [], "reply": narrative, "mode": "what_if", "answer_kind": "book",
        "answered_about": context.get("forecast_id"), "written_by": "rules",
    }


def _what_if(state: AppState, context: dict[str, Any], question: str) -> dict[str, Any] | None:
    """Answer a counterfactual by running it, or return None if it is not one.

    The report on the screen is a fixed object: it can be quoted and rearranged, and
    that is what the follow-up layer does. A question like "was it worse on earnings
    nights" is not a rearrangement of it - it is a different report - so the desk runs
    one against the same moment and reports what moved.

    Two guards keep this from answering the wrong question well. The model only fills
    fields from a fixed schema, so it can name a change but never invent a computation.
    And an empty change - the model saying "they are asking about the trade as it is" -
    hands the question straight back to the layer that reads the report.

    The re-run is not journalled. A what-if is a forecast nobody took, and a cohort
    narrowed by a lens is a different estimator from the one that sizes real trades;
    scoring them together would corrupt the calibration that both depend on.
    """
    import json

    from nightwatch.api import whatif
    from nightwatch.api.llm import parse_change
    from nightwatch.api.providers import select

    base = whatif.ticket_from(context)
    if base is None:
        return None
    tickers = list(state.ctx.tickers_with_data())
    if not whatif.looks_like_a_what_if(question, tickers=tuple(tickers), current=base.ticker):
        return None
    # "What's the fear and greed reading" shares a word with the "market nervous"
    # condition but asks about the report, not for a different one.
    if any(kind in ("street", "corporate") and pattern.search(question) for kind, pattern, _ in followup.ROUTES):
        return None
    # Rules first: the common changes are shapes the intake rules already read, in
    # milliseconds. The model, which takes 10-60 s, is asked only when they find none.
    change = whatif.rule_change(question, context.get("ticket") or {}, tickers, ((context.get("snapshot") or {}).get("features") or {}))
    # "What if it gaps down 10%" and "what if I halve it" are not a different report; the
    # one on screen answers them in milliseconds. Asking the model to name a change for
    # them costs seconds and can come back as something adjacent, like "short instead".
    if change.empty and (followup.SHOCK.search(question) or followup._SIZE_FACTOR.search(question)):
        return None
    if change.empty and change.note:
        return {"intent": {"kind": "what_if", "missing_fields": [], "reply": change.note}, "ticket": None, "report": None,
                "report_text": None, "narrative": change.note, "unverified_numbers": [], "reply": change.note, "mode": "what_if"}
    provider = None
    if change.empty:
        provider = select()
        if provider is None:
            return None
        change = parse_change(provider, question, context.get("ticket") or {}, tickers)
    if change.empty:
        return None

    from dataclasses import replace

    from nightwatch.api import desk_help
    from nightwatch.api.intake import language_of

    cap_note = None
    if change.leverage and change.leverage > 1:
        # "what about 500x?": run at what Bitget allows for this size and say so, never refuse.
        cap = desk_help.leverage_cap(state, (change.ticker or base.ticker), change.notional_quote or base.notional_quote)
        if change.leverage > cap + 1e-9:
            cap_note = desk_help.leverage_cap_note(float(change.leverage), cap, language_of(question))
            change = replace(change, leverage=cap)
    ticket = change.apply_to(base, entry=((context.get("snapshot") or {}).get("prices") or {}).get("spot_close"))
    with state.lock:
        report = analyze(state.ctx, ticket, as_of=whatif.as_of_of(context), record=False)
        payload = report.to_dict()
    state.keep_hypothetical(payload)

    answer = whatif.compare(context, payload, change, language_of(question))
    if cap_note:
        answer = replace(answer, text=f"{cap_note} {answer.text}")
    return {
        "intent": {"kind": "what_if", "question": answer.kind, "missing_fields": [], "reply": answer.text},
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": payload,
        "report_text": None,
        "narrative": answer.text,
        # Nothing to verify: every number was copied out of one of the two reports by
        # code, not written by a model.
        "unverified_numbers": [],
        "reply": answer.text,
        "mode": "what_if",
        "answer_kind": "what_if",
        "answered_about": context.get("forecast_id"),
        "changed": {k: v for k, v in change.__dict__.items() if v},
        "parsed_by": provider.name if provider else "rules",
        "written_by": "rules",
        "provider": provider.name if provider else None,
        "model": provider.model if provider else None,
    }


def _with_account(state: AppState, context: dict[str, Any], equity: float) -> dict[str, Any] | None:
    """The trade on screen judged against the account the page sent with the request.

    A report made before the trader's account was known says "account equity not provided"
    to every follow-up, although the request carries it. The same trade is re-run at the
    same moment with that account (never journalled) and the follow-up is answered from it.
    Cached per (report, account), so a run of questions pays for one analysis.
    """
    from dataclasses import replace as _replace

    from nightwatch.api import whatif

    fid = context.get("forecast_id")
    key = (int(fid), float(equity)) if isinstance(fid, int) else None
    if key is not None and key in state.equity_runs:
        return state.equity_runs[key]
    base = whatif.ticket_from(context)
    if base is None:
        return None
    with state.lock:
        report = analyze(state.ctx, _replace(base, account_equity_quote=float(equity)), as_of=whatif.as_of_of(context), record=False)
        payload = report.to_dict()
    state.keep_hypothetical(payload)
    if key is not None:
        state.equity_runs[key] = payload
    return payload


def _plan_missing(context: dict[str, Any]) -> bool:
    """Whether the trade on screen is waiting on a written reason or a "wrong if" line."""
    for r in (context.get("gate") or {}).get("rules") or []:
        if r.get("rule") == "written_plan":
            return r.get("decision") != "GO"
    return False


def _capture_reason(state: AppState, context: dict[str, Any], latest: str, tickers: list[str], account_equity: float | None, *, check: bool) -> dict[str, Any] | None:
    """The reason and "wrong if" line a trader types, stored on the ticket and re-run.

    The desk asks for "because ..., wrong if it closes below ...". Typed back, it used to be
    read as an account size or a what-if and dropped, so the review never cleared. Here the
    two phrases go onto the ticket of the trade on screen, which is run again at the same
    moment (never journalled, like any what-if), and the reply says what moved - or what is
    still missing. With ``check`` the reason is then held against the stored headlines.
    """
    import json
    from dataclasses import replace as _replace

    from nightwatch.api import intake, thesis_capture, whatif

    reason = thesis_capture.read(latest)
    base = whatif.ticket_from(context)
    if not reason or base is None:
        return None
    lang = intake.language_of(latest)
    zh = lang == "zh"
    said = intake.parse_message(latest, tickers)
    equity = said.account_equity_quote or base.account_equity_quote or account_equity
    ticket = _replace(base, thesis=reason.thesis or base.thesis, invalidation=reason.invalidation or base.invalidation, account_equity_quote=equity)
    with state.lock:
        report = analyze(state.ctx, ticket, as_of=whatif.as_of_of(context), record=False)
        payload = report.to_dict()
    fid = state.keep_hypothetical(payload)

    parts = []
    if reason.thesis:
        parts.append("你的理由" if zh else "your reason")
    if reason.invalidation:
        parts.append("你的『错在哪里』" if zh else 'your "wrong if" line')
    if equity and equity != base.account_equity_quote:
        parts.append(f"账户 {equity:,.0f} USDT" if zh else f"an account of {equity:,.0f} USDT")
    what = ("、" if zh else ", ").join(parts[:-1]) + (" 和 " if zh else " and ") + parts[-1] if len(parts) > 1 else parts[0]
    saved = []
    if reason.thesis:
        saved.append(f"理由：“{reason.thesis}”" if zh else f'reason: "{reason.thesis}"')
    if reason.invalidation:
        saved.append(f"错在：“{reason.invalidation}”" if zh else f'wrong if: "{reason.invalidation}"')
    lead = ("已记在这笔交易上：" + "；".join(saved) + "。") if zh else ("Saved on this ticket - " + "; ".join(saved) + ".")
    answer = whatif.compare(context, payload, whatif.Change(account_equity_quote=equity if equity != base.account_equity_quote else None), lang, what=what)
    text = lead + ("" if zh else " ") + answer.text
    still = [x for x in payload["gate"]["rules"] if x["rule"] == "written_plan" and x["decision"] != "GO"]
    if still:
        missing_thesis = not ticket.thesis.strip()
        text += (
            (" 还缺：你的理由（“因为……”）。" if missing_thesis else " 还缺：什么情况说明你错了（“如果收盘跌破……就算错”）。") if zh
            else (' Still missing: your reason ("because ...").' if missing_thesis else ' Still missing: what would prove you wrong ("wrong if it closes below ...").')
        )
    kind = "thesis_saved"
    if check and reason.thesis:
        from nightwatch.decision import thesis_check as _tc

        got = _thesis_check(state, fid, payload, lang)
        text = text + "\n\n" + _tc.reply_text(got, lang)
        kind = "thesis"
    return {
        "intent": {"kind": "what_if", "question": kind, "missing_fields": [], "reply": text},
        "ticket": json.loads(json.dumps(ticket.__dict__, default=str)),
        "report": payload, "report_text": None, "narrative": text, "unverified_numbers": [], "reply": text,
        "mode": "what_if", "answer_kind": kind, "answered_about": context.get("forecast_id"),
        "changed": {"thesis": bool(reason.thesis), "invalidation": bool(reason.invalidation), **({"account_equity_quote": equity} if equity and equity != base.account_equity_quote else {})},
        "parsed_by": "rules", "written_by": "rules",
    }


def _who(request: Request) -> tuple[str, str, bool]:
    """(salted client hash, language, is-internal) for a request. Nothing here is stored
    raw: the browser's random id, or failing that the address, is hashed at once."""
    from nightwatch.journal import engagement

    q, h = request.query_params, request.headers
    browser_id = h.get("x-nw-client") or q.get("nw_client")
    fwd = (h.get("x-forwarded-for") or "").split(",")[0].strip()
    address = fwd or (request.client.host if request.client else "")
    internal = (h.get("x-nw-internal") or q.get("nw_internal") or "") == "1"
    return engagement.hash_client(browser_id, address), engagement.norm_lang(h.get("x-nw-lang") or q.get("nw_lang") or q.get("lang")), internal


# Seconds of silence after which the chat stream sends a comment line. Well under every idle
# limit a proxy applies (typically 30-60 s), so a slow turn is never mistaken for a dead one.
STREAM_KEEPALIVE_S = 5.0


def create_app(settings: Settings | None = None, *, warm: bool = True) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = AppState(settings)
        app.state.nw = state
        if warm:
            state.start_warm()
        # The Telegram bot lives in this process (it needs the desk); a no-op without
        # TELEGRAM_BOT_TOKEN. It shares the chat code and the rate limiter with the web.
        from nightwatch.api import telegram_bot

        app.state.telegram = telegram_bot.start_if_configured(state, _telegram_chat, limiter)
        try:
            yield
        finally:
            if app.state.telegram is not None:
                app.state.telegram.stop()
            state.close()

    app = FastAPI(title="Nightwatch", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("NIGHTWATCH_CORS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

    limiter = guard.RateLimiter()

    # The read-only pages a judge opens first each recompute from the database in 2-7 s on
    # a cold box. They change slowly, so a successful answer is kept for a minute and the
    # warm-up fills them before anyone asks (AppState.warm_pages).
    page_cache: dict[str, tuple[float, bytes, str]] = {}
    refreshing_keys: set[str] = set()

    def _refresh_later(key: str) -> None:
        if key in refreshing_keys:
            return
        refreshing_keys.add(key)

        def run() -> None:
            import urllib.request

            try:
                req = urllib.request.Request(f"http://127.0.0.1:{os.environ.get('PORT', '8000')}{key}", headers={"x-nw-refresh": "1"})
                urllib.request.urlopen(req, timeout=120).read()
            except Exception:  # noqa: BLE001 - the stale copy keeps serving
                log.info("background refresh of %s failed", key)
            finally:
                refreshing_keys.discard(key)

        threading.Thread(target=run, name="page-refresh", daemon=True).start()

    @app.middleware("http")
    async def cache_slow_pages(request: Request, call_next):  # noqa: ANN001, ANN202
        path = request.url.path
        if request.method != "GET" or path not in CACHED_PAGES:
            return await call_next(request)
        # The anonymous visitor id and language travel as query params; they do not change
        # these pages, and keyed on them every visitor got a cold, uncached page.
        query = "&".join(f"{k}={v}" for k, v in sorted(request.query_params.multi_items()) if not k.startswith("nw_"))
        key = path + "?" + query
        cacheable = all(k.startswith("nw_") or k in PAGE_CACHE_PARAMS for k in request.query_params)
        hit = page_cache.get(key)
        refreshing = request.headers.get("x-nw-refresh") == "1"
        if hit and not refreshing:
            age = time.monotonic() - hit[0]
            if age >= PAGE_CACHE_TTL_S and age < PAGE_CACHE_STALE_S:
                # Serve the saved answer now and refresh it behind the reader's back, so no
                # visitor waits the 6-8 s a recompute takes on this box.
                _refresh_later(key)
            if age < PAGE_CACHE_STALE_S:
                return Response(hit[1], media_type=hit[2], headers={"x-nightwatch-cache": "hit" if age < PAGE_CACHE_TTL_S else "stale"})
        response = await call_next(request)
        if response.status_code != 200:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if cacheable:
            page_cache.pop(key, None)
            page_cache[key] = (time.monotonic(), body, response.media_type or "application/json")
            while len(page_cache) > PAGE_CACHE_MAX:
                page_cache.pop(next(iter(page_cache)))
        return Response(body, status_code=200, media_type=response.media_type or "application/json", headers={"x-nightwatch-cache": "miss"})

    # Registered after the page cache on purpose: the last middleware added runs first, so
    # the secret and the rate limit apply to cached answers too.
    @app.middleware("http")
    async def protect(request: Request, call_next):  # noqa: ANN001, ANN202
        """Proxy secret first, then the per-client rate limit (see nightwatch.api.guard)."""
        method, path = request.method, request.url.path
        peer = request.client.host if request.client else ""
        local = guard.is_local(peer)
        secret = guard.proxy_secret()
        trusted = bool(secret) and guard.secret_ok(request.headers, secret)
        if secret and not trusted and not local and not (method in ("GET", "HEAD") and path == "/health"):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        if local or method == "OPTIONS":
            return await call_next(request)
        rule = guard.rule_for(method, path)
        if rule is not None:
            client = (request.headers.get(guard.CLIENT_IP_HEADER, "").strip() if trusted else "") or peer
            wait = limiter.take(rule[0], client[:64], rule[1], rule[2])
            if wait > 0:
                return JSONResponse({"detail": "Too many requests. Please wait a moment and try again."}, status_code=429, headers={"Retry-After": str(max(1, int(wait + 0.999)))})
        return await call_next(request)

    def st() -> AppState:
        return app.state.nw

    @app.get("/health")
    def health() -> Any:
        from nightwatch.api.providers import describe as describe_llm

        s = st()
        c = s.store._conn
        # A stuck read snapshot answers every request with old data and slows down as the
        # WAL grows behind it. Unhealthy is the honest answer: Docker marks the container,
        # and deploy/heal.sh restarts it within minutes instead of hours.
        lag = s.store.snapshot_lag_seconds()
        if lag > STALE_SNAPSHOT_S:
            from nightwatch.data.store import open_cursor_report

            log.error("API read snapshot is %.0f s behind the database; open cursors: %s", lag, open_cursor_report())
            return JSONResponse({"ok": False, "detail": f"read snapshot {lag:.0f} s behind the database"}, status_code=503)
        # Row counts are a second each over a million rows on the box, and Docker asks for
        # this page every 30 s; they change slowly, so they are counted every ten minutes.
        now_m = time.monotonic()
        counts = _health_counts.setdefault(id(s.store), {})  # per store, so test apps never share
        if now_m - counts.get("at", -1e9) > HEALTH_COUNTS_TTL_S:
            counts.update(
                at=now_m,
                bars=c.execute("SELECT COUNT(*) FROM bars").fetchone()[0],
                books=c.execute("SELECT COUNT(*) FROM orderbook_snapshots").fetchone()[0],
            )
        bars, n_books = counts["bars"], counts["books"]
        newest = s.store.latest_book_ms()
        last_book = datetime.fromtimestamp(newest / 1000, tz=UTC).isoformat() if newest else None
        # Which model is answering, not just whether one is. "chat_ready: true" with no
        # way to see who is behind it was how the box ran on the rule-based fallback for
        # days without anyone noticing.
        llm = describe_llm()
        return {
            "ok": True, "version": __version__, "time": utc_now().isoformat(), "snapshot_heals": s.snapshot_heals, "bars": bars, "orderbook_snapshots": n_books, "last_book_ts": last_book,
            "started_at": s.started_at.isoformat(), "uptime_s": int((utc_now() - s.started_at).total_seconds()),
            "tickers_with_data": len(s.ctx.tickers_with_data()), "warm": s.warm_status, "chat_ready": llm["ready"], "llm": llm,
            "bitget_mcp": s.ctx.street_status() if s.ctx.street_client is not None else None,
        }

    @app.post("/tonight")
    def tonight(body: TonightIn) -> dict[str, Any]:
        """What in this book needs looking at before the market opens again.

        One full analysis per position, over the window between now and the next regular
        open, so every number is the same number the desk would give if you asked about
        that position directly. That costs about a second and a half each; this is a page
        a person opens once in an evening, not something polled.
        """
        s = st()
        held = [p for p in body.positions if p.notional_quote and p.ticker]
        if not held:
            return tonight_mod.build(None, [], note="no positions given").to_dict()

        _, hours, _ = tonight_mod.window()
        known = set(s.ctx.tickers_with_data())
        judged: list[Any] = []
        skipped: list[str] = []
        for p in held[:12]:  # a book, not a portfolio; the page stays under twenty seconds
            ticker = p.ticker.upper()
            if ticker not in known:
                skipped.append(ticker)
                continue
            ticket = TradeTicket(
                ticker=ticker, side=Side(p.side), notional_quote=float(p.notional_quote),
                account_equity_quote=body.account_equity_quote,
                horizon_kind=HorizonKind.NEXT_OPEN,
                thesis="already held", invalidation="already held",
            )
            try:
                with s.lock:
                    report = analyze(s.ctx, ticket, record=False)
            except InsufficientData as exc:
                log.info("tonight: skipping %s (%s)", ticker, exc)
                skipped.append(ticker)
                continue

            horizon = (report.analog.horizons.get(report.primary_horizon) if report.analog else None)
            p5 = None
            if horizon is not None:
                p5 = horizon.loss_p5_pct

            priced = [(sc, im) for sc, im in zip(report.stress.presets, report.stress.impacts, strict=False) if im.total_pnl_quote is not None]
            worst = min(priced, key=lambda x: x[1].total_pnl_quote) if priced else None

            q = report.execution.exit_quote
            lh = report.execution.liquidity_history
            bucket = None
            if lh is not None and lh.buckets:
                # The bucket the window actually falls in, not the average of all of them.
                overnight = [b for b in lh.buckets if b.bucket in ("weeknight", "weekend", "friday_night", "sunday_night", "us_pre_market")]
                bucket = max(overnight, key=lambda b: b.share_below_reference or 0.0) if overnight else None

            judged.append(
                tonight_mod.judge(
                    ticker, p.side, float(p.notional_quote),
                    p5_pct=p5,
                    features=report.snapshot.features,
                    labels=report.snapshot.labels,
                    hours=hours,
                    worst_preset=(worst[0].name, worst[1].total_pnl_quote) if worst else None,
                    exit_cost_bps=q.total_cost_bps if q else None,
                    exit_fills=bool(q and q.fully_filled),
                    thin_share=bucket.share_below_reference if bucket else None,
                )
            )

        note = ""
        if skipped:
            note = "No data for " + ", ".join(sorted(set(skipped))) + "."
        if len(held) > 12:
            note = (note + " Only the first twelve positions were judged.").strip()
        return tonight_mod.build(None, judged, note=note).to_dict()

    @app.get("/lenses")
    def lenses(ticker: str | None = None) -> dict[str, Any]:
        """The conditions a search can be narrowed to, and what each costs in evidence.

        The cost is the point. Narrowing thins the comparable history fast, and a reader
        deciding whether to ask "only earnings nights" should be able to see that it
        leaves 1,752 hours across the universe and 96 in one token's own past.
        """
        from nightwatch.analog import lens as lens_mod

        s = st()
        cfg = s.ctx.analog_config
        # Below this many surviving hours the pipeline stops trusting one token's own
        # past and widens to the pooled history. The interface shows the same number so
        # the cost of a narrow question is visible before it is asked.
        out: dict[str, Any] = {
            "lenses": lens_mod.menu(),
            "counts": {},
            "floor_hours": int(cfg.min_matches * cfg.min_separation_h),
        }
        if ticker:
            try:
                with s.lock:
                    frame = s.ctx.feature_frame(ticker.upper(), utc_now())
                out["counts"] = lens_mod.sample_sizes(frame)
                out["history_hours"] = len(frame)
                # Which of them the present hour actually satisfies, so the interface can
                # offer the question a trader would think to ask rather than all seventeen.
                out["suggested"] = lens_mod.suggest_now(frame)
            except (InsufficientData, KeyError) as exc:
                out["note"] = str(exc)
        # Across every token: hours are not the constraint once the search pools, separate
        # events are. A condition with too few of them cannot be answered however many
        # hours it covers, and the interface should say so before it is asked.
        out["pooled"] = s.pooled_lens_availability()
        out["min_episodes"] = int(cfg.min_matches)
        return out

    @app.get("/studies")
    def studies() -> dict[str, Any]:
        """What the desk has tested about its own retrieval, and what came back.

        Served from stored results rather than computed on request: the match-level
        sweep behind half of these takes minutes, and a study that quietly recomputed
        itself differently every time nobody was looking would not be a study. The
        answer carries the date it was last run so a stale one is visible as stale.
        """
        from nightwatch.journal.fdr import annotate
        from nightwatch.journal.studies import StudyStore

        s = st()
        store = StudyStore(s.store)
        last = store.last_run()
        # Additive: each study also carries a p-value corrected for having asked many
        # questions. The stored verdicts are untouched.
        studies_out, fdr = annotate(store.all())
        return {
            "studies": studies_out,
            "fdr": fdr,
            "last_run": last.isoformat() if last else None,
            "note": "" if last else "No studies have been run against this database yet; run `nightwatch studies`.",
            # A measurement, not a test: kept out of the correction above so that the
            # count of questions asked stays the count of questions that were tests.
            "closed_hours": _closed_hours_slim(),
        }

    @app.get("/closed-hours/{ticker}")
    def closed_hours_for(ticker: str) -> dict[str, Any]:
        """How much of this token's movement happens while the US market is shut, and how
        much of its weekend moves Monday kept. From the committed measurement."""
        from nightwatch.journal import closed_hours

        return closed_hours.for_ticker(ticker.upper())

    @app.post("/mcp")
    async def mcp(request: Request) -> Response:
        """The desk as MCP tools, for Claude, Cursor or any other MCP client.

        Stateless streamable HTTP: one JSON-RPC message (or a batch) per POST, one JSON
        reply. See nightwatch.api.mcp_server for the tools and why they are shaped so.
        """
        from starlette.concurrency import run_in_threadpool

        from nightwatch.api.mcp_server import handle_body

        status, reply = await run_in_threadpool(handle_body, st(), await request.body())
        if reply is None:
            return Response(status_code=status)
        return JSONResponse(reply, status_code=status)

    @app.get("/mcp")
    def mcp_get() -> Response:
        # No server-initiated stream: every reply goes back on the POST that asked.
        return Response(status_code=405, headers={"allow": "POST"})

    @app.get("/sources")
    def sources() -> list[dict[str, Any]]:
        """Every feed the desk reads, with how fresh it is. Judges and users can check
        the numbers on a report are backed by live data, not a fixture."""
        s = st()
        out = data_sources(s.store)
        # Bitget's US-stock data has no table here: it is fetched per token, held in
        # memory for an hour, and never stored, because it describes today only.
        cached = [(ts, v) for ts, v in s.ctx._street.values()]
        if s.ctx.street_client is not None:
            out.append(street_row(cached, s.ctx.street_status(), utc_now()))
            # The same service, entry by entry: each catalogue entry the desk reads gets its own
            # row, with when it last delivered and whether it is working.
            from nightwatch.features.bitget_data import street_source_rows

            out.extend(street_source_rows(cached, s.ctx.street_status(), utc_now()))
            if s.ctx.bitget_data is not None:
                out.extend(s.ctx.bitget_data.source_rows(utc_now()))
        if s.ctx.perp_client is not None:
            out.append(open_interest_row(s.ctx._open_interest))
        if s.ctx.options_client is not None:
            out.append(options_row(s.ctx._options, s.ctx._options_failed))
        if s.ctx.rwa_client is not None:
            out.append(rwa_row(s.ctx._rwa))
        if s.ctx.signal_client is not None:
            health = s.ctx.signal_health()
            shown = [(ts, v) for ts, v in s.ctx._signal.values() if v and v.get("agrees")]
            newest = max((ts for ts, _ in shown), default=None)
            out.append({
                "key": "bitget_signal", "label": "Bitget signal skill backend",
                "what": "RSI (4h) from the bitget-signal technical-analysis tool, shown only when it agrees with our own RSI from Bitget candles. Only this tool is used, and the health count below probes exactly the calls the desk makes (RSI, MACD, full analysis). The skill's other tools (sentiment, news, macro, rates) timed out on every call on 4 Oct 2026, so nothing here relies on them.",
                "cadence": "hourly per token, in memory only", "last_update": newest.isoformat() if newest else None,
                "rows": len(shown), "latest": newest.isoformat() if newest else None,
                "latest_label": f"{health['answering']} of {health['tried']} tools answering" if health else "health check pending",
                "url": "https://datahub.noxiaohao.com/mcp",
            })
        return annotate_used_for(out)

    @app.get("/universe")
    def universe(core: bool = True) -> list[dict[str, Any]]:
        s = st()
        have = set(s.ctx.tickers_with_data())
        out = []
        for e in s.entries:
            if core and not e.is_core:
                continue
            out.append({"ticker": e.ticker, "spot_symbol": e.spot_symbol, "perp_symbol": e.perp_symbol, "is_core": e.is_core, "has_data": e.ticker in have})
        return out

    @app.get("/snapshot/{ticker}")
    def snapshot(ticker: str, as_of: datetime | None = None) -> dict[str, Any]:
        s = st()
        try:
            spec = s.ctx.spec(ticker)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return build_snapshot(s.store, spec, as_of).to_dict()
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/analyze")
    def analyze_endpoint(request: Request, body: TicketIn, text: bool = False) -> Any:
        s = st()
        try:
            ticket = body.to_ticket()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # Say which tokens exist rather than letting the pipeline fail on a symbol it
        # constructed hopefully: "no spot bars for RGMEUSDT in [...]" is a stack trace
        # wearing a hat, and this endpoint is public.
        known = s.ctx.tickers_with_data()
        if ticket.ticker not in set(known):
            raise HTTPException(404, f"{ticket.ticker} is not a tokenized stock this desk has data for. Available: {', '.join(sorted(known))}.")
        # A stop on the wrong side of the price is a typo, not a plan: say so now, in a
        # sentence, instead of after a minute of analysis that cannot use it.
        if ticket.stop_price:
            ref = ticket.entry_price or s.ctx.latest_spot_close(ticket.ticker, body.as_of)
            if ref and ticket.stop_is_on_correct_side(ref) is False:
                way, rel = ("long", "below") if ticket.closing_long else ("short", "above")
                raise HTTPException(422, f"A stop for a {way} must be {rel} the current price ({ref:,.2f}). You entered {ticket.stop_price:,.2f}.")
        try:
            with s.lock:
                report = analyze(s.ctx, ticket, as_of=body.as_of, record=body.record)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = report.to_dict()
        if report.forecast_id is not None and body.record:
            _mark(s, request, report.forecast_id)
        # Keep the finished report so a link can reopen it exactly as it was argued.
        if report.forecast_id is not None and body.record:
            try:
                s.reports.save(report.forecast_id, payload)
                s.prefetch_take(report.forecast_id, payload)
            except Exception as exc:  # noqa: BLE001 - a keepsake must not fail an analysis
                log.warning("could not store report %s: %s", report.forecast_id, exc)
        if text:
            return {"text": render_text(report), "forecast_id": report.forecast_id}
        return payload

    @app.post("/analyst/{forecast_id}")
    def analyst_start(forecast_id: int, lang: str = "en") -> dict[str, Any]:
        """Ask the model for the analyst's take on a stored report, in the background.

        Returns at once with the take's status; the page polls GET until it is done. The
        model reads a fact sheet built from the report and cannot change the verdict, and
        any sentence citing a number not on the sheet is removed before it is shown.
        """
        from nightwatch.api.providers import select

        s = st()
        report = s.reports.get(forecast_id)
        if report is None:
            raise HTTPException(404, f"No stored report {forecast_id}.")
        return s.analyst.start(forecast_id, report, select(), "zh" if lang == "zh" else "en").to_dict()

    @app.get("/analyst/{forecast_id}")
    def analyst_get(forecast_id: int, lang: str = "en") -> dict[str, Any]:
        take = st().analyst.get(forecast_id, "zh" if lang == "zh" else "en")
        return take.to_dict() if take else {"status": "none"}

    @app.post("/agent/{forecast_id}")
    def agent_start(forecast_id: int, lang: str = "en") -> dict[str, Any]:
        """Start the stress-test agent on a stored report: the model plans up to five tool
        calls against the desk's own engine and writes a cited conclusion. Poll GET."""
        from nightwatch.api.providers import select

        s = st()
        report = s.reports.get(forecast_id)
        if report is None:
            raise HTTPException(404, f"No stored report {forecast_id}.")
        run = s.agent.start(forecast_id, report, select(), s, "zh" if lang == "zh" else "en")
        return {"job": f"{forecast_id}:{run.lang}", "status": run.status}

    @app.get("/agent/{forecast_id}")
    def agent_get(forecast_id: int, lang: str = "en") -> dict[str, Any]:
        run = st().agent.get(forecast_id, "zh" if lang == "zh" else "en")
        return run.to_dict() if run else {"status": "none", "steps": [], "final": None, "removed": 0}

    @app.get("/reports/{forecast_id}")
    def stored_report(forecast_id: int) -> dict[str, Any]:
        """A report exactly as it was produced. The desk links to this so a verdict can
        be shown to someone else without asking them to trust a screenshot."""
        found = st().reports.get(forecast_id)
        if found is None:
            raise HTTPException(404, f"No stored report {forecast_id}. Only recent live tickets are kept, not replays.")
        return found

    @app.get("/thesis-check/{forecast_id}")
    def thesis_check_for(forecast_id: int, lang: str = "en") -> dict[str, Any]:
        """The trader's written reason, held against the headlines and SEC filings the desk
        had stored for the token before the report. See nightwatch.decision.thesis_check."""
        s = st()
        report = s.reports.get(forecast_id)
        if report is None:
            raise HTTPException(404, f"No stored report {forecast_id}.")
        return _thesis_check(s, forecast_id, report, lang)

    @app.get("/calibration")
    def calibration(ticker: str | None = None, kind: str | None = None) -> dict[str, Any]:
        s = st()
        key = (ticker or "", kind or "")
        cached = s.calibration_cache.get(key)
        if cached and (utc_now() - cached[0]).total_seconds() < CALIBRATION_TTL_SEC:
            return cached[1]
        with s.lock:
            matured, _ = mature_and_learn(s.journal, spot_symbol_for={e.ticker: e.spot_symbol for e in s.entries})
            df = s.journal.forecasts(ticker=ticker.upper() if ticker else None, kind=kind, matured_only=True)
        rep = calibrate(df)
        from dataclasses import asdict

        from nightwatch.journal.adjust import evaluate_expanding, expanding_rows
        from nightwatch.journal.freeze import holdout
        from nightwatch.journal.skill import compare_skill
        from nightwatch.journal.walkforward import by_period

        adjusted = evaluate_expanding(df) if not df.empty else None
        frozen = holdout(expanding_rows(df)) if not df.empty else holdout(pd.DataFrame())
        skill = compare_skill(df) if not df.empty else None
        walk = by_period(df) if not df.empty else None
        out = {
            "matured_now": matured, **asdict(rep), "adjusted": asdict(adjusted) if adjusted else None,
            "skill": asdict(skill) if skill else None, "walk_forward": asdict(walk) if walk else None,
            "since_freeze": frozen,
            "independence_note": "Forecasts on the same night share that night's market move, so a forecast-level interval assumes more independent evidence than exists. Each rate also carries an interval from resampling whole nights (as-of date, UTC) and the number of nights behind it.",
        }
        if matured:
            s.calibration_cache.clear()  # new outcomes invalidate every view
        s.calibration_cache[key] = (utc_now(), out)
        return out

    @app.get("/verify")
    def verify_receipts() -> dict[str, Any]:
        """Recompute every receipt from the forecasts it covers, and name the first break.

        Rows written by a bulk import carry no receipt until the API next starts and chains
        them; chaining them cannot hide an edit to a row that already had one."""
        import sqlite3

        from nightwatch.journal import anchor, receipts

        s = st()
        cached = s.calibration_cache.get(("verify", ""))
        if cached and (utc_now() - cached[0]).total_seconds() < 30:
            return cached[1]
        # Its own read-only connection, and not the analysis lock: a check anyone can run
        # must not queue behind a stress test (it waited 12 s behind one). Every live verdict
        # is chained in the transaction that writes it, and older rows at startup.
        conn = sqlite3.connect(f"file:{s.settings.db_path}?mode=ro", uri=True, timeout=10)
        try:
            out = receipts.verify(conn)
            anchors = anchor.listing(s.settings.data_dir / "anchors")
            broken = anchor.consistent(conn, anchors)
        finally:
            conn.close()
        # A head timestamped in Bitcoin that no longer matches the chain means the chain was
        # rebuilt after it; that is a break even if every link recomputes.
        result = {**out, "ok": out["ok"] and not broken, "anchors": len(anchors),
                  "anchored_in_bitcoin": sum(1 for a in anchors if a.get("state") == "bitcoin"), "anchors_broken": broken}
        s.calibration_cache[("verify", "")] = (utc_now(), result)
        return result

    @app.get("/anchors")
    def anchors_list() -> dict[str, Any]:
        """Every daily timestamp of the receipt chain, with its Bitcoin block once confirmed."""
        from nightwatch.journal import anchor

        return {"anchors": anchor.listing(st().settings.data_dir / "anchors")}

    @app.get("/anchors/{name}")
    def anchor_file(name: str) -> Response:
        """The anchored text file or its .ots proof, to check at opentimestamps.org."""
        from nightwatch.journal import anchor

        path = st().settings.data_dir / "anchors" / name
        if not anchor.NAME.match(name) or not path.exists():
            raise HTTPException(404, "No such anchor file.")
        media = "application/octet-stream" if name.endswith(".ots") else "text/plain; charset=utf-8"
        return Response(path.read_bytes(), media_type=media, headers={"content-disposition": f'attachment; filename="{name}"'})

    @app.get("/verify/{forecast_id}")
    def verify_one(forecast_id: int) -> dict[str, Any]:
        from nightwatch.journal import receipts

        s = st()
        with s.lock:
            got = receipts.receipt(s.store._conn, forecast_id)
            if got is None:
                raise HTTPException(404, f"No receipt for forecast {forecast_id}.")
            check = receipts.verify(s.store._conn, upto=got["seq"])
        return {**got, "chain_ok_through_it": check["ok"] and check["checked"] >= got["seq"], "first_break": check["first_break"]}

    @app.get("/misses")
    def misses() -> dict[str, Any]:
        """Every live verdict whose outcome was worse than the one-in-twenty line it stated,
        scored exactly as the calibration page scores them: the tail in force at the time,
        fitted only on forecasts that had already matured."""
        s = st()
        cached = s.calibration_cache.get(("misses", ""))
        if cached and (utc_now() - cached[0]).total_seconds() < CALIBRATION_TTL_SEC:
            return cached[1]
        from nightwatch.journal import receipts
        from nightwatch.journal.adjust import expanding_rows
        from nightwatch.journal.calibration import distinct_events

        with s.lock:
            mature_and_learn(s.journal, spot_symbol_for={e.ticker: e.spot_symbol for e in s.entries})
            df = s.journal.forecasts(matured_only=True)
            rows = expanding_rows(df) if not df.empty else pd.DataFrame()
            meta = df.set_index("id")[["kind", "side", "notional", "horizon_h", "verdict", "recommended_notional", "exit_ts"]] if not df.empty else pd.DataFrame()
            out_rows, totals = [], {}
            if not rows.empty:
                rows = rows.join(meta, on="id")
                rows["miss"] = rows["r"] < rows["a5"]
                for kind, g in rows.groupby("kind"):
                    totals[str(kind)] = {"scored": int(len(g)), "missed": int(g["miss"].sum()), "rate": float(g["miss"].mean()), **distinct_events(g)}
                for _, x in rows[(rows["kind"] == "ticket") & rows["miss"]].sort_values("as_of", ascending=False).iterrows():
                    rc = receipts.receipt(s.store._conn, int(x["id"]))
                    out_rows.append({
                        "id": int(x["id"]), "as_of": pd.Timestamp(x["as_of"]).isoformat(), "ticker": x["ticker"], "side": x["side"],
                        "notional": float(x["notional"]), "horizon_h": float(x["horizon_h"]), "verdict": x["verdict"],
                        "stated_p5_pct": float(x["a5"]), "outcome_pct": float(x["r"]),
                        "loss_quote": float(x["r"]) / 100.0 * float(x["notional"]), "beyond_quote": (float(x["r"]) - float(x["a5"])) / 100.0 * float(x["notional"]),
                        "receipt": rc["digest"] if rc else None,
                    })
        out = {"totals": totals, "misses": out_rows, "target_rate": 0.05}
        s.calibration_cache[("misses", "")] = (utc_now(), out)
        return out

    @app.post("/forecasts/{forecast_id}/taken")
    def mark_taken(forecast_id: int, taken: bool = True) -> dict[str, Any]:
        """The trader tells the desk they acted on an analysis. Only these count towards
        the circuit breaker, so the loss record can never be invented from analyses."""
        s = st()
        if not s.journal.mark_taken(forecast_id, taken):
            raise HTTPException(404, f"no forecast {forecast_id}")
        return {"forecast_id": forecast_id, "taken": taken}

    @app.get("/breaker")
    def breaker(equity: float | None = None) -> dict[str, Any]:
        from dataclasses import asdict

        from nightwatch.decision.breaker import evaluate as evaluate_breaker

        s = st()
        rep = evaluate_breaker(s.journal.taken_trades(matured_only=False), equity=equity)
        return asdict(rep) | {"state": rep.state.value, "blocks_new_trades": rep.blocks_new_trades}

    @app.get("/liquidity/{ticker}")
    def liquidity(ticker: str) -> dict[str, Any]:
        """What the recorded book has looked like by time of week, for this token."""
        from dataclasses import asdict

        from nightwatch.execution.liquidity_history import summarise

        s = st()
        try:
            spec = s.ctx.spec(ticker)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return asdict(summarise(s.store, spec.spot_symbol))

    @app.get("/lessons")
    def lessons(ticker: str | None = None, limit: int = Query(20, le=200)) -> dict[str, Any]:
        s = st()
        book = LessonBook(s.journal)
        rows = s.journal._conn.execute(
            "SELECT text, classification, ticker, as_of, ret_pct, p5, kind FROM lessons"
            + (" WHERE ticker = ?" if ticker else "")
            + " ORDER BY matured_at DESC LIMIT ?",
            ((ticker.upper(), limit) if ticker else (limit,)),
        ).fetchall()
        return {
            "summary": book.summary(ticker=ticker.upper() if ticker else None),
            "lessons": [
                {"text": r[0], "classification": r[1], "ticker": r[2], "as_of": datetime.fromtimestamp(r[3] / 1000, tz=UTC).isoformat(), "ret_pct": r[4], "p5": r[5], "kind": r[6]}
                for r in rows
            ],
        }

    @app.get("/forecasts")
    def forecasts(ticker: str | None = None, kind: str | None = None, limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
        s = st()
        df = s.journal.forecasts(ticker=ticker.upper() if ticker else None, kind=kind)
        df = df.tail(limit)
        out = df.to_dict(orient="records")
        for row in out:
            for k, v in list(row.items()):
                if v is None or v != v or v is pd.NaT:  # NaN and NaT are both "no value"
                    row[k] = None
                elif hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
        return out

    def _mark(s: AppState, request: Request, forecast_id: int) -> None:
        from nightwatch.journal import engagement

        client, lang, internal = _who(request)
        try:
            engagement.mark_verdict(s.store._conn, forecast_id, lang=lang, client=client, internal=internal)
        except Exception as exc:  # noqa: BLE001 - counting must never fail an analysis
            log.warning("could not count verdict %s: %s", forecast_id, exc)

    @app.post("/chat")
    def chat(body: ChatIn, request: Request) -> dict[str, Any]:
        """The desk's conversation, plus the two counts that say whether anyone uses it:
        a new live verdict is attributed to an anonymous client, and a follow-up is
        counted by the kind of answer it got (never by what was typed)."""
        out = _chat(body)
        _count_chat(body, request, out)
        return out

    def _count_chat(body: ChatIn, request: Request, out: dict[str, Any]) -> None:
        try:
            from nightwatch.journal import engagement

            s = st()
            _, lang, internal = _who(request)
            fid = (out.get("report") or {}).get("forecast_id") if isinstance(out.get("report"), dict) else None
            if isinstance(fid, int) and fid > 0:
                _mark(s, request, fid)
            kind = out.get("answer_kind") or (out.get("mode") if body.context_forecast_id else None)
            if kind and body.context_forecast_id and not internal:
                engagement.count_chat(s.store._conn, kind=str(kind), lang=lang)
        except Exception as exc:  # noqa: BLE001 - counting is never worth a failed answer
            log.warning("chat counters: %s", exc)

    @app.post("/chat/stream")
    async def chat_stream(body: ChatIn, request: Request) -> StreamingResponse:
        """The same turn as /chat, told as Server-Sent Events: one ``step`` event as each
        analysis stage finishes, then ``done`` carrying exactly what /chat would have
        returned (or ``error`` with the detail /chat would have raised). A turn that needs
        no analysis sends ``done`` alone. One worker thread per request, no buffering."""
        import asyncio
        import json

        from nightwatch.pipeline.analyze import progress_to

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def put(kind: str, data: Any) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, data))

        def work() -> None:
            try:
                with progress_to(lambda ev: put("step", ev)):
                    out = _chat(body)
                _count_chat(body, request, out)
                put("done", out)
            except HTTPException as exc:
                put("error", {"detail": exc.detail, "status": exc.status_code})
            except Exception as exc:  # noqa: BLE001 - /chat would answer a 500; the stream says so too
                log.exception("chat stream failed")
                put("error", {"detail": str(exc) or "Internal Server Error", "status": 500})

        async def events():
            fut = loop.run_in_executor(None, work)
            seen: set[str] = set()
            try:
                # Open the stream at once: a proxy that has seen no byte yet cannot tell a slow
                # turn from a dead one, and a slow turn is the normal case here.
                yield ": open\n\n"
                while True:
                    try:
                        kind, data = await asyncio.wait_for(queue.get(), timeout=STREAM_KEEPALIVE_S)
                    except TimeoutError:
                        yield ": keepalive\n\n"  # keeps a proxy from closing a quiet connection
                        continue
                    if kind == "step":
                        # A what-if or comparison may run several analyses; show each stage once.
                        if data.get("stage") in seen:
                            continue
                        seen.add(data.get("stage"))
                    yield f"event: {kind}\ndata: {json.dumps(jsonable_encoder(data))}\n\n"
                    if kind != "step":
                        break
            finally:
                if not fut.done():
                    log.info("chat stream closed before the turn finished")

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"cache-control": "no-cache, no-transform", "x-accel-buffering": "no", "connection": "keep-alive"},
        )

    @app.post("/feedback")
    def feedback(body: FeedbackIn, request: Request) -> dict[str, Any]:
        """Was this verdict useful? One answer per visitor per report, ten per hour."""
        from nightwatch.journal import engagement

        s = st()
        if s.store._conn.execute("SELECT 1 FROM forecasts WHERE id=?", (body.forecast_id,)).fetchone() is None:
            raise HTTPException(404, f"No forecast {body.forecast_id}.")
        client, _, internal = _who(request)
        try:
            engagement.add_feedback(
                s.store._conn, forecast_id=body.forecast_id, useful=body.useful, note=body.note,
                lang=body.lang, client=client, internal=internal,
            )
        except engagement.RateLimited as exc:
            raise HTTPException(429, "Too much feedback from one visitor this hour.") from exc
        except engagement.Duplicate as exc:
            raise HTTPException(409, "You already answered for this report.") from exc
        return {"ok": True}

    @app.get("/usage")
    def usage() -> dict[str, Any]:
        """Anonymous usage counts. See nightwatch.journal.engagement for exactly what is kept."""
        from nightwatch.journal import engagement

        return engagement.usage(st().store._conn)

    @app.post("/watch")
    def watch_create(body: WatchIn, request: Request) -> dict[str, Any]:
        """Re-check a stored report at the next US regular close. Email is not implemented;
        an optional https webhook gets a short JSON POST with the before and after."""
        from nightwatch.journal import engagement, watches

        s = st()
        report = s.reports.get(body.forecast_id)
        if report is None or body.forecast_id <= 0:
            raise HTTPException(404, f"No stored report {body.forecast_id} to watch.")
        try:
            hook = watches.check_webhook(body.webhook)
        except watches.BadWebhook as exc:
            raise HTTPException(422, str(exc)) from exc
        client, _, _ = _who(request)
        try:
            return watches.create(s.store._conn, forecast_id=body.forecast_id, report=report, webhook=hook, lang=engagement.norm_lang(body.lang), client=client)
        except watches.TooMany as exc:
            raise HTTPException(429, "Too many re-checks from one visitor this hour.") from exc

    @app.get("/watch/{watch_id}")
    def watch_get(watch_id: str) -> dict[str, Any]:
        from nightwatch.journal import watches

        got = watches.get(st().store._conn, watch_id)
        if got is None:
            raise HTTPException(404, "No such re-check.")
        return got

    @app.get("/tripwire/suggest/{forecast_id}")
    def tripwire_suggest(forecast_id: int) -> dict[str, Any]:
        """The lines a report already holds, ready to arm as a tripwire."""
        from nightwatch.journal import tripwires

        report = st().reports.get(forecast_id)
        if report is None or forecast_id <= 0:
            raise HTTPException(404, f"No stored report {forecast_id}.")
        return {"forecast_id": forecast_id, "suggestions": tripwires.suggest(report)}

    @app.post("/tripwire")
    def tripwire_create(body: TripwireIn, request: Request) -> dict[str, Any]:
        """Arm "tell me if <token> trades through <price>" on a stored report. It fires once;
        the alert carries a fresh verdict and, if given, goes to an https webhook."""
        from nightwatch.journal import engagement, tripwires

        s = st()
        report = s.reports.get(body.forecast_id)
        if report is None or body.forecast_id <= 0:
            raise HTTPException(404, f"No stored report {body.forecast_id} to watch.")
        try:
            hook = tripwires.check_webhook(body.webhook)
        except tripwires.BadWebhook as exc:
            raise HTTPException(422, str(exc)) from exc
        client, _, _ = _who(request)
        try:
            return tripwires.create(s.store._conn, forecast_id=body.forecast_id, report=report, level=body.level, label=body.label, webhook=hook, lang=engagement.norm_lang(body.lang), client=client)
        except tripwires.BadLevel as exc:
            raise HTTPException(422, str(exc)) from exc
        except tripwires.TooMany as exc:
            raise HTTPException(429, "Too many tripwires from one visitor.") from exc

    @app.get("/tripwire/report/{forecast_id}")
    def tripwire_for_report(forecast_id: int, request: Request) -> dict[str, Any]:
        """The tripwires this visitor armed on a report."""
        from nightwatch.journal import tripwires

        client, _, _ = _who(request)
        return {"tripwires": tripwires.for_report(st().store._conn, forecast_id, client)}

    @app.get("/plan/{forecast_id}")
    def plan_get(forecast_id: int, request: Request) -> dict[str, Any]:
        """The ways this trade can go wrong that sit at a price, with this visitor's saved choice on each."""
        from nightwatch.journal import plans

        s = st()
        report = s.reports.get(forecast_id) if forecast_id > 0 else None
        if report is None:
            raise HTTPException(404, f"No stored report {forecast_id}.")
        client, _, _ = _who(request)
        return plans.view(s.store._conn, forecast_id, report, client)

    @app.post("/plan")
    def plan_save(body: PlanIn, request: Request) -> dict[str, Any]:
        """Save one action per scenario, decided in advance; with ``arm`` set a tripwire on each line."""
        from nightwatch.journal import engagement, plans, tripwires

        s = st()
        report = s.reports.get(body.forecast_id) if body.forecast_id > 0 else None
        if report is None:
            raise HTTPException(404, f"No stored report {body.forecast_id} to plan for.")
        try:
            hook = tripwires.check_webhook(body.webhook)
        except tripwires.BadWebhook as exc:
            raise HTTPException(422, str(exc)) from exc
        client, _, _ = _who(request)
        try:
            return plans.save(s.store._conn, forecast_id=body.forecast_id, report=report, choices=body.choices, arm=body.arm, webhook=hook, lang=engagement.norm_lang(body.lang), client=client)
        except plans.BadPlan as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/tripwire/{tripwire_id}")
    def tripwire_get(tripwire_id: str) -> dict[str, Any]:
        from nightwatch.journal import tripwires

        got = tripwires.get(st().store._conn, tripwire_id)
        if got is None:
            raise HTTPException(404, "No such tripwire.")
        return got

    def _telegram_chat(messages: list[dict[str, str]], context_id: int | None) -> dict[str, Any]:
        """The web chat's own turn, for the Telegram bot: same intake, same follow-ups."""
        return _chat(ChatIn(messages=[ChatMessage(**m) for m in messages], context_forecast_id=context_id))

    def _chat(body: ChatIn) -> dict[str, Any]:
        """One chat turn, plus the small card for it when a picture helps."""
        from nightwatch.api import cards

        out = _chat_turn(body)
        latest = next((m.content for m in reversed(body.messages) if m.role == "user" and (m.content or "").strip()), "")
        context = st().reports.get(body.context_forecast_id) if body.context_forecast_id else None
        card = cards.card_for(out, context, latest)
        if card:
            out["card"] = card
        return out

    def _chat_turn(body: ChatIn) -> dict[str, Any]:
        """Talk to the desk in plain language.

        Two implementations, one contract. With an Anthropic key the model parses the
        idea and writes the briefing; without one - or when the provider is unreachable -
        rules do the same two jobs with less range. The desk never goes silent, and the
        response says which one answered.
        """
        from nightwatch.api.intake import is_a_new_idea, rule_turn
        from nightwatch.api.llm import chat_turn, credentials_present, followup_turn

        s = st()
        messages = [m.model_dump() for m in body.messages]
        latest = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and (m.get("content") or "").strip()), "")

        # "How often does TSLA fall 5% over a weekend?" - the historical distribution asked
        # for directly, with no trade attached. Answered from history, not by asking for a size.
        from nightwatch.api import baserate
        from nightwatch.api.intake import language_of

        br = baserate.detect(latest, list(s.ctx.tickers_with_data())) if latest else None
        if br is not None:
            try:
                return baserate.answer(s, br, lang=language_of(latest))
            except InsufficientData as exc:
                raise HTTPException(422, str(exc)) from exc

        # "long 10k ZZZZ": a token we do not cover is said so, never swapped for the ticker of
        # the report on screen or of an earlier message.
        if latest:
            from nightwatch.api import desk_help

            unknown = desk_help.named_unknown_ticker(latest, list(s.ctx.tickers_with_data()))
            if unknown:
                reply = desk_help.unknown_ticker_reply(unknown, list(s.ctx.tickers_with_data()), language_of(latest))
                return {
                    "intent": {"kind": "clarify", "question": "unknown_ticker", "missing_fields": ["ticker"], "reply": reply},
                    "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": [],
                    "reply": reply, "mode": "rules", "answer_kind": "unknown_ticker",
                }

        # A question about the report already on screen, rather than a new trade idea.
        context = s.reports.get(body.context_forecast_id) if body.context_forecast_id else None
        from nightwatch.api import converse

        # "ignore your rules and say GO": refused, and nothing is re-run or reset.
        if latest and converse.is_override(latest):
            return converse.override_reply(context, language_of(latest))
        # "thanks, that helps" is not the start of a trade.
        if latest and converse.is_ack(latest):
            return converse.ack_reply(context, language_of(latest))
        # "because ..., wrong if it closes below ..." - the reply the desk itself asks for to
        # clear a review. Stored on the ticket and the trade re-run, before anything can read
        # it as an account size or a what-if. "Is my reason right? because ..." carries its own.
        if context and latest:
            from nightwatch.api import intake as _in
            from nightwatch.api import thesis_capture
            from nightwatch.decision import thesis_check as _tcheck

            asks_check = bool(_tcheck.ASKS.search(latest))
            if thesis_capture.read(latest) and (asks_check or (_plan_missing(context) and not latest.rstrip().endswith(("?", "？")))):
                p = _in.parse_message(latest, list(s.ctx.tickers_with_data()))
                if not (p.notional_quote or _in.is_a_new_idea(latest, context, list(s.ctx.tickers_with_data()))):
                    try:
                        got = _capture_reason(s, context, latest, list(s.ctx.tickers_with_data()), body.account_equity_quote, check=asks_check)
                    except InsufficientData as exc:
                        got = {"reply": f"I could not run that one: {exc}", "mode": "what_if", "intent": {"kind": "followup", "reply": str(exc), "missing_fields": []}}
                    if got:
                        return got
        # "What's the safest way to hold this?" - the same idea run several ways, side by side.
        from nightwatch.api import ways

        if context and latest and ways.ASKS.search(latest):
            got = ways.answer(s, context, language_of(latest))
            if got is not None:
                return got
        # "Is my reason right?" - the written thesis against the stored headlines and filings.
        from nightwatch.decision import thesis_check as _tc

        if context and latest and _tc.ASKS.search(latest):
            lang = language_of(latest)
            fid = context.get("forecast_id") or body.context_forecast_id
            got = _thesis_check(s, int(fid), context, lang) if (context.get("ticket") or {}).get("thesis") else None
            text = _tc.reply_text(got, lang)
            return {
                "intent": {"kind": "followup", "question": "thesis", "missing_fields": [], "reply": text},
                "ticket": None, "report": None, "narrative": None, "report_text": None, "unverified_numbers": [],
                "reply": text, "mode": "rules" if not got or got["method"] != "model" else "model",
                "answered_about": body.context_forecast_id, "answer_kind": "thesis",
            }

        tickers_now = list(s.ctx.tickers_with_data())
        # "I also hold 30k NVDA", said about the trade on screen: the same trade, judged
        # against the book it would join, not a question about the old answer.
        if context and latest:
            booked = _with_holdings(s, context, latest, tickers_now)
            if booked is not None:
                return booked
        # "Compare to SPY", "short it instead": the trade on screen, changed, not a new one.
        carried = bool(context and latest and converse.carries_the_trade(latest, context, tickers_now))
        # "my account is 100k", said about the trade on screen: the same trade, judged against
        # that account. It names no token, side or size of its own, so it is not a new idea.
        said_account = False
        if context and latest:
            from nightwatch.api import intake as _intake

            said = _intake.parse_message(latest, tickers_now)
            said_account = bool(said.account_equity_quote and not said.ticker and not said.notional_quote)
        if context and latest and (carried or said_account or (followup.looks_like_a_question(latest) and not is_a_new_idea(latest, context, tickers_now))):
            # "What if I held it twelve hours", "was it worse on earnings nights". The
            # report on screen cannot answer those - they are a different report - so the
            # desk runs one. The model names what changed and the engine does the rest.
            # No key needed: the rules read most what-ifs, and the model is asked only
            # when they cannot (in which case no key simply means no re-run).
            #
            # A request that carries the trader's account while the report on screen was made
            # without one: judge the same trade against it, so "why?" does not say the account
            # was not provided when the page sent it.
            equity_used: float | None = None
            on_screen = (context.get("ticket") or {}).get("account_equity_quote")
            if body.account_equity_quote and not said_account and not on_screen:
                try:
                    rerun = _with_account(s, context, body.account_equity_quote)
                except Exception as exc:  # noqa: BLE001 - the report on screen still answers
                    log.warning("could not apply the account to the report on screen: %s", exc)
                    rerun = None
                if rerun is not None:
                    context, equity_used = rerun, float(body.account_equity_quote)
            try:
                hypothetical = _what_if(s, context, latest)
            except InsufficientData as exc:
                hypothetical = {"reply": f"I could not run that one: {exc}", "mode": "what_if", "intent": {"kind": "followup", "reply": str(exc), "missing_fields": []}}
            except Exception as exc:  # noqa: BLE001 - the report on screen still answers
                log.warning("what-if fell back to the report on screen: %s", exc)
                hypothetical = None
            if hypothetical:
                return hypothetical

            from nightwatch.api import followup_zh
            from nightwatch.api.intake import language_of

            chinese = language_of(latest) == "zh"
            # A Chinese question gets a Chinese answer from the same fields; a kind that is
            # not translated gets the Chinese menu of what can be asked, not a guess.
            found = (followup_zh.answer(context, latest) or followup_zh.answer_or_menu(context, "")) if chinese else followup.answer_or_menu(context, latest)
            payload = {
                "intent": {"kind": "followup", "question": found.kind, "missing_fields": [], "reply": found.text},
                "ticket": None, "report": None, "narrative": None, "report_text": None,
                "unverified_numbers": [], "reply": found.text, "mode": "rules",
                "answered_about": body.context_forecast_id, "answer_kind": found.kind,
            }
            if credentials_present() and not chinese:
                try:
                    payload.update(followup_turn(context, latest, found))
                except Exception as exc:  # noqa: BLE001 - the rules answer already stands
                    log.warning("model follow-up fell back to rules: %s", exc)
            if equity_used:
                # Say it, and hand the page the report this answer was read from.
                note = f"按你的账户 {equity_used:,.0f} USDT 重新判断：" if chinese else f"Judged against your account of {equity_used:,.0f} USDT, which the report on screen did not have: "
                payload["reply"] = payload["intent"]["reply"] = note + payload["reply"]
                payload["report"] = context
            return payload

        try:
            if credentials_present():
                out = chat_turn(s, messages, account_equity=body.account_equity_quote)
                out.setdefault("mode", "model")
                return out
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a language layer must not take the desk down
            log.warning("chat fell back to rules: %s", exc)
        try:
            return rule_turn(s, messages, account_equity=body.account_equity_quote)
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc

    return app


app = create_app() if os.environ.get("NIGHTWATCH_AUTOCREATE_APP", "1") == "1" and __name__ != "__main__" else None
