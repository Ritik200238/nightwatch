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
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nightwatch import __version__
from nightwatch.config import Settings, load_settings
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.models import Venue
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry, build_universe
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.features.snapshot import InsufficientData, build_snapshot
from nightwatch.journal.calibration import calibrate
from nightwatch.journal.journal import Journal
from nightwatch.pipeline.analyze import AnalysisContext, analyze
from nightwatch.pipeline.render import render_text
from nightwatch.stress.scenarios import Side
from nightwatch.time_utils import UTC, utc_now

log = logging.getLogger(__name__)
CALIBRATION_TTL_SEC = 120


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

    def to_ticket(self) -> TradeTicket:
        return TradeTicket(
            ticker=self.ticker.upper(), side=self.side, notional_quote=self.notional_quote, account_equity_quote=self.account_equity_quote,
            horizon_kind=self.horizon_kind, horizon_hours=self.horizon_hours, entry_price=self.entry_price, stop_price=self.stop_price,
            target_price=self.target_price, thesis=self.thesis, invalidation=self.invalidation, hedge_ratio=self.hedge_ratio,
        )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]
    account_equity_quote: float | None = None


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.entries: list[UniverseEntry] = build_universe(
            self.store.list_instruments(Venue.BITGET_SPOT), self.store.list_instruments(Venue.BITGET_UMCBL), settings.core_tickers
        )
        self.journal = Journal(self.store)
        live = os.environ.get("NIGHTWATCH_LIVE_BOOK", "1") == "1"
        self.ctx = AnalysisContext(
            store=self.store, entries=self.entries, journal=self.journal,
            spot_client=BitgetPublicClient(Venue.BITGET_SPOT, rate_per_sec=4) if live else None,
            perp_client=BitgetPublicClient(Venue.BITGET_UMCBL, rate_per_sec=4) if live else None,
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

    def start_warm(self) -> None:
        self.warm_thread = threading.Thread(target=self.warm, name="warm-frames", daemon=True)
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
        try:
            with s.lock:
                report = analyze(s.ctx, ticket, as_of=body.as_of, record=body.record)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc
        if text:
            return {"text": render_text(report), "forecast_id": report.forecast_id}
        return report.to_dict()

    @app.get("/calibration")
    def calibration(ticker: str | None = None, kind: str | None = None) -> dict[str, Any]:
        s = st()
        key = (ticker or "", kind or "")
        cached = s.calibration_cache.get(key)
        if cached and (utc_now() - cached[0]).total_seconds() < CALIBRATION_TTL_SEC:
            return cached[1]
        with s.lock:
            matured = s.journal.mature(spot_symbol_for={e.ticker: e.spot_symbol for e in s.entries})
            df = s.journal.forecasts(ticker=ticker.upper() if ticker else None, kind=kind, matured_only=True)
        rep = calibrate(df)
        from dataclasses import asdict

        from nightwatch.journal.adjust import evaluate_expanding
        from nightwatch.journal.skill import compare_skill

        adjusted = evaluate_expanding(df) if not df.empty else None
        skill = compare_skill(df) if not df.empty else None
        out = {"matured_now": matured, **asdict(rep), "adjusted": asdict(adjusted) if adjusted else None, "skill": asdict(skill) if skill else None}
        if matured:
            s.calibration_cache.clear()  # new outcomes invalidate every view
        s.calibration_cache[key] = (utc_now(), out)
        return out

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
        from nightwatch.api.llm import chat_turn, credentials_present

        s = st()
        if not credentials_present():
            # The desk is fully usable without a model; only this entry point needs one.
            raise HTTPException(503, "The plain-language desk needs an Anthropic API key (set ANTHROPIC_API_KEY on the server). Everything else, including the ticket form, works without one.")
        try:
            return chat_turn(s, [m.model_dump() for m in body.messages], account_equity=body.account_equity_quote)
        except InsufficientData as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:  # missing or rejected credentials
            raise HTTPException(503, str(exc)) from exc

    return app


app = create_app() if os.environ.get("NIGHTWATCH_AUTOCREATE_APP", "1") == "1" and __name__ != "__main__" else None
