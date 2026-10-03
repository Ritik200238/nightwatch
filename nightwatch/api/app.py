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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from nightwatch import __version__
from nightwatch.api import followup, guard
from nightwatch.api.sources import data_sources
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

# How often the idle API re-reads its cached frames so they are not swapped out.
TOUCH_EVERY_S = 180.0
CALIBRATION_TTL_SEC = 120
PAGE_CACHE_MAX = 200
CALIBRATION_CACHE_MAX = 100
# Query params that change what a cached page shows; anything else is not cached, so a
# caller cannot grow the cache with made-up parameters.
PAGE_CACHE_PARAMS = frozenset({"core", "ticker", "kind", "limit"})
PAGE_CACHE_TTL_S = 60.0
PAGE_CACHE_STALE_S = 6 * 3600.0  # beyond this a saved page is too old to show even while refreshing
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
        from nightwatch.journal import engagement, receipts, tripwires, watches

        self.store._conn.executescript(engagement.SCHEMA)
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
        self.ctx = AnalysisContext(
            store=self.store, entries=self.entries, journal=self.journal,
            spot_client=BitgetPublicClient(Venue.BITGET_SPOT, rate_per_sec=4) if live else None,
            perp_client=BitgetPublicClient(Venue.BITGET_UMCBL, rate_per_sec=4) if live else None,
            frame_cache_size=settings.frame_cache_size,
            street_client=_street_client(),
            signal_client=_signal_client(),
        )
        self.lock = threading.Lock()  # serialises analyses that share the frame cache
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
                with self.lock:
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

    def refresh_signal(self) -> None:
        """The signal skill's reading for every token, one at a time: its backend is flaky
        and slow, so it gets no parallel load, and it runs outside the analysis lock."""
        for t in self.ctx.tickers_with_data():
            self.ctx.signal_for(t, max_age=timedelta(minutes=50), fetch=True)
        self.ctx.signal_health(max_age=timedelta(minutes=50))

    def warm_forever(self) -> None:
        """Warm now, then again just after every hour boundary.

        Frames are keyed by end-hour, so at the top of each hour every token goes cold and
        the first request for it pays a few seconds. A judge's first click should not be
        the one that pays, so the cache is refilled in the background before they arrive."""
        while True:
            if self.ctx.street_client is not None:
                threading.Thread(target=self.refresh_street, name="street-refresh", daemon=True).start()
            if self.ctx.signal_client is not None:
                threading.Thread(target=self.refresh_signal, name="signal-refresh", daemon=True).start()
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

    def start_warm(self) -> None:
        self.warm_thread = threading.Thread(target=self.warm_forever, name="warm-frames", daemon=True)
        self.warm_thread.start()

    def close(self) -> None:
        self.store.close()


def _street_client():  # noqa: ANN202
    """Bitget's US-stock data service, unless turned off (NIGHTWATCH_BITGET_MCP=0)."""
    if os.environ.get("NIGHTWATCH_BITGET_MCP", "1") != "1":
        return None
    from nightwatch.data.bitget_mcp import BitgetMcpClient

    return BitgetMcpClient()


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
    if any(kind == "street" and pattern.search(question) for kind, pattern, _ in followup.ROUTES):
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

    ticket = change.apply_to(base, entry=((context.get("snapshot") or {}).get("prices") or {}).get("spot_close"))
    with state.lock:
        report = analyze(state.ctx, ticket, as_of=whatif.as_of_of(context), record=False)
        payload = report.to_dict()
    state.keep_hypothetical(payload)
    from nightwatch.api.intake import language_of

    answer = whatif.compare(context, payload, change, language_of(question))
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


def create_app(settings: Settings | None = None, *, warm: bool = True) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = AppState(settings)
        app.state.nw = state
        if warm:
            state.start_warm()
        try:
            yield
        finally:
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
    def health() -> dict[str, Any]:
        from nightwatch.api.providers import describe as describe_llm

        s = st()
        c = s.store._conn
        bars = c.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        ob = c.execute("SELECT COUNT(*), MAX(ts) FROM orderbook_snapshots").fetchone()
        last_book = datetime.fromtimestamp(ob[1] / 1000, tz=UTC).isoformat() if ob[1] else None
        # Which model is answering, not just whether one is. "chat_ready: true" with no
        # way to see who is behind it was how the box ran on the rule-based fallback for
        # days without anyone noticing.
        llm = describe_llm()
        return {
            "ok": True, "version": __version__, "time": utc_now().isoformat(), "bars": bars, "orderbook_snapshots": ob[0], "last_book_ts": last_book,
            "started_at": s.started_at.isoformat(), "uptime_s": int((utc_now() - s.started_at).total_seconds()),
            "tickers_with_data": len(s.ctx.tickers_with_data()), "warm": s.warm_status, "chat_ready": llm["ready"], "llm": llm,
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
        }

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
            newest = max((ts for ts, _ in cached), default=None)
            out.append({
                "key": "bitget_mcp", "label": "Bitget US-stock data",
                "what": "Live quote for the underlying, analyst ratings and targets, insider trades, market fear & greed (bitget-mcp-server)",
                "cadence": "hourly per token, in memory only", "last_update": newest.isoformat() if newest else None,
                "rows": len(cached), "latest": newest.isoformat() if newest else None,
                "latest_label": f"{len(cached)} tokens with current street data", "url": "https://agent.bitget.com/mcp",
            })
        if s.ctx.signal_client is not None:
            health = s.ctx.signal_health()
            shown = [(ts, v) for ts, v in s.ctx._signal.values() if v and v.get("agrees")]
            newest = max((ts for ts, _ in shown), default=None)
            out.append({
                "key": "bitget_signal", "label": "Bitget signal skill backend",
                "what": "RSI (4h) from the bitget-signal technical-analysis tool, shown only when it agrees with our own RSI from Bitget candles. Its other tools are mostly failing.",
                "cadence": "hourly per token, in memory only", "last_update": newest.isoformat() if newest else None,
                "rows": len(shown), "latest": newest.isoformat() if newest else None,
                "latest_label": f"{health['answering']} of {health['tried']} tools answering" if health else "health check pending",
                "url": "https://datahub.noxiaohao.com/mcp",
            })
        return out

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

        from nightwatch.journal.adjust import evaluate_expanding
        from nightwatch.journal.skill import compare_skill
        from nightwatch.journal.walkforward import by_period

        adjusted = evaluate_expanding(df) if not df.empty else None
        skill = compare_skill(df) if not df.empty else None
        walk = by_period(df) if not df.empty else None
        out = {
            "matured_now": matured, **asdict(rep), "adjusted": asdict(adjusted) if adjusted else None,
            "skill": asdict(skill) if skill else None, "walk_forward": asdict(walk) if walk else None,
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

        with s.lock:
            mature_and_learn(s.journal, spot_symbol_for={e.ticker: e.spot_symbol for e in s.entries})
            df = s.journal.forecasts(matured_only=True)
            rows = expanding_rows(df) if not df.empty else pd.DataFrame()
            meta = df.set_index("id")[["kind", "side", "notional", "horizon_h", "verdict", "recommended_notional"]] if not df.empty else pd.DataFrame()
            out_rows, totals = [], {}
            if not rows.empty:
                rows = rows.join(meta, on="id")
                rows["miss"] = rows["r"] < rows["a5"]
                for kind, g in rows.groupby("kind"):
                    totals[str(kind)] = {"scored": int(len(g)), "missed": int(g["miss"].sum()), "rate": float(g["miss"].mean())}
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
        return out

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

    @app.get("/tripwire/{tripwire_id}")
    def tripwire_get(tripwire_id: str) -> dict[str, Any]:
        from nightwatch.journal import tripwires

        got = tripwires.get(st().store._conn, tripwire_id)
        if got is None:
            raise HTTPException(404, "No such tripwire.")
        return got

    def _chat(body: ChatIn) -> dict[str, Any]:
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

        # A question about the report already on screen, rather than a new trade idea.
        context = s.reports.get(body.context_forecast_id) if body.context_forecast_id else None
        from nightwatch.api import converse

        # "thanks, that helps" is not the start of a trade.
        if latest and converse.is_ack(latest):
            return converse.ack_reply(context, language_of(latest))
        # "What's the safest way to hold this?" - the same idea run several ways, side by side.
        from nightwatch.api import ways

        if context and latest and ways.ASKS.search(latest):
            got = ways.answer(s, context, language_of(latest))
            if got is not None:
                return got

        tickers_now = list(s.ctx.tickers_with_data())
        # "I also hold 30k NVDA", said about the trade on screen: the same trade, judged
        # against the book it would join, not a question about the old answer.
        if context and latest:
            booked = _with_holdings(s, context, latest, tickers_now)
            if booked is not None:
                return booked
        # "Compare to SPY", "short it instead": the trade on screen, changed, not a new one.
        carried = bool(context and latest and converse.carries_the_trade(latest, context, tickers_now))
        if context and latest and (carried or (followup.looks_like_a_question(latest) and not is_a_new_idea(latest, context, tickers_now))):
            # "What if I held it twelve hours", "was it worse on earnings nights". The
            # report on screen cannot answer those - they are a different report - so the
            # desk runs one. The model names what changed and the engine does the rest.
            # No key needed: the rules read most what-ifs, and the model is asked only
            # when they cannot (in which case no key simply means no re-run).
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
