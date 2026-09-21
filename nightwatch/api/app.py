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
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nightwatch import __version__
from nightwatch.api import followup
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
CALIBRATION_TTL_SEC = 120


class PositionIn(BaseModel):
    ticker: str
    side: Side = Side.LONG
    notional_quote: float = Field(gt=0)


class TicketIn(BaseModel):
    ticker: str
    side: Side = Side.LONG
    notional_quote: float = Field(gt=0)
    account_equity_quote: float | None = Field(default=None, gt=0)
    horizon_kind: HorizonKind = HorizonKind.NEXT_OPEN
    horizon_hours: float | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    thesis: str = ""
    invalidation: str = ""
    hedge_ratio: float | None = Field(default=None, ge=0, le=1)
    as_of: datetime | None = None
    record: bool = True
    open_positions: list[PositionIn] = Field(default_factory=list)

    def to_ticket(self) -> TradeTicket:
        return TradeTicket(
            ticker=self.ticker.upper(), side=self.side, notional_quote=self.notional_quote, account_equity_quote=self.account_equity_quote,
            horizon_kind=self.horizon_kind, horizon_hours=self.horizon_hours, entry_price=self.entry_price, stop_price=self.stop_price,
            target_price=self.target_price, thesis=self.thesis, invalidation=self.invalidation, hedge_ratio=self.hedge_ratio,
            open_positions=tuple((p.ticker.upper(), p.side.value, p.notional_quote) for p in self.open_positions),
        )


class ChatMessage(BaseModel):
    role: str
    content: str


class TonightIn(BaseModel):
    positions: list[PositionIn] = Field(default_factory=list)
    account_equity_quote: float | None = None


class ChatIn(BaseModel):
    messages: list[ChatMessage]
    account_equity_quote: float | None = None
    # The report the conversation is currently about, so a question can be answered from
    # it. The desk already stores every report it produces; this is the key to one.
    context_forecast_id: int | None = None


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.entries: list[UniverseEntry] = build_universe(
            self.store.list_instruments(Venue.BITGET_SPOT), self.store.list_instruments(Venue.BITGET_UMCBL), settings.core_tickers
        )
        self.journal = Journal(self.store)
        self.reports = ReportStore(self.store)
        live = os.environ.get("NIGHTWATCH_LIVE_BOOK", "1") == "1"
        self.ctx = AnalysisContext(
            store=self.store, entries=self.entries, journal=self.journal,
            spot_client=BitgetPublicClient(Venue.BITGET_SPOT, rate_per_sec=4) if live else None,
            perp_client=BitgetPublicClient(Venue.BITGET_UMCBL, rate_per_sec=4) if live else None,
            frame_cache_size=settings.frame_cache_size,
        )
        self.lock = threading.Lock()  # serialises analyses that share the frame cache
        # Scoring the whole journal takes seconds; it only changes when forecasts mature.
        self.calibration_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
        self.warm_thread: threading.Thread | None = None
        self.warm_status: dict[str, Any] = {"state": "idle", "done": 0, "total": 0}

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

    def warm_forever(self) -> None:
        """Warm now, then again just after every hour boundary.

        Frames are keyed by end-hour, so at the top of each hour every token goes cold and
        the first request for it pays a few seconds. A judge's first click should not be
        the one that pays, so the cache is refilled in the background before they arrive."""
        while True:
            self.warm()
            now = utc_now()
            next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1, seconds=45))
            threading.Event().wait(max(30.0, (next_hour - now).total_seconds()))

    def start_warm(self) -> None:
        self.warm_thread = threading.Thread(target=self.warm_forever, name="warm-frames", daemon=True)
        self.warm_thread.start()

    def close(self) -> None:
        self.store.close()


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

    def st() -> AppState:
        return app.state.nw

    @app.get("/health")
    def health() -> dict[str, Any]:
        from nightwatch.api.llm import credentials_present
        s = st()
        c = s.store._conn
        bars = c.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        ob = c.execute("SELECT COUNT(*), MAX(ts) FROM orderbook_snapshots").fetchone()
        last_book = datetime.fromtimestamp(ob[1] / 1000, tz=UTC).isoformat() if ob[1] else None
        chat_ready = credentials_present()
        return {
            "ok": True, "version": __version__, "time": utc_now().isoformat(), "bars": bars, "orderbook_snapshots": ob[0], "last_book_ts": last_book,
            "tickers_with_data": len(s.ctx.tickers_with_data()), "warm": s.warm_status, "chat_ready": chat_ready,
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
                p5 = horizon.p5_adjusted if horizon.p5_adjusted is not None else horizon.cohort.p5

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

    @app.get("/studies")
    def studies() -> dict[str, Any]:
        """What the desk has tested about its own retrieval, and what came back.

        Served from stored results rather than computed on request: the match-level
        sweep behind half of these takes minutes, and a study that quietly recomputed
        itself differently every time nobody was looking would not be a study. The
        answer carries the date it was last run so a stale one is visible as stale.
        """
        from nightwatch.journal.studies import StudyStore

        s = st()
        store = StudyStore(s.store)
        last = store.last_run()
        return {
            "studies": store.all(),
            "last_run": last.isoformat() if last else None,
            "note": "" if last else "No studies have been run against this database yet; run `nightwatch studies`.",
        }

    @app.get("/sources")
    def sources() -> list[dict[str, Any]]:
        """Every feed the desk reads, with how fresh it is. Judges and users can check
        the numbers on a report are backed by live data, not a fixture."""
        return data_sources(st().store)

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
    def analyze_endpoint(body: TicketIn, text: bool = False) -> Any:
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
        # Keep the finished report so a link can reopen it exactly as it was argued.
        if report.forecast_id is not None and body.record:
            try:
                s.reports.save(report.forecast_id, payload)
            except Exception as exc:  # noqa: BLE001 - a keepsake must not fail an analysis
                log.warning("could not store report %s: %s", report.forecast_id, exc)
        if text:
            return {"text": render_text(report), "forecast_id": report.forecast_id}
        return payload

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

    @app.post("/chat")
    def chat(body: ChatIn) -> dict[str, Any]:
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

        # A question about the report already on screen, rather than a new trade idea.
        context = s.reports.get(body.context_forecast_id) if body.context_forecast_id else None
        if context and latest and followup.looks_like_a_question(latest) and not is_a_new_idea(latest, context, list(s.ctx.tickers_with_data())):
            found = followup.answer_or_menu(context, latest)
            payload = {
                "intent": {"kind": "followup", "question": found.kind, "missing_fields": [], "reply": found.text},
                "ticket": None, "report": None, "narrative": None, "report_text": None,
                "unverified_numbers": [], "reply": found.text, "mode": "rules",
                "answered_about": body.context_forecast_id, "answer_kind": found.kind,
            }
            if credentials_present():
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
