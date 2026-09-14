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
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from nightwatch.analog.cohort import BaselineComparison, CohortStats, compare_to_baseline, sample_baseline_times, summarize
from nightwatch.analog.engine import AnalogConfig, AnalogEngine, AnalogResult, pooled_history
from nightwatch.analog.outcomes import MatchOutcome, compute_match_outcomes, outcomes_table
from nightwatch.analog.regimes import RegimeMap
from nightwatch.analog.regimes import build as build_regimes
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.models import Interval, OrderBookSnapshot, Venue
from nightwatch.data.store import Store
from nightwatch.data.sync import UniverseEntry
from nightwatch.decision.breaker import BreakerPolicy, BreakerReport, BreakerState
from nightwatch.decision.breaker import evaluate as evaluate_breaker
from nightwatch.decision.gate import GatePolicy, GateReport
from nightwatch.decision.portfolio import PortfolioReport
from nightwatch.decision.portfolio import Position as BookPosition
from nightwatch.decision.portfolio import evaluate as evaluate_portfolio
from nightwatch.decision.sensitivity import DecisionContext, SensitivityReport, build_sensitivity
from nightwatch.decision.sizing import SizingPolicy, SizingResult, VerdictResult
from nightwatch.decision.ticket import HorizonKind, TradeTicket
from nightwatch.execution.exit_cost import ExitQuote, HedgeQuote, cost_curve, max_notional_within, quote_exit, quote_hedge
from nightwatch.execution.liquidity_history import LiquidityHistory
from nightwatch.execution.liquidity_history import summarise as summarise_liquidity
from nightwatch.features.series import SeriesSpec
from nightwatch.features.snapshot import FeatureSnapshot, InsufficientData, build_snapshot, compute_feature_frame
from nightwatch.stress.montecarlo import MonteCarloResult, hourly_log_returns, reverse_stress, simulate
from nightwatch.stress.scenarios import (
    EmpiricalInputs,
    Position,
    Scenario,
    ScenarioImpact,
    apply_scenario,
    build_presets,
    closed_window_returns,
    earnings_gaps,
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
    breaker_policy: BreakerPolicy = field(default_factory=BreakerPolicy)
    sizing_policy: SizingPolicy = field(default_factory=SizingPolicy)
    pooled_tickers: tuple[str, ...] | None = None  # None = all entries with data
    journal: Any = None  # nightwatch.journal.journal.Journal, optional
    sensitivity: bool = True  # run the size/stop what-if sweeps
    frame_cache_size: int = 64  # >= universe size so a warm cache survives one hour of traffic
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    _book_windows: dict[str, pd.DataFrame] = field(default_factory=dict)
    _with_data: tuple[str, ...] | None = None
    _factors_cache: dict[str, Any] = field(default_factory=dict)

    def tail_factors(self, as_of: datetime):  # noqa: ANN201
        """Tail-calibration factors fitted on replay forecasts matured before ``as_of``
        (None when the journal is absent or has too few matured replays)."""
        if self.journal is None:
            return None
        key = ensure_utc(as_of).replace(minute=0, second=0, microsecond=0).isoformat()
        if key not in self._factors_cache:
            from nightwatch.journal.adjust import factors_as_of

            try:
                df = self.journal.forecasts(kind="replay", matured_only=True)
                self._factors_cache[key] = factors_as_of(df, as_of) if not df.empty else None
            except Exception:  # noqa: BLE001
                log.exception("tail factor fit failed")
                self._factors_cache[key] = None
        return self._factors_cache[key]

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

    def liquidity_frame(self, symbol: str, as_of: datetime, *, days: int = 30):  # noqa: ANN201
        """The recorded book window for one symbol, bucketed, cached per hour.

        The archive grows by a snapshot a minute per book, so this is the part worth
        keeping; the aggregation on top of it depends on the ticket size and is cheap."""
        from nightwatch.execution.liquidity_history import load as load_books
        from nightwatch.execution.liquidity_history import prepare

        key = f"{symbol}|{ensure_utc(as_of).replace(minute=0, second=0, microsecond=0).isoformat()}"
        cached = self._book_windows.pop(key, None)
        if cached is None:
            cached = prepare(load_books(self.store, symbol, since=ensure_utc(as_of) - timedelta(days=days)))
        self._book_windows[key] = cached
        while len(self._book_windows) > 32:
            self._book_windows.pop(next(iter(self._book_windows)))
        return cached

    def feature_frame(self, ticker: str, end: datetime) -> pd.DataFrame:
        """Full-history feature frame for a ticker, cached per process per end-hour.

        The cache is bounded (least-recently-used eviction) because an always-on API
        sees a new end-hour every hour and replays ask for arbitrary as-of hours; an
        unbounded map would grow by a full frame per ticker per hour for weeks."""
        key = f"{ticker}|{ensure_utc(end).replace(minute=0, second=0, microsecond=0).isoformat()}"
        frame = self._frames.pop(key, None)
        if frame is None:
            spec = self.spec(ticker)
            cov = self.store.bar_coverage(Venue.BITGET_SPOT, spec.spot_symbol, Interval.H1)
            if cov is None:
                raise InsufficientData(f"no stored bars for {spec.spot_symbol}")
            frame = compute_feature_frame(self.store, spec, cov[0], end)
        self._frames[key] = frame  # re-insert as most recent
        while len(self._frames) > self.frame_cache_size:
            self._frames.pop(next(iter(self._frames)))
        while len(self._factors_cache) > 64:
            self._factors_cache.pop(next(iter(self._factors_cache)))
        return frame


# ------------------------------------------------------------------ report types


@dataclass
class HorizonReport:
    horizon: str
    hours: float
    cohort: CohortStats
    baseline: BaselineComparison | None
    p5_adjusted: float | None = None  # tail-calibrated (see journal.adjust)
    p95_adjusted: float | None = None
    adjustment: dict[str, Any] | None = None  # k_lo, k_hi, n_fit, fitted_through


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
    liquidity_history: LiquidityHistory | None = None


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
    sensitivity: SensitivityReport | None
    lessons: list[dict[str, Any]]
    breaker: BreakerReport
    portfolio: PortfolioReport | None
    regimes: RegimeMap | None
    sources: list[dict[str, Any]]
    warnings: list[str]
    timings_ms: dict[str, int]
    forecast_id: int | None = None
    second_opinion: Any = None  # nightwatch.decision.devil.SecondOpinion

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
    execution = _execution_section(ctx, ticket, spec, frame, book, book_source, fees, horizon_h, entry_info, as_of)
    timings["execution"] = _ms(t0)

    # 6. Gate, sizing, verdict.
    t0 = time.perf_counter()
    p5 = _primary_p5(analog, primary)
    residual_p5 = None
    if execution.hedge_quote and execution.hedge_quote.residual_basis_p95_bps is not None:
        residual_p5 = -execution.hedge_quote.residual_basis_p95_bps / 100.0
    # The trader's own recent record, which has nothing to do with this trade's merits.
    breaker = BreakerReport(state=BreakerState.NORMAL, reasons=["no journal"], equity=ticket.account_equity_quote)
    if ctx.journal is not None:
        try:
            breaker = evaluate_breaker(ctx.journal.taken_trades(matured_only=False), equity=ticket.account_equity_quote, now=as_of, policy=ctx.breaker_policy)
        except Exception:  # noqa: BLE001
            log.exception("circuit breaker evaluation failed")

    # One context drives the headline decision and every what-if, so a swept verdict
    # can never be computed differently from the one on the report.
    dc = DecisionContext(
        entry_price=entry_price, analog_p5_loss_pct=p5, quality_flags=tuple(snapshot.quality_flags),
        regime_label=snapshot.labels.get("regime_label", "unknown"),
        risk_multiplier=float(snapshot.features.get("risk_multiplier") or _regime_multiplier(frame)),
        recent_losing_exits=(ctx.journal.recent_losing_exits(since=as_of - timedelta(hours=ctx.gate_policy.revenge_cooldown_h)) if ctx.journal is not None else ()),
        breaker_state=breaker.state.value, breaker_reason="; ".join(breaker.reasons[:2]),
        now=as_of, book=book, spot_taker_fee=fees["spot_taker"], presets=tuple(stress.presets),
        max_exit_notional_within_budget=execution.max_notional_within_budget,
        hedge_cost_bps_of_position=execution.hedge_quote.total_cost_bps_of_position if execution.hedge_quote else None,
        hedge_residual_p5_loss_pct=residual_p5, gate_policy=ctx.gate_policy, sizing_policy=ctx.sizing_policy,
    )
    ev = dc.evaluate(
        ticket, impacts=stress.impacts,
        exit_cost_bps=execution.exit_quote.total_cost_bps if execution.exit_quote else None,
        exit_fully_filled=execution.exit_quote.fully_filled if execution.exit_quote else False,
    )
    gate, sizing, verdict = ev.gate, ev.sizing, ev.verdict
    timings["decision"] = _ms(t0)

    # 7. What happened last time conditions looked like this.
    lessons: list[dict[str, Any]] = []
    if ctx.journal is not None:
        try:
            from nightwatch.journal.postmortem import LessonBook

            book = LessonBook(ctx.journal)
            for x in book.recall(ticker=ticket.ticker, bucket=snapshot.labels.get("bucket"), regime_label=snapshot.labels.get("regime_label"), as_of=as_of, limit=3):
                lessons.append({
                    "forecast_id": x.forecast_id, "as_of": x.as_of.isoformat(), "ticker": x.ticker, "kind": x.kind,
                    "classification": x.classification.value, "text": x.text, "notable": x.notable,
                    "ret_pct": x.ret_pct, "p5": x.p5, "bucket": x.bucket, "regime_label": x.regime_label,
                })
        except Exception:  # noqa: BLE001 - memory is a nicety; it must never break a verdict
            log.exception("lesson recall failed")

    # 8. The coarse map: what state this is, and what usually follows it.
    t0 = time.perf_counter()
    regimes = None
    try:
        regimes = build_regimes(frame, as_of=pd.Timestamp(snapshot.bar_ts), horizon_h=max(1, int(round(horizon_h))))
    except Exception:  # noqa: BLE001 - a map is not worth breaking a verdict for
        log.exception("regime map failed")
    timings["regimes"] = _ms(t0)

    # 9. The rest of the book, if the trader told us about it.
    t0 = time.perf_counter()
    portfolio = None
    if ticket.open_positions:
        try:
            held = [BookPosition(t.upper(), s, float(n)) for t, s, n in ticket.open_positions]
            frames: dict[str, pd.DataFrame] = {ticket.ticker: frame}
            for pos in held:
                if pos.ticker not in frames:
                    try:
                        frames[pos.ticker] = ctx.feature_frame(pos.ticker, as_of)
                    except (InsufficientData, KeyError):
                        frames[pos.ticker] = pd.DataFrame()
            portfolio = evaluate_portfolio(
                held, BookPosition(ticket.ticker, ticket.side.value, ticket.notional_quote), frames,
                equity=ticket.account_equity_quote, horizon_h=horizon_h,
            )
        except Exception:  # noqa: BLE001 - the book view must never break the verdict
            log.exception("portfolio evaluation failed")

    timings["portfolio"] = _ms(t0)

    # 10. Sensitivity: what would have to change.
    t0 = time.perf_counter()
    sensitivity = None
    if ctx.sensitivity:
        try:
            sensitivity = build_sensitivity(dc, ticket, headline=ev)
        except Exception:  # noqa: BLE001 - a what-if must never break the decision
            log.exception("sensitivity sweep failed")
            warnings.append("sensitivity sweep failed; the verdict above is unaffected")
    timings["sensitivity"] = _ms(t0)
    timings["total"] = int((time.perf_counter() - t_start) * 1000)

    report = AnalysisReport(
        ticket=ticket, as_of=as_of, horizon_h=horizon_h, primary_horizon=primary, snapshot=snapshot, analog=analog,
        stress=stress, execution=execution, gate=gate, sizing=sizing, verdict=verdict, sensitivity=sensitivity, lessons=lessons, breaker=breaker, portfolio=portfolio, regimes=regimes, sources=sources, warnings=warnings, timings_ms=timings,
    )
    # The case against whatever was just decided, from the report's own numbers.
    try:
        from nightwatch.decision.devil import build as build_second_opinion

        report.second_opinion = build_second_opinion(report)
    except Exception:  # noqa: BLE001
        log.exception("second opinion failed")

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
        # Raw analog quantiles are journaled (they are what calibration refits on);
        # the adjusted tails go in the payload so a report can be audited either way.
        qs = sorted(sign * q for q in (stats.p5, stats.p25, stats.median_pct, stats.p75, stats.p95))
        quantiles = dict(zip(("p5", "p25", "p50", "p75", "p95"), qs, strict=True))
    h = r.analog.horizons[r.primary_horizon] if (r.analog and r.primary_horizon in r.analog.horizons) else None
    mc = r.stress.monte_carlo
    return ctx.journal.record_forecast(
        kind="ticket", ticker=r.ticket.ticker, side=r.ticket.side.value, notional=r.ticket.notional_quote, as_of=r.as_of, bar_ts=r.snapshot.bar_ts,
        horizon_h=r.horizon_h, entry_price=r.ticket.entry_price or r.snapshot.prices["spot_close"] or 0.0, snapshot_hash=r.snapshot.content_hash,
        analog_n=r.analog.result.n if r.analog else 0, analog_scope=r.analog.scope if r.analog else None, quantiles=quantiles,
        es5=(mc.expected_shortfall_5_pct if mc else None), mc_p5=(mc.p5 if mc else None), mc_p95=(mc.p95 if mc else None),
        verdict=r.verdict.verdict.value, recommended_notional=r.verdict.recommended_notional,
        payload={
            "gate": r.gate.decision.value, "reasons": r.verdict.reasons, "labels": r.snapshot.labels, "flags": r.snapshot.quality_flags, "sources": r.sources,
            "p5_adjusted": (h.p5_adjusted if h else None), "p95_adjusted": (h.p95_adjusted if h else None), "adjustment": (h.adjustment if h else None),
        },
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
    factors = ctx.tail_factors(as_of)
    for name in horizon_names:
        table = outcomes_table(outcomes, name)
        stats = summarize(table, weights=weights, min_sample=ctx.analog_config.min_matches)
        base_table = outcomes_table(base_outcomes, name)
        comparison = compare_to_baseline(table, base_table, min_sample=ctx.analog_config.min_matches) if not table.empty and not base_table.empty else None
        hours = float(table["hours"].mean()) if not table.empty else float("nan")
        p5_adj = p95_adj = None
        adjustment = None
        if factors is not None and not stats.insufficient:
            from nightwatch.journal.adjust import apply_factors

            p5_adj, p95_adj = apply_factors(stats.p5, stats.median_pct, stats.p95, factors)
            adjustment = {"k_lo": factors.k_lo, "k_hi": factors.k_hi, "n_fit": factors.n_fit, "fitted_through": factors.fitted_through.isoformat() if factors.fitted_through else None, "scope": factors.scope}
        horizons[name] = HorizonReport(horizon=name, hours=hours, cohort=stats, baseline=comparison, p5_adjusted=p5_adj, p95_adjusted=p95_adj, adjustment=adjustment)
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


def _execution_section(ctx: AnalysisContext, ticket: TradeTicket, spec: SeriesSpec, frame: pd.DataFrame, book: OrderBookSnapshot | None, book_source: str, fees: dict[str, float], horizon_h: float, entry: UniverseEntry, as_of: datetime) -> ExecutionSection:
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
    # What the recorded archive says about this book at other times of the week.
    history = None
    try:
        history = summarise_liquidity(ctx.store, spec.spot_symbol, reference=ticket.notional_quote, frame=ctx.liquidity_frame(spec.spot_symbol, as_of))
    except Exception:  # noqa: BLE001
        log.exception("liquidity history failed")
    return ExecutionSection(
        exit_quote=exit_quote, cost_curve=curve, max_notional_within_budget=max_n, hedge_quote=hedge,
        book_ts=book.ts if book else None, book_source=book_source, liquidity_history=history,
    )


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
    """The 5th-percentile loss the verdict sizes against: tail-calibrated when
    replay evidence exists, raw otherwise."""
    if analog is None or primary not in analog.horizons:
        return None
    h = analog.horizons[primary]
    if h.cohort.insufficient:
        return None
    return h.p5_adjusted if h.p5_adjusted is not None else h.cohort.p5


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
        # Walk one level at a time rather than asdict(), which is deep and would flatten a
        # nested object before its own to_dict() ever ran - which is how ten thousand
        # Monte Carlo path values kept ending up in the response.
        if hasattr(obj, "to_dict") and not isinstance(obj, AnalysisReport):
            return _serialise(obj.to_dict())
        return {f.name: _serialise(getattr(obj, f.name)) for f in fields(obj)}
    if hasattr(obj, "value") and isinstance(obj.value, str):
        return obj.value
    return obj
