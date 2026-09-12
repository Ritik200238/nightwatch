"""Ticket → report.

This is the one place that wires the layers together. It is deliberately explicit
about *where every number came from* (``sources``) and about what it could not do
(``warnings``), because the report is read by a human who has to trust it.

Analog strategy: search the ticker's own history first; if that yields fewer distinct
episodes than the configured minimum, widen to the pooled history of all tickers with
loaded features (the features are normalised, so cross-ticker comparison is valid),
and say which was used.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.analog.cohort import BaselineComparison, CohortStats, compare_to_baseline, sample_baseline_times, summarize
from nightwatch.analog.engine import AnalogConfig, AnalogEngine, AnalogResult, pooled_history
from nightwatch.analog.outcomes import MatchOutcome, compute_match_outcomes, outcomes_table
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.models import Interval, OrderBookSnapshot, Venue
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.decision.gate import GateInputs, GatePolicy, GateReport, evaluate_gate
from nightwatch.decision.sizing import SizingInputs, SizingPolicy, SizingResult, VerdictResult, decide, recommend_size
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.execution.exit_cost import ExitQuote, HedgeQuote, cost_curve, max_notional_within, quote_exit, quote_hedge
from nightwatch.features.series import SeriesSpec
from nightwatch.features.snapshot import FeatureSnapshot, InsufficientData, build_snapshot, compute_feature_frame
from nightwatch.stress.montecarlo import MonteCarloResult, hourly_log_returns, reverse_stress, simulate
from nightwatch.stress.scenarios import (
    EmpiricalInputs,
    Position,
    Scenario,
    ScenarioImpact,
    Severity,
    apply_scenario,
    build_presets,
    closed_window_returns,
    earnings_gaps,
    impacts_table,
)
from nightwatch.time_utils import ensure_utc, utc_now

log = logging.getLogger(__name__)

BOOK_MAX_AGE = timedelta(minutes=10)


@dataclass
class AnalysisContext:
    store: Store
    entries: list[UniverseEntry]
    spot_client: BitgetPublicClient | None = None
    perp_client: BitgetPublicClient | None = None
    analog_config: AnalogConfig = field(default_factory=AnalogConfig)
    gate_policy: GatePolicy = field(default_factory=GatePolicy)
    sizing_policy: SizingPolicy = field(default_factory=SizingPolicy)
    pooled_tickers: tuple[str, ...] | None = None  # None = all entries with data
    journal: Any = None  # nightwatch.journal.journal.Journal, optional
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    _with_data: tuple[str, ...] | None = None

    def tickers_with_data(self) -> tuple[str, ...]:
        """Universe tickers whose spot symbol has stored hourly bars (one SQL query, cached)."""
        if self._with_data is None:
            rows = self.store._conn.execute(
                "SELECT DISTINCT symbol FROM bars WHERE venue=? AND interval=?", (Venue.BITGET_SPOT.value, Interval.H1.value)
            ).fetchall()
            have = {r[0] for r in rows}
            self._with_data = tuple(e.ticker for e in self.entries if e.spot_symbol in have)
        return self._with_data

    def entry(self, ticker: str) -> UniverseEntry:
        for e in self.entries:
            if e.ticker == ticker.upper():
                return e
        raise KeyError(f"{ticker} is not in the universe")

    def spec(self, ticker: str) -> SeriesSpec:
        e = self.entry(ticker)
        return SeriesSpec(e.ticker, e.spot_symbol, e.perp_symbol, e.yahoo_ticker)

    def feature_frame(self, ticker: str, end: datetime) -> pd.DataFrame:
        """Full-history feature frame for a ticker, cached per process per end-hour."""
        key = f"{ticker}|{ensure_utc(end).replace(minute=0, second=0, microsecond=0).isoformat()}"
        if key not in self._frames:
            spec = self.spec(ticker)
            cov = self.store.bar_coverage(Venue.BITGET_SPOT, spec.spot_symbol, Interval.H1)
            if cov is None:
                raise InsufficientData(f"no stored bars for {spec.spot_symbol}")
            self._frames[key] = compute_feature_frame(self.store, spec, cov[0], end)
        return self._frames[key]


# ------------------------------------------------------------------ report types


@dataclass
class HorizonReport:
    horizon: str
    hours: float
    cohort: CohortStats
    baseline: BaselineComparison | None


@dataclass
class AnalogSection:
    result: AnalogResult
    scope: str  # "same_ticker" | "pooled"
    horizons: dict[str, HorizonReport]
    matches_outcomes: list[MatchOutcome]


@dataclass
class StressSection:
    presets: list[Scenario]
    impacts: list[ScenarioImpact]
    monte_carlo: MonteCarloResult | None
    reverse_move_pct_for_5pct_loss: float | None
    inputs_summary: dict[str, Any]


@dataclass
class ExecutionSection:
    exit_quote: ExitQuote | None
    cost_curve: pd.DataFrame | None
    max_notional_within_budget: float | None
    hedge_quote: HedgeQuote | None
    book_ts: datetime | None
    book_source: str


@dataclass
class AnalysisReport:
    ticket: TradeTicket
    as_of: datetime
    horizon_h: float
    primary_horizon: str
    snapshot: FeatureSnapshot
    analog: AnalogSection | None
    stress: StressSection
    execution: ExecutionSection
    gate: GateReport
    sizing: SizingResult
    verdict: VerdictResult
    sources: list[dict[str, Any]]
    warnings: list[str]
    timings_ms: dict[str, int]
    forecast_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialise(self)


# --------------------------------------------------------------------- analyse


def analyze(ctx: AnalysisContext, ticket: TradeTicket, *, as_of: datetime | None = None, record: bool = True) -> AnalysisReport:
    t_start = time.perf_counter()
    timings: dict[str, int] = {}
    warnings: list[str] = []
    sources: list[dict[str, Any]] = []
    as_of = ensure_utc(as_of or utc_now())
    spec = ctx.spec(ticket.ticker)
    entry_info = ctx.entry(ticket.ticker)
    horizon_h = ticket.horizon_h(as_of)
    primary = f"{max(1, int(round(horizon_h)))}h"

    # 1. Snapshot (now).
    t0 = time.perf_counter()
    snapshot = build_snapshot(ctx.store, spec, as_of)
    timings["snapshot"] = _ms(t0)
    entry_price = ticket.entry_price or snapshot.prices["spot_close"] or 0.0
    sources.append({"kind": "features", "ticker": ticket.ticker, "bar_ts": snapshot.bar_ts.isoformat(), "hash": snapshot.content_hash, "history_hours": snapshot.history_hours})

    # 2. Analog search + outcomes.
    t0 = time.perf_counter()
    frame = ctx.feature_frame(ticket.ticker, as_of)
    analog = _analog_section(ctx, ticket, snapshot, frame, as_of, horizon_h, primary, warnings)
    timings["analog"] = _ms(t0)

    # 3. Order book (recorded, refreshed live if stale and a client exists).
    t0 = time.perf_counter()
    book, book_source = _get_book(ctx, spec.spot_symbol, as_of)
    if book is not None:
        sources.append({"kind": "orderbook", "symbol": spec.spot_symbol, "ts": book.ts.isoformat(), "source": book_source, "levels": len(book.bids) + len(book.asks)})
    else:
        warnings.append("no order book available: exit cost and liquidity caps are unknown")
    fees = _fees(ctx, spec)
    timings["book"] = _ms(t0)

    # 4. Stress.
    t0 = time.perf_counter()
    stress = _stress_section(ctx, ticket, spec, snapshot, frame, book, fees["spot_taker"], horizon_h, entry_price, warnings)
    timings["stress"] = _ms(t0)

    # 5. Execution.
    t0 = time.perf_counter()
    execution = _execution_section(ctx, ticket, spec, frame, book, book_source, fees, horizon_h, entry_info)
    timings["execution"] = _ms(t0)

    # 6. Gate, sizing, verdict.
    t0 = time.perf_counter()
    p5 = _primary_p5(analog, primary)
    exit_bps = execution.exit_quote.total_cost_bps if execution.exit_quote else None
    fully = execution.exit_quote.fully_filled if execution.exit_quote else False
    gate = evaluate_gate(
        ticket,
        GateInputs(
            entry_price=entry_price, equity=ticket.account_equity_quote, analog_p5_loss_pct=p5,
            quality_flags=tuple(snapshot.quality_flags), regime_label=snapshot.labels.get("regime_label", "unknown"),
            risk_multiplier=float(snapshot.features.get("risk_multiplier") or _regime_multiplier(frame)),
            exit_cost_bps=exit_bps, exit_fully_filled=fully,
            recent_losing_exits=(ctx.journal.recent_losing_exits(since=as_of - timedelta(hours=ctx.gate_policy.revenge_cooldown_h)) if ctx.journal is not None else ()),
            now=as_of,
        ),
        ctx.gate_policy,
    )
    severe = [i.total_pct_of_notional for i, s in zip(stress.impacts, stress.presets, strict=True) if s.severity == Severity.SEVERE and i.total_pct_of_notional is not None]
    residual_p5 = None
    if execution.hedge_quote and execution.hedge_quote.residual_basis_p95_bps is not None:
        residual_p5 = -execution.hedge_quote.residual_basis_p95_bps / 100.0
    sizing = recommend_size(
        ticket,
        SizingInputs(
            entry_price=entry_price, equity=ticket.account_equity_quote, stop_distance_pct=ticket.stop_distance_pct(entry_price),
            analog_p5_loss_pct=p5, risk_multiplier=_regime_multiplier(frame),
            max_exit_notional_within_budget=execution.max_notional_within_budget,
            worst_severe_stress_pct=min(severe) if severe else None,
            hedge_cost_bps_of_position=execution.hedge_quote.total_cost_bps_of_position if execution.hedge_quote else None,
            hedge_residual_p5_loss_pct=residual_p5,
        ),
        ctx.sizing_policy,
    )
    verdict = decide(ticket, gate, sizing)
    timings["decision"] = _ms(t0)
    timings["total"] = int((time.perf_counter() - t_start) * 1000)

    report = AnalysisReport(
        ticket=ticket, as_of=as_of, horizon_h=horizon_h, primary_horizon=primary, snapshot=snapshot, analog=analog,
        stress=stress, execution=execution, gate=gate, sizing=sizing, verdict=verdict, sources=sources, warnings=warnings, timings_ms=timings,
    )
    if ctx.journal is not None and record:
        try:
            report.forecast_id = _record(ctx, report)
        except Exception:  # noqa: BLE001 - journaling must never break an analysis
            log.exception("failed to journal the forecast")
    return report


def _record(ctx: AnalysisContext, r: AnalysisReport) -> int:
    stats = r.analog.horizons[r.primary_horizon].cohort if (r.analog and r.primary_horizon in r.analog.horizons) else None
    sign = 1.0 if r.ticket.side.value == "long" else -1.0
    quantiles: dict[str, float | None] = {k: None for k in ("p5", "p25", "p50", "p75", "p95")}
    if stats is not None and not stats.insufficient:
        qs = sorted(sign * q for q in (stats.p5, stats.p25, stats.median_pct, stats.p75, stats.p95))
        quantiles = dict(zip(("p5", "p25", "p50", "p75", "p95"), qs, strict=True))
    mc = r.stress.monte_carlo
    return ctx.journal.record_forecast(
        kind="ticket", ticker=r.ticket.ticker, side=r.ticket.side.value, notional=r.ticket.notional_quote, as_of=r.as_of, bar_ts=r.snapshot.bar_ts,
        horizon_h=r.horizon_h, entry_price=r.ticket.entry_price or r.snapshot.prices["spot_close"] or 0.0, snapshot_hash=r.snapshot.content_hash,
        analog_n=r.analog.result.n if r.analog else 0, analog_scope=r.analog.scope if r.analog else None, quantiles=quantiles,
        es5=(mc.expected_shortfall_5_pct if mc else None), mc_p5=(mc.p5 if mc else None), mc_p95=(mc.p95 if mc else None),
        verdict=r.verdict.verdict.value, recommended_notional=r.verdict.recommended_notional,
        payload={"gate": r.gate.decision.value, "reasons": r.verdict.reasons, "labels": r.snapshot.labels, "flags": r.snapshot.quality_flags, "sources": r.sources},
    )


# ------------------------------------------------------------------- sections


def _analog_section(ctx: AnalysisContext, ticket: TradeTicket, snapshot: FeatureSnapshot, frame: pd.DataFrame, as_of: datetime, horizon_h: float, primary: str, warnings: list[str]) -> AnalogSection | None:
    engine = AnalogEngine(ctx.analog_config)
    query_bucket = snapshot.labels.get("bucket")
    frames: dict[str, pd.DataFrame] = {ticket.ticker: frame}

    result = engine.search(frame.assign(ticker=ticket.ticker), snapshot.features, query_ts=snapshot.bar_ts, query_bucket=query_bucket, query_ticker=ticket.ticker)
    scope = "same_ticker"
    same_ticker_episodes = result.n_distinct_available if result.ok else result.n_distinct_available
    if not result.ok or result.n < ctx.analog_config.k:
        pooled_parts = [(ticket.ticker, frame)]
        tickers = ctx.pooled_tickers or ctx.tickers_with_data()
        for t in tickers:
            if t == ticket.ticker:
                continue
            try:
                f = ctx.feature_frame(t, as_of)
            except InsufficientData:
                continue
            frames[t] = f
            pooled_parts.append((t, f))
        if len(pooled_parts) > 1:
            pooled = pooled_history(pooled_parts)
            pooled_result = engine.search(pooled, snapshot.features, query_ts=snapshot.bar_ts, query_bucket=query_bucket, query_ticker=ticket.ticker)
            if pooled_result.ok and (not result.ok or pooled_result.n > result.n):
                result, scope = pooled_result, "pooled"
                warnings.append(f"same-ticker history has only {same_ticker_episodes} distinct episodes; using pooled history across {len(pooled_parts)} tickers")
    if not result.ok:
        warnings.append(f"analog search refused: {result.reason}")
        return AnalogSection(result=result, scope=scope, horizons={}, matches_outcomes=[])

    # The ticket's own horizon length is applied uniformly to every analog (that is the
    # cohort the verdict uses); the structural horizons are each analog's *own* next
    # open / window end and are reported alongside for context.
    ticket_h = max(1, int(round(horizon_h)))
    fixed = tuple(sorted({24, 72, ticket_h}))
    outcomes: list[MatchOutcome] = []
    for m in result.matches:
        f = frames.get(m.ticker)
        if f is None:
            continue
        try:
            outcomes.append(compute_match_outcomes(f, m.ts, fixed_h=fixed))
        except (KeyError, ValueError):
            continue
    weights = np.array([m.similarity for m in result.matches[: len(outcomes)]])

    horizons: dict[str, HorizonReport] = {}
    horizon_names = [f"{h}h" for h in fixed] + ["next_open", "window_end"]
    cut = frame.index <= pd.Timestamp(snapshot.bar_ts) - pd.Timedelta(hours=ctx.analog_config.min_age_h)
    same_bucket = (frame["bucket"] == query_bucket)[cut]
    closed_mask = frame["is_closed"].astype(bool)[cut]
    exclude = pd.DatetimeIndex([m.ts for m in result.matches])
    base_ts = sample_baseline_times(frame.index[cut], n=min(120, 3 * max(result.n, 1)), bucket_mask=same_bucket, fallback_mask=closed_mask, exclude=exclude, min_separation_h=ctx.analog_config.min_separation_h)
    base_outcomes = [compute_match_outcomes(frame, t.to_pydatetime(), fixed_h=fixed) for t in base_ts]
    for name in horizon_names:
        table = outcomes_table(outcomes, name)
        stats = summarize(table, weights=weights, min_sample=ctx.analog_config.min_matches)
        base_table = outcomes_table(base_outcomes, name)
        comparison = compare_to_baseline(table, base_table, min_sample=ctx.analog_config.min_matches) if not table.empty and not base_table.empty else None
        hours = float(table["hours"].mean()) if not table.empty else float("nan")
        horizons[name] = HorizonReport(horizon=name, hours=hours, cohort=stats, baseline=comparison)
    if primary in horizons and horizons[primary].cohort.insufficient:
        warnings.append(f"analog cohort for the {primary} horizon is below the minimum sample; verdict falls back to the stop for risk")
    return AnalogSection(result=result, scope=scope, horizons=horizons, matches_outcomes=outcomes)


def _stress_section(ctx: AnalysisContext, ticket: TradeTicket, spec: SeriesSpec, snapshot: FeatureSnapshot, frame: pd.DataFrame, book: OrderBookSnapshot | None, taker_fee: float, horizon_h: float, entry_price: float, warnings: list[str]) -> StressSection:
    daily = ctx.store.get_bars(Venue.YAHOO, spec.yahoo_ticker, Interval.D1)
    events = ctx.store.get_earnings(ticket.ticker)
    closed = closed_window_returns(frame)
    gaps = earnings_gaps(daily, events)
    basis_closed = frame.loc[frame["is_closed"].astype(bool), "basis_index_bps"].abs().dropna().to_numpy()
    funding_p95 = 0.0
    if spec.perp_symbol:
        fr = ctx.store.get_funding(Venue.BITGET_UMCBL, spec.perp_symbol)
        if not fr.empty:
            funding_p95 = float(fr["rate"].abs().quantile(0.95))
    inp = EmpiricalInputs(closed_window_ret_pct=closed, earnings_gap_pct=gaps, abs_basis_closed_bps=basis_closed, rv_24h_now=float(snapshot.features.get("rv_24h") or 0.0), horizon_h=horizon_h, funding_rate_abs_p95=funding_p95)
    presets = build_presets(inp)
    position = Position(ticket.ticker, ticket.side, ticket.notional_quote, entry_price, hedge_ratio=ticket.hedge_ratio or 0.0)
    impacts = [apply_scenario(position, p, book=book, taker_fee=taker_fee) for p in presets]

    mc = None
    rets = hourly_log_returns(frame, closed_only=ticket.horizon_kind != HorizonKind.HOURS)
    if rets.size < 48:
        rets = hourly_log_returns(frame, closed_only=False)
    if rets.size >= 48 and horizon_h >= 1:
        mc = simulate(position.sign, rets, int(round(horizon_h)))
    else:
        warnings.append("not enough hourly history for a Monte Carlo over the horizon")
    reverse = reverse_stress(position, book=book, taker_fee=taker_fee, target_loss_pct=ctx.sizing_policy.max_stress_loss_pct, horizon_h=horizon_h) if book is not None else None
    return StressSection(
        presets=presets, impacts=impacts, monte_carlo=mc, reverse_move_pct_for_5pct_loss=reverse,
        inputs_summary={"closed_windows_n": int(closed.size), "earnings_gaps_n": int(gaps.size), "closed_basis_obs_n": int(basis_closed.size), "rv_24h": inp.rv_24h_now, "funding_abs_p95": funding_p95, "mc_source_hours": int(rets.size)},
    )


def _execution_section(ctx: AnalysisContext, ticket: TradeTicket, spec: SeriesSpec, frame: pd.DataFrame, book: OrderBookSnapshot | None, book_source: str, fees: dict[str, float], horizon_h: float, entry: UniverseEntry) -> ExecutionSection:
    exit_quote = curve = None
    max_n = None
    if book is not None:
        exit_quote = quote_exit(book, ticket.notional_quote, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"])
        curve = cost_curve(book, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"])
        max_n = max_notional_within(book, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"], budget_bps=ctx.sizing_policy.exit_cost_budget_bps)
    hedge = None
    if entry.perp_symbol:
        fr = ctx.store.get_funding(Venue.BITGET_UMCBL, entry.perp_symbol)
        now_rate = float(fr["rate"].iloc[-1]) if not fr.empty else 0.0
        p95 = float(fr["rate"].abs().quantile(0.95)) if not fr.empty else 0.0
        basis_closed = frame.loc[frame["is_closed"].astype(bool), "basis_index_bps"].abs().dropna()
        residual = float(basis_closed.quantile(0.95)) if len(basis_closed) >= 20 else None
        hedge = quote_hedge(position_notional=ticket.notional_quote, hedge_ratio=1.0, horizon_h=horizon_h, perp_symbol=entry.perp_symbol, perp_fee=fees["perp_taker"], funding_rate_now=now_rate, funding_rate_abs_p95=p95, residual_basis_abs_p95_bps=residual)
    return ExecutionSection(exit_quote=exit_quote, cost_curve=curve, max_notional_within_budget=max_n, hedge_quote=hedge, book_ts=book.ts if book else None, book_source=book_source)


# -------------------------------------------------------------------- helpers


def _get_book(ctx: AnalysisContext, symbol: str, as_of: datetime) -> tuple[OrderBookSnapshot | None, str]:
    snap = ctx.store.latest_orderbook(Venue.BITGET_SPOT, symbol)
    if snap is not None and as_of - snap.ts <= BOOK_MAX_AGE:
        return snap, "recorded"
    if ctx.spot_client is not None:
        try:
            live = ctx.spot_client.get_orderbook(symbol)
            ctx.store.insert_orderbook(live)
            return live, "live"
        except Exception as exc:  # noqa: BLE001
            log.warning("live book fetch failed for %s: %s", symbol, exc)
    if snap is not None:
        return snap, f"recorded (stale by {(as_of - snap.ts).total_seconds() / 60:.0f} min)"
    return None, "none"


def _fees(ctx: AnalysisContext, spec: SeriesSpec) -> dict[str, float]:
    spot = {i.symbol: i for i in ctx.store.list_instruments(Venue.BITGET_SPOT)}
    perp = {i.symbol: i for i in ctx.store.list_instruments(Venue.BITGET_UMCBL)}
    s = spot.get(spec.spot_symbol)
    p = perp.get(spec.perp_symbol) if spec.perp_symbol else None
    return {
        "spot_taker": float(s.taker_fee) if s and s.taker_fee is not None else 0.001,
        "spot_maker": float(s.maker_fee) if s and s.maker_fee is not None else 0.001,
        "perp_taker": float(p.taker_fee) if p and p.taker_fee is not None else 0.0006,
        "perp_maker": float(p.maker_fee) if p and p.maker_fee is not None else 0.0002,
    }


def _regime_multiplier(frame: pd.DataFrame) -> float:
    if "risk_multiplier" not in frame or frame.empty:
        return 1.0
    v = frame["risk_multiplier"].dropna()
    return float(v.iloc[-1]) if len(v) else 1.0


def _primary_p5(analog: AnalogSection | None, primary: str) -> float | None:
    if analog is None or primary not in analog.horizons:
        return None
    stats = analog.horizons[primary].cohort
    return None if stats.insufficient else stats.p5


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _serialise(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return obj.reset_index().to_dict(orient="records") if obj is not None else None
    if isinstance(obj, pd.Timestamp | datetime):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return [None if (isinstance(x, float) and np.isnan(x)) else float(x) for x in obj.tolist()]
    if isinstance(obj, np.generic):  # numpy bool/int/float scalars
        v = obj.item()
        return None if isinstance(v, float) and np.isnan(v) else v
    if isinstance(obj, float) and np.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {str(k): _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_serialise(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialise(v) for k, v in asdict(obj).items()} if not hasattr(obj, "to_dict") or isinstance(obj, AnalysisReport) else obj.to_dict()
    if hasattr(obj, "value") and isinstance(getattr(obj, "value"), str):
        return obj.value
    return obj
