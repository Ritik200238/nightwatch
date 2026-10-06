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

import contextlib
import contextvars
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace
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
from nightwatch.decision.portfolio import PortfolioReport, build_book_model
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
    closed_windows_in_hold,
    crash_replays,
    earnings_gaps,
    earnings_in_window,
)
from nightwatch.time_utils import classify_session, ensure_utc, round_half_up, utc_now

log = logging.getLogger(__name__)

BOOK_MAX_AGE = timedelta(minutes=10)
# The longest hold the tail calibration has scored forecasts for (the journal's longest is
# 90 hours). Beyond it no factor is applied.
CALIBRATED_MAX_H = 96.0
OUTCOME_CACHE = 4000  # a few analyses' worth of matches and baseline hours
BASELINE_CACHE = 200


def _remember(cache: dict, key: tuple, value: Any, limit: int) -> None:  # noqa: ANN401
    cache[key] = value
    while len(cache) > limit:
        cache.pop(next(iter(cache)))


def _digest(table: pd.DataFrame) -> tuple:
    """The whole table - every column and row, in order - as a hashable key. Order counts:
    the permutation test shuffles the rows as given, so the same rows in another order
    give another p-value."""
    return (tuple(table.columns), pd.util.hash_pandas_object(table, index=True).to_numpy().tobytes())
# When the book now is this much wider than its median over the lookback, and by at least
# this many bps, it is a momentary blowout rather than the book, and does not set the size.
WIDE_BOOK_LOOKBACK = timedelta(hours=2)
WIDE_BOOK_RATIO = 2.5
WIDE_BOOK_MIN_BPS = 10.0


@dataclass
class AnalysisContext:
    store: Store
    entries: list[UniverseEntry]
    spot_client: BitgetPublicClient | None = None
    perp_client: BitgetPublicClient | None = None
    analog_config: AnalogConfig = field(default_factory=AnalogConfig.vol_focused)
    gate_policy: GatePolicy = field(default_factory=GatePolicy)
    breaker_policy: BreakerPolicy = field(default_factory=BreakerPolicy)
    sizing_policy: SizingPolicy = field(default_factory=SizingPolicy)
    pooled_tickers: tuple[str, ...] | None = None  # None = all entries with data
    journal: Any = None  # nightwatch.journal.journal.Journal, optional
    # Bitget's US-stock data service (nightwatch.data.bitget_mcp.BitgetMcpClient), for the
    # street and insider context and an independent quote. Optional: without it the
    # report simply has no street section.
    street_client: Any = None
    # The rest of that catalogue (nightwatch.features.bitget_data.BitgetData): earnings
    # calendar, valuation, dividends, consensus, profile. A cache plus a refresher that
    # makes at most one call per ticker per entry per hour; an analysis only reads it.
    bitget_data: Any = None
    _bitget_pending: set[str] = field(default_factory=set)
    # Bitget's bitget-signal Skill backend (nightwatch.data.bitget_signal.BitgetSignalClient):
    # an RSI reading, shown only when it agrees with the desk's own candles. Context only.
    signal_client: Any = None
    # Bitget Wallet's tokenized-stock listing (nightwatch.data.bitget_rwa.BitgetRwaClient):
    # tradable status, pause or alert text, per-order size limits. Cached, refreshed in the
    # background, never waited on.
    rwa_client: Any = None
    _rwa: dict[str, tuple[datetime, dict | None]] = field(default_factory=dict)
    _rwa_pending: set[str] = field(default_factory=set)
    sensitivity: bool = True  # run the size/stop what-if sweeps
    frame_cache_size: int = 64  # >= universe size so a warm cache survives one hour of traffic
    _frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Frames for an end-hour older than the newest one held for that token: a what-if on a report
    # from earlier in the day asks for one. Kept apart so they never push a hot frame out of
    # ``_frames`` (the pooled search needs every token's newest), and few, since each is ~6.6 MB.
    _older_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Fee rates per symbol pair, good for FEES_TTL_S: reading them parsed every instrument of both
    # venues (about 3,500 JSON rows) on every analysis and every what-if.
    _fee_cache: dict[tuple[str, str | None], tuple[float, dict[str, float]]] = field(default_factory=dict)
    _book_windows: dict[str, pd.DataFrame] = field(default_factory=dict)
    _with_data: tuple[str, ...] | None = None
    _factors_cache: dict[str, Any] = field(default_factory=dict)
    _street: dict[str, tuple[datetime, Any]] = field(default_factory=dict)
    _street_pending: set[str] = field(default_factory=set)
    _open_interest: dict[str, tuple[datetime, tuple[float, datetime] | None]] = field(default_factory=dict)
    # Cboe's delayed option quotes (nightwatch.data.cboe.CboeOptionsClient), reduced to one
    # at-the-money quote per expiry. Optional: without it the report has no implied move.
    options_client: Any = None
    _options: dict[str, tuple[datetime, Any]] = field(default_factory=dict)  # chain, "none" (no options) or None (failed)
    _options_pending: set[str] = field(default_factory=set)
    _options_failed: dict[str, datetime] = field(default_factory=dict)
    _signal: dict[str, tuple[datetime, dict | None]] = field(default_factory=dict)
    _signal_pending: set[str] = field(default_factory=set)
    _signal_health: tuple[datetime, dict] | None = None
    _profiles: dict[str, tuple[datetime, dict[str, float]]] = field(default_factory=dict)
    _degraded: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    _tiers: dict[str, tuple[datetime, list[Any]]] = field(default_factory=dict)
    _tiers_failed: dict[str, datetime] = field(default_factory=dict)
    # Network fetches an analysis may need but must never sit through: one background thread
    # per key, and the request waits for it only up to a short bound.
    _inflight: dict[str, threading.Event] = field(default_factory=dict)
    # What followed a past hour, and how a cohort compared with random hours, depend only
    # on their inputs. "Compare ways" and every what-if rerun the same moment with one
    # thing changed, so most of these repeat exactly; recomputing them was most of the
    # 1.5-2 s an analysis spends after the search. Bounded, oldest out first.
    _outcomes: dict[tuple, Any] = field(default_factory=dict)
    _baselines: dict[tuple, Any] = field(default_factory=dict)
    _memo_lock: threading.Lock = field(default_factory=threading.Lock)
    # A what-if re-runs the same ticker at the same moment with one thing changed, so the
    # snapshot and the regime map are identical to the run before. Keyed by the moment and the
    # frame, bounded, oldest out first.
    _snapshots: dict[tuple, Any] = field(default_factory=dict)
    _regime_maps: dict[tuple, Any] = field(default_factory=dict)

    def snapshot_at(self, spec: SeriesSpec, as_of: datetime) -> FeatureSnapshot:
        key = (spec.ticker, ensure_utc(as_of).isoformat())
        hit = self._snapshots.get(key)
        if hit is None:
            hit = build_snapshot(self.store, spec, as_of)
            with self._memo_lock:
                _remember(self._snapshots, key, hit, 32)
        return hit

    def regimes_at(self, frame: pd.DataFrame, bar_ts: Any, horizon: int) -> RegimeMap:  # noqa: ANN401
        key = (id(frame), len(frame), pd.Timestamp(bar_ts), horizon)
        hit = self._regime_maps.get(key)
        if hit is None:
            hit = build_regimes(frame, as_of=pd.Timestamp(bar_ts), horizon_h=horizon)
            with self._memo_lock:
                _remember(self._regime_maps, key, hit, 32)
        return hit

    def match_outcomes(self, frame: pd.DataFrame, ts: datetime, fixed: tuple[int, ...]) -> MatchOutcome:
        key = (id(frame), len(frame), frame.index[0], frame.index[-1], pd.Timestamp(ts), fixed)
        hit = self._outcomes.get(key)
        if hit is None:
            hit = compute_match_outcomes(frame, ts, fixed_h=fixed)
            with self._memo_lock:
                _remember(self._outcomes, key, hit, OUTCOME_CACHE)
        return hit

    def baseline_comparison(self, table: pd.DataFrame, base_table: pd.DataFrame, min_sample: int) -> BaselineComparison:
        key = (_digest(table), _digest(base_table), min_sample)
        hit = self._baselines.get(key)
        if hit is None:
            hit = compare_to_baseline(table, base_table, min_sample=min_sample)
            with self._memo_lock:
                _remember(self._baselines, key, hit, BASELINE_CACHE)
        return hit

    def _fetch_within(self, key: str, work: Callable[[], None], wait_s: float) -> None:
        """Run ``work`` on one background thread per ``key`` and wait for it at most ``wait_s``.

        A Bitget call on the request path used to hold a chat for as long as the exchange took
        to answer - with its retries, tens of seconds during an outage. The work still runs to
        the end and fills its cache; the request just stops waiting for it."""
        with self._memo_lock:
            done = self._inflight.get(key)
            if done is None:
                done = self._inflight[key] = threading.Event()

                def run() -> None:
                    try:
                        work()
                    finally:
                        done.set()
                        with self._memo_lock:
                            self._inflight.pop(key, None)

                threading.Thread(target=run, name=f"fetch-{key}", daemon=True).start()
        if wait_s > 0:
            done.wait(wait_s)

    def margin_tiers(self, perp_symbol: str | None, *, wait_s: float | None = None) -> list[Any] | None:
        """Bitget's margin tiers for a perp, cached for a day. None when there is no perp
        client or no table yet; the leverage view then says it assumed a rate.

        Never holds a request for long: a stale table is served at once while a fresh one is
        fetched in the background, a missing one is waited for at most ``wait_s`` (the warm-up
        normally has it before anyone asks), and a failed fetch is not retried for a few
        minutes, so an exchange outage costs a leveraged chat nothing."""
        if not perp_symbol or self.perp_client is None:
            return None
        now = utc_now()
        hit = self._tiers.get(perp_symbol)
        if hit and now - hit[0] < timedelta(hours=24):
            return hit[1]
        failed = self._tiers_failed.get(perp_symbol)
        if failed and now - failed < TIERS_RETRY:
            return hit[1] if hit else None
        from nightwatch.execution.leverage import parse_tiers

        def work() -> None:
            try:
                tiers = parse_tiers(self.perp_client.get_position_tiers(perp_symbol))
            except Exception as exc:  # noqa: BLE001 - an assumed rate, said so, beats no answer
                log.warning("margin tiers for %s unavailable: %s", perp_symbol, exc)
                self._tiers_failed[perp_symbol] = utc_now()
                return
            self._tiers[perp_symbol] = (utc_now(), tiers)
            self._tiers_failed.pop(perp_symbol, None)

        self._fetch_within(f"tiers-{perp_symbol}", work, 0.0 if hit else (TIERS_WAIT_S if wait_s is None else wait_s))
        hit = self._tiers.get(perp_symbol)
        return hit[1] if hit else None

    def open_interest_for(self, perp_symbol: str | None, *, price: float | None = None, ttl: timedelta | None = None) -> dict | None:
        """Open interest on the token's perp, cached for a few minutes.

        One small public request (about 0.1 s) per token per ``ttl``, so a busy minute of
        analyses costs one call per token, not one per analysis. A failure is cached for a
        minute as "nothing" so a down endpoint is not retried by every request, and never
        raises: this is context for a leveraged trade, not part of the verdict.
        """
        if not perp_symbol or self.perp_client is None:
            return None
        now = utc_now()
        hit = self._open_interest.get(perp_symbol)
        from nightwatch.features import open_interest as oi_mod

        def block_of(raw: tuple[float, datetime] | None) -> dict | None:
            # The dollar figure needs the price of the analysis asking, so it is worked out here
            # from the raw reading, not stored with it.
            return oi_mod.build(perp_symbol, raw[0], raw[1], self.store, price=price) if raw else None

        if hit and now - hit[0] <= ((ttl or OI_TTL) if hit[1] else OI_RETRY):
            return block_of(hit[1])

        def work() -> None:
            try:
                raw = self.perp_client.get_open_interest(perp_symbol)
            except Exception as exc:  # noqa: BLE001 - context must never fail an analysis
                log.warning("open interest for %s unavailable: %s", perp_symbol, exc)
                self._open_interest[perp_symbol] = (utc_now(), None)
                return
            self._open_interest[perp_symbol] = (utc_now(), raw)

        # A reading under half an hour old is served while a fresh one is fetched behind it;
        # without one, the request waits a moment for the fetch and otherwise goes without.
        usable = hit is not None and hit[1] is not None and now - hit[0] <= OI_STALE_MAX
        self._fetch_within(f"oi-{perp_symbol}", work, 0.0 if usable else OI_WAIT_S)
        got = self._open_interest.get(perp_symbol)
        return block_of(got[1]) if got else None

    def options_chain_for(self, ticker: str, *, fetch: bool = False):  # noqa: ANN201
        """The cached options chain for a ticker: an ``OptionsChain``, ``"none"`` when the
        underlying has no listed options, or None when nothing usable is cached.

        Never waits on the network unless asked to (``fetch=True``, the warm-up). A stale or
        missing entry asks for a background refresh and returns what is cached, so an
        analysis is never held up by a 2-5 MB download. Chains are served up to
        ``OPTIONS_STALE_MAX`` old (the quote carries its own time, and out of session the
        feed is the last session's anyway); "no options" is remembered for hours and a
        failure for a few minutes.
        """
        if self.options_client is None:
            return None
        now = utc_now()
        hit = self._options.get(ticker)
        stale = hit is None or now - hit[0] > (OPTIONS_NONE_TTL if hit[1] == "none" else OPTIONS_TTL)
        failed = self._options_failed.get(ticker)
        if stale and not (failed and now - failed < OPTIONS_RETRY):
            if fetch:
                self._fetch_options(ticker)
                hit = self._options.get(ticker)
            else:
                self.refresh_options_later(ticker)
        if hit is None:
            return None
        if hit[1] != "none" and now - hit[0] > OPTIONS_STALE_MAX:
            return None
        return hit[1]

    def _fetch_options(self, ticker: str) -> None:
        from nightwatch.data.cboe import NoOptions

        now = utc_now()
        try:
            self._options[ticker] = (now, self.options_client.get_chain(ticker, fetched_at=now))
            self._options_failed.pop(ticker, None)
        except NoOptions:
            self._options[ticker] = (now, "none")
            self._options_failed.pop(ticker, None)
        except Exception as exc:  # noqa: BLE001 - context must never fail an analysis
            # An older good chain stays and is served with its own age; the retry is paced.
            log.warning("options for %s unavailable: %s", ticker, exc)
            self._options_failed[ticker] = now

    def refresh_options_later(self, ticker: str) -> None:
        """Fetch one ticker's chain in the background, once at a time."""
        if self.options_client is None or ticker in self._options_pending:
            return
        self._options_pending.add(ticker)

        def run() -> None:
            try:
                self._fetch_options(ticker)
            finally:
                self._options_pending.discard(ticker)

        threading.Thread(target=run, name=f"options-{ticker}", daemon=True).start()

    def street_for(self, ticker: str, *, max_age: timedelta = timedelta(hours=2), fetch: bool = True):  # noqa: ANN201
        """Street context for a ticker, from cache when fresh enough.

        ``fetch=True`` fetches on a miss and waits for it; the warm-up does that. An
        analysis passes ``fetch=False``: the analyst feed takes 1-9 s to answer, measured,
        and a request must not wait on a context feed, so a miss returns what is cached (or
        nothing) and asks for a background refresh instead.

        When a refresh fails, the last good view is kept and served (up to
        ``STREET_LAST_GOOD_MAX`` old). It carries its own ``fetched_at``, so the report can
        say how old it is; it is never passed off as current.
        """
        if self.street_client is None:
            return None
        hit = self._street.get(ticker)
        if hit and utc_now() - hit[0] <= max_age:
            return hit[1]
        last_good = hit[1] if hit and utc_now() - hit[0] <= STREET_LAST_GOOD_MAX else None
        if not fetch:
            self.refresh_street_later(ticker)
            return last_good
        return self._fetch_street(ticker) or last_good

    def street_status(self) -> dict | None:
        """The street feed's health, from the client, or None if it keeps none."""
        fn = getattr(self.street_client, "status", None)
        try:
            return fn() if callable(fn) else None
        except Exception:  # noqa: BLE001
            return None

    def _fetch_street(self, ticker: str):  # noqa: ANN202
        from nightwatch.features import street as street_mod

        try:
            view = street_mod.build(self.street_client, ticker)
        except Exception:  # noqa: BLE001 - context must never fail an analysis
            log.exception("street context for %s failed", ticker)
            return None
        if view.empty:
            # Nothing came back. If the service is down that is an outage, not "no
            # coverage": keep the last good view rather than overwrite it with a blank, and
            # cache nothing so the next ask retries. If it is up, the token genuinely has
            # no street data and the blank is cached like any other answer.
            status = self.street_status()
            if status is not None and status.get("ok") is not True:
                return None
        self._street[ticker] = (utc_now(), view)
        return view

    def refresh_street_later(self, ticker: str) -> None:
        """Fetch one token's street context in the background, once at a time."""
        if self.street_client is None or ticker in self._street_pending:
            return
        self._street_pending.add(ticker)

        def run() -> None:
            try:
                self._fetch_street(ticker)
            finally:
                self._street_pending.discard(ticker)

        threading.Thread(target=run, name=f"street-{ticker}", daemon=True).start()

    def refresh_bitget_later(self, ticker: str) -> None:
        """Ask for this ticker's catalogue entries in the background, if any is due.

        The refresher itself enforces one call per entry per hour, so a burst of analyses of
        one ticker starts at most one pass, and a cold cache after a restart fills itself."""
        bd = self.bitget_data
        if bd is None or ticker in self._bitget_pending or not any(bd.due(ticker, eid, utc_now()) for eid in bd.entries):
            return
        self._bitget_pending.add(ticker)

        def run() -> None:
            try:
                bd.refresh_ticker(ticker)
            except Exception:  # noqa: BLE001 - an optional feed
                log.exception("bitget data for %s failed", ticker)
            finally:
                self._bitget_pending.discard(ticker)

        threading.Thread(target=run, name=f"bitget-{ticker}", daemon=True).start()

    def signal_for(self, ticker: str, *, max_age: timedelta = timedelta(hours=1), fetch: bool = False) -> dict | None:
        """The checked bitget-signal reading for a ticker, from cache when fresh enough.

        Same contract as ``street_for``: an analysis passes ``fetch=False`` and never
        waits; a miss returns what is cached and asks for a background refresh."""
        if self.signal_client is None:
            return None
        hit = self._signal.get(ticker)
        if hit and utc_now() - hit[0] <= max_age:
            return hit[1]
        if not fetch:
            self.refresh_signal_later(ticker)
            return hit[1] if hit else None
        return self._fetch_signal(ticker) or (hit[1] if hit else None)

    def _fetch_signal(self, ticker: str) -> dict | None:
        from nightwatch.features import signal as signal_mod

        try:
            spec = self.spec(ticker)
            bars = self.store.get_bars(Venue.BITGET_SPOT, spec.spot_symbol, Interval.H1, start=utc_now() - timedelta(days=30), as_of=utc_now())
            view = signal_mod.build(self.signal_client, ticker, bars["close"] if len(bars) else None)
        except Exception:  # noqa: BLE001 - context must never fail an analysis
            log.exception("signal context for %s failed", ticker)
            return None
        self._signal[ticker] = (utc_now(), view)
        return view

    def refresh_signal_later(self, ticker: str) -> None:
        if self.signal_client is None or ticker in self._signal_pending:
            return
        self._signal_pending.add(ticker)

        def run() -> None:
            try:
                self._fetch_signal(ticker)
            finally:
                self._signal_pending.discard(ticker)

        threading.Thread(target=run, name=f"signal-{ticker}", daemon=True).start()

    def rwa_for(self, ticker: str, *, max_age: timedelta = timedelta(minutes=30), fetch: bool = False) -> dict | None:
        """The cached Bitget Wallet listing for a ticker. An analysis passes ``fetch=False``:
        a miss returns what is cached (up to a day old) and asks for a background refresh."""
        if self.rwa_client is None:
            return None
        hit = self._rwa.get(ticker)
        if hit and utc_now() - hit[0] <= max_age:
            return hit[1]
        if fetch:
            return self._fetch_rwa(ticker) or (hit[1] if hit else None)
        self.refresh_rwa_later(ticker)
        return hit[1] if hit and utc_now() - hit[0] <= timedelta(days=1) else None

    def _fetch_rwa(self, ticker: str) -> dict | None:
        try:
            info = self.rwa_client.stock_info(ticker)
        except Exception:  # noqa: BLE001 - context must never fail an analysis
            log.exception("bitget rwa for %s failed", ticker)
            return None
        if info is not None:
            self._rwa[ticker] = (utc_now(), info)
        return info

    def refresh_rwa_later(self, ticker: str) -> None:
        if self.rwa_client is None or ticker in self._rwa_pending:
            return
        self._rwa_pending.add(ticker)

        def run() -> None:
            try:
                self._fetch_rwa(ticker)
            finally:
                self._rwa_pending.discard(ticker)

        threading.Thread(target=run, name=f"rwa-{ticker}", daemon=True).start()

    def signal_health(self, *, max_age: timedelta = timedelta(hours=1)) -> dict | None:
        """{answering, tried, checked_at} from cache; a stale or missing value triggers a
        background probe and is returned as is, so the sources page never waits on it."""
        if self.signal_client is None:
            return None
        hit = self._signal_health
        if hit is None or utc_now() - hit[0] > max_age:
            if "_health" not in self._signal_pending:
                self._signal_pending.add("_health")

                def run() -> None:
                    try:
                        h = self.signal_client.health()
                        self._signal_health = (utc_now(), h)
                    except Exception:  # noqa: BLE001
                        log.exception("signal health probe failed")
                    finally:
                        self._signal_pending.discard("_health")

                threading.Thread(target=run, name="signal-health", daemon=True).start()
        return {**hit[1], "checked_at": hit[0].isoformat()} if hit else None

    def tail_factors(self, as_of: datetime, side: str = "long"):  # noqa: ANN201
        """Tail-calibration factors fitted on replay forecasts matured before ``as_of``
        (None when the journal is absent or has too few matured replays).

        ``side="short"`` fits the loss tail of the short replays alone: the same nights,
        replayed the other way, so a short's loss line is calibrated on shorts' outcomes."""
        if self.journal is None:
            return None
        key = side + ensure_utc(as_of).replace(minute=0, second=0, microsecond=0).isoformat()
        if key not in self._factors_cache:
            from nightwatch.journal.adjust import factors_as_of

            try:
                df = self.journal.forecasts(kind="replay", matured_only=True, short_replays=side == "short")
                df = df[df["side"] == side] if not df.empty else df
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

    def latest_spot_close(self, ticker: str, as_of: datetime | None = None) -> float | None:
        """The newest stored hourly close of the token at or before ``as_of``: one indexed read,
        for checks that need the price without running the whole analysis."""
        spot = self.entry(ticker).spot_symbol
        cutoff = int((ensure_utc(as_of) if as_of else utc_now()).timestamp() * 1000)
        row = self.store._conn.execute(
            "SELECT close FROM bars WHERE venue=? AND symbol=? AND interval=? AND kind=? AND ts<=? ORDER BY ts DESC LIMIT 1",
            (Venue.BITGET_SPOT.value, spot, Interval.H1.value, "trade", cutoff),
        ).fetchone()
        return float(row[0]) if row and row[0] else None

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

    def touch_frames(self) -> int:
        """Read every cached frame once, so the kernel keeps it in memory.

        On the 1 GB box the API needs more than the memory left over, and the kernel
        moves whatever was least recently used to swap. An hour of nobody asking is
        enough for that to be the frames, and the next narrowed search - which reads all
        twenty-four of them - then spent 18-25 s paging them back in; measured at 2 s
        once they were resident. Reading each column's values every few minutes keeps
        them the most recently used pages, so what goes to swap is memory nothing is
        using. Returns the number of frames touched.
        """
        touched = 0
        for frame in list(self._frames.values()):
            for col in frame.columns:
                values = frame[col].to_numpy() if frame[col].dtype.kind in "fiub" else None
                if values is not None and values.size:
                    values.sum()
            touched += 1
        return touched

    def _checked(self, ticker: str, end: datetime, frame: pd.DataFrame, rebuild: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        """A freshly built frame, checked for gaps the previous build did not have.

        On 2026-09-24 at 06:21 UTC the live desk answered a TSLA overnight hold from 2,462
        candidate hours where the same moment replayed later had 7,977: the cached frame
        was missing features for thousands of past hours, the search fell back on weekend
        hours, and the loss tail came out at -0.2% against a true -2.2%. The cause was not
        found. So each build is compared with the last one for the same token (a build for
        a nearby end, not an old replay), and a feature that is suddenly missing for far
        more of the history triggers one rebuild; if it persists, the token is marked so
        the report says its history was incomplete instead of answering quietly.
        """
        profile = _gap_profile(frame)
        prev = self._profiles.get(ticker)
        near = prev is not None and abs((ensure_utc(end) - prev[0]).total_seconds()) <= PROFILE_WINDOW_S
        worse = _worse_gaps(prev[1], profile) if near else {}
        if worse:
            log.warning("feature frame for %s came back with new gaps %s; rebuilding once", ticker, worse)
            frame = rebuild()
            profile = _gap_profile(frame)
            worse = _worse_gaps(prev[1], profile)
        if worse:
            log.error("feature frame for %s still has new gaps after a rebuild: %s", ticker, worse)
            self._degraded[ticker] = worse
            return frame  # keep the old profile as the reference for the next build
        self._degraded.pop(ticker, None)
        self._profiles[ticker] = (ensure_utc(end), profile)
        return frame

    def feature_frame(self, ticker: str, end: datetime) -> pd.DataFrame:
        """Full-history feature frame for a ticker, cached per process per end-hour.

        The cache is bounded (least-recently-used eviction) because an always-on API
        sees a new end-hour every hour and replays ask for arbitrary as-of hours; an
        unbounded map would grow by a full frame per ticker per hour for weeks."""
        key = f"{ticker}|{ensure_utc(end).replace(minute=0, second=0, microsecond=0).isoformat()}"
        prefix = f"{ticker}|"
        newest = max((k for k in self._frames if k.startswith(prefix)), default=None)
        older = newest is not None and key < newest  # ISO hours sort as time does
        store = self._older_frames if older else self._frames
        frame = store.pop(key, None)
        if frame is None:
            spec = self.spec(ticker)
            cov = self.store.bar_coverage(Venue.BITGET_SPOT, spec.spot_symbol, Interval.H1)
            if cov is None:
                raise InsufficientData(f"no stored bars for {spec.spot_symbol}")
            frame = _compact(compute_feature_frame(self.store, spec, cov[0], end))
            frame = self._checked(ticker, end, frame, lambda: _compact(compute_feature_frame(self.store, spec, cov[0], end)))
        store[key] = frame  # re-insert as most recent
        if not older:
            # A new end-hour used to leave the hour before it behind for every token until the
            # limit pushed it out: two or three full hour-sets (about 6.6 MB a frame, twenty-four
            # tokens) in memory on a box with 900 MB, which then swapped. Only the newest hour of
            # a token stays in the main cache.
            for stale in [k for k in self._frames if k.startswith(prefix) and k != key]:
                self._frames.pop(stale, None)
        while len(self._older_frames) > OLDER_FRAMES_KEPT:
            self._older_frames.pop(next(iter(self._older_frames)))
        while len(self._frames) > self.frame_cache_size:
            self._frames.pop(next(iter(self._frames)))
        while len(self._factors_cache) > 64:
            self._factors_cache.pop(next(iter(self._factors_cache)))
        return frame


# A search feature missing for this many more percentage points of a token's history
# than in the previous build is a broken build, not an hour of new data.
GAP_JUMP = 0.05
OLDER_FRAMES_KEPT = 4
PROFILE_WINDOW_S = 48 * 3600


def _gap_profile(frame: pd.DataFrame) -> dict[str, float]:
    from nightwatch.features.snapshot import SEARCH_COLUMNS

    return {c: float(frame[c].isna().mean()) for c in SEARCH_COLUMNS if c in frame.columns and len(frame)}


def _worse_gaps(before: dict[str, float], after: dict[str, float]) -> dict[str, tuple[float, float]]:
    return {c: (round(before[c], 3), round(after[c], 3)) for c in after if c in before and after[c] - before[c] > GAP_JUMP}


def _compact(frame: pd.DataFrame) -> pd.DataFrame:
    """The same frame with its label columns stored as categories.

    Six text columns - the time-of-week bucket and the regime labels - repeat a handful
    of values across fifteen thousand rows and were half of every frame's 11.7 MB. On the
    1 GB box the API keeps twenty-four of these, and that was enough to push them into
    swap and make the first narrowed search of an hour take 18-23 s. As categories the
    values, comparisons and filters are unchanged; only the storage is.
    """
    out = frame.copy()
    for col in out.columns:
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col].dtype):
            if out[col].nunique(dropna=True) <= 64:
                out[col] = out[col].astype("category")
    return out


# ------------------------------------------------------------------ report types


@dataclass
class HorizonReport:
    horizon: str
    hours: float
    cohort: CohortStats
    baseline: BaselineComparison | None
    p5_adjusted: float | None = None  # tail-calibrated (see journal.adjust)
    p95_adjusted: float | None = None
    adjustment: dict[str, Any] | None = None  # k_lo, k_hi, c_lo, n_fit, fitted_through
    # The same distribution as the position's profit and loss, in percent. The cohort is
    # the token's move; a short loses when it rises, so its one-in-twenty loss is the
    # token's 95th percentile turned over, not its 5th. Every consumer that sizes, gates
    # or states "the one-in-twenty loss" reads these, never p5 directly.
    loss_p5_pct: float | None = None
    pnl_median_pct: float | None = None
    pnl_win_rate: float | None = None


def _position_view(h: HorizonReport, side: str, short_factors: Any = None) -> None:  # noqa: ANN401
    """Fill the position's own view of a horizon from the token's.

    A short's loss line is the more cautious of two: the token's upper tail widened by the
    long-fitted factor, and the short's own loss tail widened by factors fitted on short
    replays of the same nights. Scored out of sample on 2,301 short replays
    (research/short_calibration.py) the combination breached 4.7% against 5%, 5.7% on the
    narrowest third instead of 7.8%, at the same pinball loss (t = -0.02)."""
    c = h.cohort
    if c.insufficient:
        return
    if side == "short":
        up = h.p95_adjusted if h.p95_adjusted is not None else c.p95
        h.loss_p5_pct = -up if up is not None else None
        own = short_factors.for_hours(h.hours) if short_factors is not None and not (h.adjustment or {}).get("uncalibrated") else None
        if own is not None and c.p95 is not None and c.median_pct is not None:
            p5_s, p50_s = -c.p95, -c.median_pct
            line = p50_s + own.k_lo * (p5_s - p50_s) - own.c_lo
            if h.loss_p5_pct is None or line < h.loss_p5_pct:
                h.loss_p5_pct = line
                h.adjustment = {**(h.adjustment or {}), "short_own_fit": {"k_lo": own.k_lo, "c_lo": own.c_lo, "n_fit": own.n_fit}}
        h.pnl_median_pct = -c.median_pct if c.median_pct is not None else None
        h.pnl_win_rate = (1.0 - c.win_rate) if c.win_rate is not None else None
    else:
        h.loss_p5_pct = h.p5_adjusted if h.p5_adjusted is not None else c.p5
        h.pnl_median_pct = c.median_pct
        h.pnl_win_rate = c.win_rate


@dataclass
class AnalogSection:
    result: AnalogResult
    scope: str  # "same_ticker" | "pooled"
    horizons: dict[str, HorizonReport]
    matches_outcomes: list[MatchOutcome]
    paths: Any = None  # nightwatch.analog.paths.ScenarioPaths, over the primary horizon
    # Which named conditions narrowed the search, what they cost in evidence, and
    # whether they could be honoured at all. nightwatch.analog.lens.LensResult.
    lens: Any = None
    # How a hold over a weekend was matched against past weekend holds, and how many of the
    # final matches were one. nightwatch.analog.lens.WeekendHold; None for a hold that
    # crosses no weekend.
    weekend_hold: Any = None


@dataclass
class FilingNote:
    """A filing that landed recently enough to still be unpriced, and what it said.

    Two halves, deliberately kept apart. ``headline`` and ``category`` are the model's
    words about text that was public when the filing landed. ``p5_pct`` and the rest are
    not the model's: they are what this desk's own bars did after every other filing the
    model gave the same label to, which is why the label is allowed on the page at all.

    No direction is carried. The model offers one and it was measured at 49.5% against a
    coin, so it does not travel.
    """

    ticker: str
    accepted_at: datetime
    form: str
    items: str | None
    hours_ago: float
    inside_window: bool
    market_was_shut: bool
    category: str
    headline: str
    market_moving: str
    # From history, not from the model. None when that label has too few scored filings.
    label_n: int | None = None
    label_p5_pct: float | None = None
    label_median_pct: float | None = None
    label_mean_abs_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "accepted_at": self.accepted_at.isoformat()}


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
    book_note: str | None = None  # the book now is a momentary blowout; the size used the typical one


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
    filings: list[FilingNote] = field(default_factory=list)
    # nightwatch.features.street.StreetView as a dict: analysts, insiders, market mood and
    # an independent quote, from Bitget's data. Context only; None for past moments.
    street: dict | None = None
    # nightwatch.features.bitget_data.report_block: Bitget's earnings calendar (cross-checked
    # against Nasdaq's), valuation, dividends and consensus. Context only; None for past moments.
    bitget: dict | None = None
    # nightwatch.features.signal.build: Bitget's signal-skill RSI beside our own from
    # Bitget candles. Context only: not read by the gate or the size.
    signal: dict | None = None
    # The trader's invalidation read for a testable level and measured against the
    # analogs; plus a flag when the stated reason reads against the position.
    plan_check: dict | None = None
    # How to get into the recommended size on the live book: cost, slices, limit price.
    entry_plan: dict | None = None
    # A leveraged ticket's liquidation price and how often history reached it.
    leverage: dict | None = None
    # What the verdict assumes, how this trade loses money (trigger → mechanism → cost →
    # how often), and where the stated reason depends on an event the data can date.
    # All written by rules from the report's own fields (nightwatch.decision.story).
    assumptions: list[dict] = field(default_factory=list)
    failure_modes: list[dict] = field(default_factory=list)
    premise: list[str] = field(default_factory=list)
    # "Over the weekend" asked early in the week: holding from now is a trade longer than
    # any scored one, so what past Friday-close-to-Monday weekends did is shown beside it.
    weekend_only: dict | None = None
    # US regular sessions around the hold, for the market-clock strip (nightwatch.decision.timeline).
    timeline: dict | None = None
    # The journal receipt for this verdict: chained to every one before it (see journal.receipts).
    receipt: str | None = None
    # Ex-dividend dates, splits and Bitget notices around the hold, from the stored calendar
    # (nightwatch.features.corporate.build). Point in time; never fetched during an analysis.
    corporate_events: dict | None = None
    # Open interest on the token's perp now and its change over 24 h, with the one plain line
    # the leverage section shows (nightwatch.features.open_interest). Context only; None for
    # past moments, tokens without a perp, or when Bitget did not answer.
    open_interest: dict | None = None
    # The options market's implied one-sigma move over the hold, from Cboe's delayed quotes,
    # beside the desk's own one-in-twenty loss (nightwatch.features.options). Context only;
    # None for past moments, names with no listed options, or while the cache is cold.
    options: dict | None = None
    # For every source used: what it supplied and whether it changed the answer
    # (nightwatch.pipeline.effects), built from the decisions above, not from narrative.
    source_effects: list[dict] = field(default_factory=list)
    # Bitget Wallet's listing of the token (nightwatch.features.rwa_status): tradable status,
    # pause or alert text, per-order limits. A caution only; it never moves the size.
    rwa_listing: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        out = _serialise(self)
        _add_zh_names(out)
        _add_provenance(out)
        return out


def _add_provenance(out: dict[str, Any]) -> None:
    """Where each headline number came from (live Bitget, history, assumed, AI)."""
    try:
        from nightwatch.pipeline.provenance import build

        out["provenance"] = build(out)
    except Exception:  # noqa: BLE001 - a label must never break a report
        log.exception("provenance failed")


def _add_zh_names(out: dict[str, Any]) -> None:
    """Chinese names for failure modes and stress presets, from the maps the chat uses,
    so the report page shows the same words the briefing does."""
    try:
        from nightwatch.api.intake import FAILURE_ZH, preset_zh
        from nightwatch.decision.zh import assumption_zh, note_zh

        for m in out.get("failure_modes") or []:
            if isinstance(m, dict) and m.get("key") in FAILURE_ZH:
                m["title_zh"] = FAILURE_ZH[m["key"]]
        for p in ((out.get("stress") or {}).get("presets")) or []:
            if isinstance(p, dict) and p.get("id") and p.get("name"):
                p["name_zh"] = preset_zh(p["id"], p["name"])
                # The "how often" line under each preset in the stress table; absent when it is not a known shape.
                if p.get("probability_note") and (zh := note_zh(p["probability_note"])):
                    p["probability_note_zh"] = zh
        for a in out.get("assumptions") or []:
            if isinstance(a, dict) and a.get("text") and (zh := assumption_zh(a["text"])):
                a["text_zh"] = zh
    except Exception:  # noqa: BLE001 - a translation must never break a report
        log.exception("zh names failed")


# --------------------------------------------------------------------- analyse


_PROGRESS: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar("nightwatch_progress", default=None)


# Whose record the circuit breaker reads: the anonymous visitor the request came from. Unset (a
# call from the CLI, a background job) it reads the trades no visitor owns, so one person's
# clicks never move another person's verdict.
_TRADER: contextvars.ContextVar[str | None] = contextvars.ContextVar("nightwatch_trader", default=None)


@contextlib.contextmanager
def trader_scope(client: str | None):
    token = _TRADER.set(client)
    try:
        yield
    finally:
        _TRADER.reset(token)


@contextlib.contextmanager
def progress_to(callback: Callable[[dict[str, Any]], None] | None):
    """Route the progress events of every analyze() call made inside the block to ``callback``.

    A context variable rather than a parameter threaded through the chat's many call
    sites: the chat routing stays one code path, and a call made with no listener behaves
    exactly as before.
    """
    token = _PROGRESS.set(callback)
    try:
        yield
    finally:
        _PROGRESS.reset(token)


def _money(x: float) -> str:
    return f"{x:,.0f}"


def _announce(cb: Callable[[dict[str, Any]], None] | None, stage: str, en: str, zh: str, t_start: float) -> None:
    """One finished stage, in plain words, with a number taken from that stage's own result.
    A listener that fails must never fail an analysis."""
    if cb is None:
        return
    try:
        cb({"stage": stage, "en": en, "zh": zh, "ms": int((time.perf_counter() - t_start) * 1000)})
    except Exception:  # noqa: BLE001
        log.exception("progress listener failed")


def analyze(ctx: AnalysisContext, ticket: TradeTicket, *, as_of: datetime | None = None, record: bool = True,
            progress: Callable[[dict[str, Any]], None] | None = None) -> AnalysisReport:
    """Run the whole analysis. ``progress``, if given (or set with ``progress_to``), is called
    as each major stage finishes with ``{stage, en, zh, ms}``; it changes nothing else."""
    t_start = time.perf_counter()
    cb = progress or _PROGRESS.get()
    timings: dict[str, int] = {}
    warnings: list[str] = []
    sources: list[dict[str, Any]] = []
    as_of = ensure_utc(as_of or utc_now())
    spec = ctx.spec(ticket.ticker)
    entry_info = ctx.entry(ticket.ticker)
    horizon_h = ticket.horizon_h(as_of)
    primary = f"{max(1, round_half_up(horizon_h))}h"

    # 1. Snapshot (now).
    t0 = time.perf_counter()
    snapshot = ctx.snapshot_at(spec, as_of)
    timings["snapshot"] = _ms(t0)
    _announce(cb, "snapshot", f"Read {ticket.ticker} and the market as it stands now", f"已读取 {ticket.ticker} 和当前市场状况", t_start)
    entry_price = ticket.entry_price or snapshot.prices["spot_close"] or 0.0
    # A stop given as a distance becomes a price here, the first moment one is known, so
    # everything after - the gate, the paths, the brief - sees an ordinary stop.
    ticket = ticket.with_stop_resolved(entry_price)
    fees = _fees(ctx, spec)
    # A leveraged ticket's liquidation price, known before history is searched so the
    # analog paths can be judged against it the same way they are against the stop.
    lev_view = None
    if ticket.leveraged:
        from nightwatch.execution import leverage as lev_mod

        lev_view = lev_mod.assess(
            leverage=float(ticket.leverage or 1.0), notional=ticket.notional_quote, entry=entry_price, long=ticket.closing_long,
            perp_symbol=spec.perp_symbol, tiers=ctx.margin_tiers(spec.perp_symbol), taker_fee=fees["perp_taker"],
        )
    sources.append({"kind": "features", "label": "Computed features", "ticker": ticket.ticker, "bar_ts": snapshot.bar_ts.isoformat(), "hash": snapshot.content_hash, "history_hours": snapshot.history_hours})

    # 2. Analog search + outcomes.
    t0 = time.perf_counter()
    frame = ctx.feature_frame(ticket.ticker, as_of)
    gaps = ctx._degraded.get(ticket.ticker)
    if gaps:
        warnings.append(
            f"part of {ticket.ticker}'s stored history was incomplete when this ran ({', '.join(sorted(gaps))} missing for more "
            f"of it than usual), so the comparison is drawn from a narrower history than normal; treat the distribution with caution"
        )
    # On nights where the unfiltered answer has been measured to be wrong, the desk
    # narrows the search itself, unless the trader named conditions or turned it off.
    # The report says it did, and why, next to the verdict.
    auto_reason = ""
    if not ticket.lenses and ticket.auto_lens:
        from nightwatch.analog import lens as lens_mod

        hits = lens_mod.automatic_for(snapshot.features)
        if hits:
            ticket = replace(ticket, lenses=tuple(x.name for x in hits))
            auto_reason = (
                f"narrowed automatically because {lens_mod.describe(hits)} holds tonight: on past nights like this "
                f"the unfiltered 5% loss line was broken far more often than 5%, and the narrowed one close to it"
            )
    analog = _analog_section(ctx, ticket, snapshot, frame, as_of, horizon_h, primary, warnings, entry_price=entry_price,
                             liquidation_price=lev_view.liquidation_price if lev_view else None)
    if auto_reason and analog is not None and analog.lens is not None:
        # The evidence that narrowing gives a truer tail is suggestive, not established
        # (q = 0.095 once corrected for the other studies), so a narrowing the desk chose
        # itself may make the answer more cautious and never less: each horizon is sized
        # on the worse of the narrowed and the unfiltered one-in-twenty loss.
        plain = _analog_section(ctx, replace(ticket, lenses=()), snapshot, frame, as_of, horizon_h, primary, [],
                                entry_price=entry_price, liquidation_price=lev_view.liquidation_price if lev_view else None)
        floored = _cautious_of(analog, plain)
        if floored:
            auto_reason += f"; the unfiltered answer was more cautious for {', '.join(floored)}, so that is what the size uses"
        analog.lens = replace(analog.lens, auto=auto_reason)
    timings["analog"] = _ms(t0)
    if analog is not None and analog.result.n:
        n = analog.result.n
        _announce(cb, "analog", f"Found {n} past moments like now", f"找到 {n} 个与现在相似的历史时刻", t_start)
    else:
        _announce(cb, "analog", "Searched history for moments like now: too few to rely on", "已搜索历史相似时刻：数量太少，不足以依赖", t_start)

    from nightwatch.decision import plan_check as plan_mod

    plan = plan_mod.check(
        ticket.invalidation, ticket.thesis, long=ticket.closing_long, price=entry_price or None,
        frame=frame, paths=getattr(analog, "paths", None) if analog else None,
    )

    # 3. Order book (recorded, refreshed live if stale and a client exists).
    t0 = time.perf_counter()
    book, book_source = _get_book(ctx, spec.spot_symbol, as_of)
    if book is not None:
        sources.append({"kind": "orderbook", "label": "Bitget order book", "last_ts": book.ts.isoformat(), "rows_used": len(book.bids) + len(book.asks), "symbol": spec.spot_symbol, "ts": book.ts.isoformat(), "source": book_source, "levels": len(book.bids) + len(book.asks)})
    else:
        warnings.append("no order book available: exit cost and liquidity caps are unknown")
    timings["book"] = _ms(t0)
    if book is not None:
        lv = len(book.bids) + len(book.asks)
        _announce(cb, "book", f"Read the Bitget order book ({lv} price levels)", f"已读取 Bitget 盘口（{lv} 档）", t_start)
    else:
        _announce(cb, "book", "No order book available for this token", "该代币暂无盘口数据", t_start)

    # What the options market implies for this hold, beside the desk's own 1-in-20 loss.
    # From cache only: a cold cache means no line this time and a background fetch. Read
    # before the stress step because a bigger implied move than history's is a stress preset.
    options = None
    if abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S:
        options = _options_block(ctx, ticket.ticker, as_of, horizon_h, analog, primary)

    # 4. Stress.
    t0 = time.perf_counter()
    stress = _stress_section(ctx, ticket, spec, snapshot, frame, book, fees["spot_taker"], horizon_h, entry_price, warnings, as_of=_hold_start(ticket, as_of), analog_p5=_primary_p5(analog, primary),
                             options_move_pct=options["implied_move_pct"] if options else None)
    if options:
        from nightwatch.features import options as options_mod

        options_mod.attach_sizing(options, next((p for p in stress.presets if p.id == "options_implied_move"), None))
    timings["stress"] = _ms(t0)
    totals = [i.total_pnl_quote for i in stress.impacts if i.total_pnl_quote is not None]
    if totals:
        w = min(totals)
        worst = f"{'-' if w < 0 else ''}{_money(abs(w))} USDT"
        _announce(cb, "stress", f"Ran {len(stress.presets)} stress presets: worst {worst}", f"已运行 {len(stress.presets)} 个压力情景：最坏 {worst}", t_start)
    else:
        _announce(cb, "stress", f"Ran {len(stress.presets)} stress presets", f"已运行 {len(stress.presets)} 个压力情景", t_start)

    # 5. Execution.
    t0 = time.perf_counter()
    execution = _execution_section(ctx, ticket, spec, frame, book, book_source, fees, horizon_h, entry_info, as_of)
    if execution.book_note:
        warnings.append(execution.book_note)
    timings["execution"] = _ms(t0)
    if execution.exit_quote is not None and execution.exit_quote.total_cost_bps is not None:
        c = execution.exit_quote.total_cost_bps
        _announce(cb, "execution", f"Walked the live Bitget order book: exit costs {c:.0f} bps", f"按 Bitget 实时盘口平仓：成本 {c:.0f} 个基点", t_start)
    else:
        _announce(cb, "execution", "Priced the exit: the book cannot absorb this size", "已计算平仓：盘口无法承接该仓位", t_start)

    # 6. Gate, sizing, verdict.
    t0 = time.perf_counter()
    p5 = _primary_p5(analog, primary)
    if plan is not None:
        plan.judge_reach(p5)
    leverage_rule = None
    if lev_view is not None:
        from nightwatch.execution import leverage as lev_mod

        paths = analog.paths if analog else None
        moves = {
            s.name: imp.mtm_pnl_quote / ticket.notional_quote * 100.0
            for s, imp in zip(stress.presets, stress.impacts, strict=True) if imp.mtm_pnl_quote is not None
        }
        lev_mod.attach_history(
            lev_view, analog_hits=paths.liquidated if paths and paths.liquidation_pct is not None else None,
            analog_of=len(paths.paths) if paths and paths.liquidation_pct is not None else None, preset_moves=moves,
            mc_worst_pct=stress.monte_carlo.worst_drawdown_pct if stress.monte_carlo is not None else None,
        )
        leverage_rule = lev_mod.gate_rule(lev_view, p5)
        # The same position at other leverage levels, judged on the same drawn paths, so
        # "5x is too much" arrives with what would be fine and what it costs in margin.
        rungs, safest, extra = lev_mod.safety_ladder(
            requested=float(ticket.leverage or 1.0), notional=ticket.notional_quote, entry=entry_price,
            long=ticket.closing_long, perp_symbol=spec.perp_symbol, tiers=ctx.margin_tiers(spec.perp_symbol),
            taker_fee=fees["perp_taker"], preset_moves=moves, p5_loss_pct=p5,
            worst_adverse=[p.worst_adverse_pct for p in paths.paths] if paths else None,
        )
        lev_mod.attach_ladder(lev_view, rungs, safest, extra)
    residual_p5 = None
    if execution.hedge_quote and execution.hedge_quote.residual_basis_p95_bps is not None:
        residual_p5 = -execution.hedge_quote.residual_basis_p95_bps / 100.0
    # The trader's own recent record, which has nothing to do with this trade's merits.
    breaker = BreakerReport(state=BreakerState.NORMAL, reasons=["no journal"], equity=ticket.account_equity_quote)
    if ctx.journal is not None:
        try:
            breaker = evaluate_breaker(ctx.journal.taken_trades(matured_only=False, client=_TRADER.get()), equity=ticket.account_equity_quote, now=as_of, policy=ctx.breaker_policy)
        except Exception:  # noqa: BLE001
            log.exception("circuit breaker evaluation failed")

    # The rest of the book, if the trader told us about it. Measured before the decision
    # because it changes it: it caps the size and colours the gate, and the same context
    # then drives every what-if, so a swept verdict is the headline verdict's sibling.
    t0 = time.perf_counter()
    portfolio = None
    book_built = None
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
            book_built = build_book_model(held, ticket.ticker, frames, horizon_h=max(1, round_half_up(horizon_h)))
            portfolio = evaluate_portfolio(
                held, BookPosition(ticket.ticker, ticket.side.value, ticket.notional_quote), frames,
                equity=ticket.account_equity_quote, horizon_h=horizon_h, built=book_built,
            )
        except Exception:  # noqa: BLE001 - the book view must never break the verdict
            log.exception("portfolio evaluation failed")
            portfolio = book_built = None
            warnings.append("Your holdings could not be measured this time, so this verdict does not include them. Run it again, or treat it as the trade on its own.")
    # Holdings were given but no tail could be measured from them (the book failed above, or no
    # window is shared by enough history): say they are unmeasured rather than let the gate
    # report that "the book's history is measured".
    book_unknown: tuple[str, ...] = book_built[2] if book_built else ()
    if ticket.open_positions and not (book_built and book_built[0] is not None):
        book_unknown = book_unknown or tuple(dict.fromkeys(t.upper() for t, _, _ in ticket.open_positions))
    timings["portfolio"] = _ms(t0)

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
        leverage_rule=leverage_rule,
        book_model=book_built[0] if book_built else None, book_unknown=book_unknown,
        book_mean_correlation=portfolio.mean_correlation_to_book if portfolio else None,
        invalidation_distance_pct=plan.measured_pct() if plan else None,
        invalidation_reach_pct=plan.reach_pct if plan else None,
    )
    ev = dc.evaluate(
        ticket, impacts=stress.impacts,
        exit_cost_bps=execution.exit_quote.total_cost_bps if execution.exit_quote else None,
        exit_fully_filled=execution.exit_quote.fully_filled if execution.exit_quote else False,
        has_book=execution.exit_quote is not None,
    )
    gate, sizing, verdict = ev.gate, ev.sizing, ev.verdict

    # How to get into the size the desk arrived at, on the book as it stands. Priced for
    # the recommended size, not the requested one: that difference is the verdict.
    from nightwatch.execution.entry_plan import plan_entry

    entry_size = verdict.recommended_notional if verdict.recommended_notional else ticket.notional_quote
    entry_plan = plan_entry(book, entry_size, long=ticket.closing_long, taker_fee=fees["spot_taker"], budget_bps=ctx.sizing_policy.exit_cost_budget_bps)
    timings["decision"] = _ms(t0)
    v = getattr(verdict.verdict, "value", verdict.verdict)
    zh_v = {"GO": "可以做", "REDUCE_TO": "建议减仓", "HEDGE": "建议对冲", "REVIEW": "需要复核", "NO_GO": "不建议做"}.get(str(v), str(v))
    _announce(cb, "decision", f"Checked the risk rules and sized the trade: {str(v).replace('_', ' ')}", f"已核对风控规则并确定仓位：{zh_v}", t_start)

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
        regimes = ctx.regimes_at(frame, snapshot.bar_ts, max(1, round_half_up(horizon_h)))
    except Exception:  # noqa: BLE001 - a map is not worth breaking a verdict for
        log.exception("regime map failed")
    timings["regimes"] = _ms(t0)

    # 9. The rest of the book was measured before the decision (see above), so the size
    # is sized against it; what is left is to say what the recommended size does to it.
    if portfolio is not None and book_built is not None and book_built[0] is not None and book_built[0].unit is not None:
        rec = verdict.recommended_notional
        model = book_built[0]
        cap = next((c for c in sizing.caps if c.name == "book_tail"), None)
        portfolio = replace(
            portfolio,
            tail_after_recommended_quote=model.tail(rec, ticket.side.value) if rec is not None else None,
            book_cap_quote=cap.notional if cap else None,
            book_cap_pct_of_equity=ctx.sizing_policy.max_book_tail_pct_of_equity if cap else None,
            book_cap_binds=bool(cap and sizing.binding_cap == "book_tail"),
        )
        portfolio = replace(portfolio, stress=_book_stress(ctx, ticket, book_built[0], held, fees, horizon_h, lev_view))

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

    # What the model made of any filing recent enough to still be unpriced. Reads only;
    # nothing here has touched the verdict above, and the study that earned it a place
    # on the page also says its directional call is a coin, so no direction travels.
    t0 = time.perf_counter()
    filings = _filing_notes(ctx, ticket, as_of, horizon_h)
    timings["filings"] = _ms(t0)

    # Street context. Current data describes today, so it is attached only to an
    # analysis of today; a replay of a past night showing today's targets would be
    # lookahead dressed as context.
    t0 = time.perf_counter()
    street = None
    if abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S:
        from nightwatch.features import street as street_mod

        view = ctx.street_for(ticket.ticker, fetch=False)
        mcp = ctx.street_status()
        down = mcp is not None and mcp.get("ok") is False
        if (view is None or view.empty) and down:
            # An outage, not "no coverage": say so on the report, in its warnings and in the
            # sources line, so the missing section is not mistaken for a quiet stock.
            note = f"unavailable{street_mod.outage_clause(mcp)}"
            warnings.append(f"Bitget's US-stock data (analysts, insiders, live quote) is {note}; this report has no street section")
            sources.append({"kind": "bitget_mcp", "label": "Bitget US-stock MCP", "last_ts": None, "rows_used": 0, "ticker": ticket.ticker, "status": "unavailable", "note": note})
        if view is not None and not view.empty:
            street = view.to_dict()
            age_s = street_mod.age_seconds(view, utc_now())
            # Served from the cache after the feed stopped answering, or simply old: say so,
            # and do not let a price that old stand in for the live one.
            stale = down or (age_s is not None and age_s > STREET_LIVE_S)
            street["age_s"] = age_s
            street["stale"] = stale
            street["age_label"] = street_mod.last_good_label(age_s) if stale else None
            sources.append({"kind": "bitget_mcp", "label": "Bitget US-stock MCP", "last_ts": view.fetched_at, "rows_used": 1, "ticker": ticket.ticker, "fetched_at": view.fetched_at,
                            **({"status": "last_good", "note": street["age_label"]} if stale else {})})
            if stale:
                warnings.append(
                    f"Bitget's US-stock data (analysts, insiders, live quote) is {street['age_label']}{street_mod.outage_clause(mcp)}; "
                    f"it is context, not live, and is left out of the live-price checks"
                )
            native = snapshot.prices.get("native_close")
            gap = None if stale else street_mod.quote_disagreement_bps(view, native, snapshot.features.get("native_close_age_h"))
            street["quote_gap_bps"] = gap
            street["token_vs_live_bps"] = None if stale else street_mod.token_vs_live_bps(view, snapshot.prices.get("spot_close"))
            street["token_vs_close_bps"] = ((snapshot.prices["spot_close"] / native - 1.0) * 10_000.0) if native and snapshot.prices.get("spot_close") else None
            if gap is not None and abs(gap) > street_mod.QUOTE_DISAGREE_BPS:
                warnings.append(
                    f"the native close fair value is built on ({native:.2f}) is {gap:+.0f} bps from Bitget's figure for the same close; "
                    f"one of them is wrong, so read the basis with care"
                )
    timings["street"] = _ms(t0)

    # The rest of Bitget's catalogue, from cache only (see AnalysisContext.refresh_bitget_later).
    t0 = time.perf_counter()
    bitget = None
    if ctx.bitget_data is not None and abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S:
        try:
            from nightwatch.features import bitget_data as bd_mod

            ctx.refresh_bitget_later(ticket.ticker)
            nasdaq = [e.report_date.date() for e in ctx.store.get_earnings(ticket.ticker)]
            bitget = bd_mod.report_block(ctx.bitget_data, ticket.ticker, nasdaq, now=utc_now())
            if bitget:
                for eid, d in bitget["entries"].items():
                    sources.append({"kind": f"bitget_{eid}", "label": f"Bitget: {ctx.bitget_data.entries[eid].label}", "last_ts": d.get("fetched_at"), "rows_used": 1, "ticker": ticket.ticker, "fetched_at": d.get("fetched_at")})
                chk = bitget.get("earnings_check")
                if chk and chk["status"] == "differ":
                    warnings.append(
                        f"Bitget's calendar puts the next {ticket.ticker} earnings on {chk['bitget']} and Nasdaq's on {chk['nasdaq']} ({abs(chk['gap_days'])} day{'' if abs(chk['gap_days']) == 1 else 's'} apart); "
                        f"one of them is an estimate, so check the date before a hold that spans either"
                    )
        except Exception:  # noqa: BLE001 - optional context must never break a verdict
            log.exception("bitget catalogue for %s failed", ticket.ticker)
    timings["bitget_data"] = _ms(t0)

    t0 = time.perf_counter()
    corporate = None
    try:
        from nightwatch.features import corporate as corporate_mod

        corporate = corporate_mod.build(ctx.store, ticket.ticker, as_of=as_of, horizon_h=horizon_h,
                                        price=snapshot.prices.get("native_close") or snapshot.prices.get("spot_close"))
    except Exception:  # noqa: BLE001 - an optional calendar must never break a verdict
        log.exception("corporate events for %s failed", ticket.ticker)
    timings["corporate_events"] = _ms(t0)

    signal = None
    if abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S:
        sig = ctx.signal_for(ticket.ticker)
        if sig is not None and sig.get("agrees"):
            signal = sig
            sources.append({"kind": "bitget_signal", "label": "Bitget signal skill (technical analysis)", "last_ts": sig["fetched_at"], "rows_used": 1, "ticker": ticket.ticker, "fetched_at": sig["fetched_at"]})
    # Open interest on the perp: live, so only for an analysis of now. Context for a
    # leveraged trade; it never reaches the verdict.
    open_interest = None
    if abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S and spec.perp_symbol:
        open_interest = ctx.open_interest_for(spec.perp_symbol, price=snapshot.prices.get("perp_close"))
        if open_interest:
            sources.append({"kind": "bitget_open_interest", "label": "Bitget perp open interest", "last_ts": open_interest["observed_at"], "rows_used": 1, "symbol": spec.perp_symbol})
    if options:
        sources.append({"kind": "cboe_options", "label": "Cboe options quotes", "last_ts": options["quote_ts"] or options["fetched_at"], "rows_used": options["n_strikes"], "ticker": ticket.ticker,
                        "fetched_at": options["fetched_at"]})
    rwa_listing = None
    if abs((utc_now() - as_of).total_seconds()) <= STREET_FRESH_S:
        try:
            from nightwatch.features import rwa_status

            rwa_listing = rwa_status.build(ctx.rwa_for(ticket.ticker), ticket.notional_quote, ticket.side.value == "long")
        except Exception:  # noqa: BLE001 - optional context must never break a verdict
            log.exception("bitget rwa listing for %s failed", ticket.ticker)
        if rwa_listing:
            sources.append({"kind": "bitget_wallet_rwa", "label": "Bitget Wallet RWA listing", "last_ts": rwa_listing["fetched_at"], "rows_used": 1, "ticker": ticket.ticker, "fetched_at": rwa_listing["fetched_at"]})
            for f in rwa_listing["flags"]:
                warnings.append(f"{f[0].upper()}{f[1:]}; this did not change the size")
    timings["total"] = int((time.perf_counter() - t_start) * 1000)
    from nightwatch.pipeline.feeds import feed_sources

    tiers = ctx.margin_tiers(spec.perp_symbol) if lev_view is not None else None
    sources.extend(feed_sources(ctx.store, ticker=ticket.ticker, spot_symbol=spec.spot_symbol, perp_symbol=spec.perp_symbol,
                                yahoo_ticker=spec.yahoo_ticker, as_of=as_of, margin_tier_rows=len(tiers) if tiers else None))

    report = AnalysisReport(
        ticket=ticket, as_of=as_of, horizon_h=horizon_h, primary_horizon=primary, snapshot=snapshot, analog=analog,
        stress=stress, execution=execution, gate=gate, sizing=sizing, verdict=verdict, sensitivity=sensitivity, lessons=lessons, breaker=breaker, portfolio=portfolio, regimes=regimes, sources=sources, warnings=warnings, timings_ms=timings, filings=filings, street=street, bitget=bitget, signal=signal, corporate_events=corporate, open_interest=open_interest, options=options, rwa_listing=rwa_listing,
        plan_check=plan.to_dict() if plan else None,
        entry_plan=entry_plan.to_dict() if entry_plan else None,
        leverage=lev_view.to_dict() if lev_view else None,
    )
    if report.leverage is not None and open_interest:
        report.leverage["open_interest_line"] = open_interest["line"]
        report.leverage["open_interest_crowded_line"] = open_interest.get("crowded_line")
    if open_interest and open_interest.get("crowded"):
        report.warnings.append(f"The {open_interest['symbol']} perp looks crowded: {open_interest['crowded_line']}. A liquidation cascade has more to feed on; this did not change the size")
    try:
        from nightwatch.pipeline.effects import build as build_effects

        report.source_effects = build_effects(report)
    except Exception:  # noqa: BLE001 - an explanation of the sources must never break a verdict
        log.exception("source effects failed")
    # The case against whatever was just decided, from the report's own numbers.
    try:
        from nightwatch.decision.devil import build as build_second_opinion

        report.second_opinion = build_second_opinion(report)
    except Exception:  # noqa: BLE001
        log.exception("second opinion failed")
    try:
        from nightwatch.decision import story

        report.assumptions = [x.__dict__ for x in story.assumptions(report)]
        report.failure_modes = [x.to_dict() for x in story.failure_modes(report)]
        report.premise = story.premise(report)
    except Exception:  # noqa: BLE001 - an explanation must never break a verdict
        log.exception("assumptions / failure modes failed")

    report.weekend_only = _weekend_only(ticket, horizon_h, frame, as_of)
    try:
        from nightwatch.decision.timeline import build as build_timeline

        report.timeline = build_timeline(as_of, horizon_h, hold_start=_hold_start(ticket, as_of))
    except Exception:  # noqa: BLE001 - a clock strip must never break a verdict
        log.exception("timeline failed")

    if ctx.journal is not None and record:
        try:
            report.forecast_id = _record(ctx, report)
            from nightwatch.journal import receipts

            got = receipts.receipt(ctx.journal.store._conn, report.forecast_id)
            report.receipt = got["digest"] if got else None
        except Exception:  # noqa: BLE001 - journaling must never break an analysis
            log.exception("failed to journal the forecast")
    return report


def _options_block(ctx: AnalysisContext, ticker: str, as_of: datetime, horizon_h: float, analog: Any, primary: str) -> dict | None:  # noqa: ANN401
    """The implied-move block, or None for any reason at all: it is context and must never
    cost an analysis anything."""
    try:
        chain = ctx.options_chain_for(ticker)
        if chain is None or chain == "none":
            return None
        from nightwatch.features import options as options_mod

        block = options_mod.implied_move(chain, as_of, horizon_h)
        if block is None:
            return None
        horizon = analog.horizons.get(primary) if analog else None
        return options_mod.attach_history(block, horizon.loss_p5_pct if horizon is not None else None)
    except Exception:  # noqa: BLE001
        log.exception("options implied move for %s failed", ticker)
        return None


def _hold_start(ticket: TradeTicket, as_of: datetime) -> datetime:
    """When the hold begins. Now, except for a scheduled weekend ("over the weekend" asked
    early in the week), which begins at Friday's close: the closed time it crosses is that
    one weekend, not the nights between now and then."""
    label = (ticket.extra or {}).get("horizon_label") if isinstance(ticket.extra, dict) else None
    if isinstance(label, str) and label.startswith("the coming weekend"):
        from nightwatch.analog.outcomes import coming_weekend_hours

        try:
            return max(ensure_utc(as_of), coming_weekend_hours(as_of)[1])
        except Exception:  # noqa: BLE001 - fall back to holding from now
            log.exception("weekend hold start failed")
    return ensure_utc(as_of)


def _weekend_only(ticket: TradeTicket, horizon_h: float, frame: pd.DataFrame, as_of: datetime) -> dict | None:
    """Past weekends, when "through the weekend" was asked far enough ahead of it that
    holding from now runs past the longest scored hold."""
    label = (ticket.extra or {}).get("horizon_label") if isinstance(ticket.extra, dict) else None
    scheduled = bool(label) and label.startswith("the coming weekend")
    if not label or "weekend" not in label or (horizon_h <= CALIBRATED_MAX_H and not scheduled):
        return None
    from nightwatch.analog.outcomes import weekend_history
    from nightwatch.time_utils import ET

    try:
        hist = weekend_history(frame, ticket.side.value)
    except Exception:  # noqa: BLE001 - context must never fail an analysis
        log.exception("weekend history failed")
        return None
    if hist is None:
        return None
    out = {**hist, "today": ensure_utc(as_of).astimezone(ET).strftime("%A"), "hold_from_now_h": horizon_h}
    if scheduled:
        from nightwatch.analog.outcomes import hours_through_weekend

        out.update(scheduled=True, scheduled_h=horizon_h, hold_from_now_h=hours_through_weekend(as_of))
    return out


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
            "p5_adjusted": (h.p5_adjusted if h else None), "p95_adjusted": (h.p95_adjusted if h else None), "loss_p5_pct": (h.loss_p5_pct if h else None), "adjustment": (h.adjustment if h else None),
        },
    )


# ------------------------------------------------------------------- sections


# How far back a filing can be and still be worth putting on the report. Beyond a couple
# of sessions the market has had a chance to price it and it is history, not news.
# Same 72 h the filings_72h feature counts, so the page lists what the feature counted.
FILING_LOOKBACK_H = 72.0
# How close to now an analysis must be for today's street data to belong on it.
STREET_FRESH_S = 6 * 3600
# A cached street view older than this is served only as "last good", labelled with its age.
STREET_LIVE_S = 2 * 3600
OPTIONS_TTL = timedelta(minutes=30)
OPTIONS_NONE_TTL = timedelta(hours=6)
OPTIONS_RETRY = timedelta(minutes=5)
OPTIONS_STALE_MAX = timedelta(hours=24)
OI_TTL = timedelta(minutes=5)
OI_RETRY = timedelta(seconds=60)
OI_STALE_MAX = timedelta(minutes=30)
# How long a request waits for a Bitget lookup it needs (the rest of the fetch carries on behind it).
OI_WAIT_S = 2.0
TIERS_WAIT_S = 3.0
TIERS_RETRY = timedelta(minutes=5)
STREET_LAST_GOOD_MAX = timedelta(hours=24)


def _filing_notes(ctx: AnalysisContext, ticket: TradeTicket, as_of: datetime, horizon_h: float) -> list[FilingNote]:
    """Filings recent enough to still be unpriced, with what the model made of them.

    The window matches the ``filings_72h`` feature. A filing the model has not read yet is
    still listed, marked ``unread`` with no impact label: the feature counts it, so the
    page must too. The numbers beside a read one come from the measured distribution for
    its label, never from the model.
    """
    from nightwatch.features.filing_outcomes import load_labels
    from nightwatch.features.filing_read import FilingReadStore

    at = ensure_utc(as_of)
    try:
        recent = ctx.store.get_filings(ticket.ticker, start=at - timedelta(hours=FILING_LOOKBACK_H), end=at, as_of=at)
    except Exception:  # noqa: BLE001 - a filing lookup must never fail an analysis
        log.exception("filing lookup failed for %s", ticket.ticker)
        return []
    if not recent:
        return []
    reads = FilingReadStore(ctx.store)
    labels = load_labels(ctx.store)
    window_end = at + timedelta(hours=horizon_h)
    notes: list[FilingNote] = []
    for f in sorted(recent, key=lambda x: x.accepted_at, reverse=True):
        read = reads.get(f.accession)
        if read is None:
            # Not yet read by the model: still listed (the feature counted it), plainly
            # marked, with no impact label and so no history figures beside it.
            notes.append(FilingNote(
                ticker=f.ticker, accepted_at=f.accepted_at, form=f.form, items=f.items,
                hours_ago=(at - ensure_utc(f.accepted_at)).total_seconds() / 3600.0,
                inside_window=ensure_utc(f.accepted_at) <= window_end,
                market_was_shut=classify_session(f.accepted_at).is_closed,
                category="unread", headline=(f.description or f"{f.form} filing") + " (not yet read by the model)", market_moving="unread",
            ))
            continue
        stats = labels.get(read.market_moving)
        notes.append(FilingNote(
            ticker=f.ticker, accepted_at=f.accepted_at, form=f.form, items=f.items,
            hours_ago=(at - ensure_utc(f.accepted_at)).total_seconds() / 3600.0,
            inside_window=ensure_utc(f.accepted_at) <= window_end,
            market_was_shut=classify_session(f.accepted_at).is_closed,
            category=read.category, headline=read.headline, market_moving=read.market_moving,
            label_n=stats.n if stats else None,
            label_p5_pct=stats.p5_pct if stats else None,
            label_median_pct=stats.median_pct if stats else None,
            label_mean_abs_pct=stats.mean_abs_pct if stats else None,
        ))
    return notes[:5]


def _analog_section(ctx: AnalysisContext, ticket: TradeTicket, snapshot: FeatureSnapshot, frame: pd.DataFrame, as_of: datetime, horizon_h: float, primary: str, warnings: list[str], *, entry_price: float = 0.0, liquidation_price: float | None = None) -> AnalogSection | None:
    from nightwatch.analog import lens as lens_mod

    engine = AnalogEngine(ctx.analog_config)
    query_bucket = snapshot.labels.get("bucket")
    frames: dict[str, pd.DataFrame] = {ticket.ticker: frame}

    # Narrow the searchable history *before* ranking, so the distances are measured
    # inside the cohort the trader asked for rather than picking the survivors of an
    # unfiltered ranking. Those are different cohorts and only the first answers the
    # question. The floor keeps a filter from leaving too little to search at all.
    floor = ctx.analog_config.min_matches * ctx.analog_config.min_separation_h

    # A hold over a weekend is matched to past holds over a weekend, not to any hour that
    # happens to look like now: the same hard-match idea as a lens, on the shape of the hold.
    # "Over the weekend" asked early in the week is a scheduled Friday-to-Monday hold, which
    # the clock from now would not show as one.
    scheduled = str((ticket.extra or {}).get("horizon_label", "")).startswith("the coming weekend") if isinstance(ticket.extra, dict) else False
    wk_query = scheduled or bool(lens_mod.spans_weekend(pd.DatetimeIndex([ensure_utc(as_of)]), horizon_h)[0])
    weekend_state: dict[str, Any] = {}

    def weekend_cut(parts: list[tuple[str, pd.DataFrame]], scope: str) -> list[tuple[str, pd.DataFrame]]:
        if not wk_query:
            return parts
        kept, state = lens_mod.restrict_to_weekend_holds(parts, horizon_h, min_rows=floor)
        weekend_state[scope] = state
        return kept

    def search_with(names: tuple[str, ...]) -> tuple[Any, str, Any, list[str]]:
        notes: list[str] = []
        searchable, lens_result = lens_mod.apply(frame, list(names), min_rows=floor)
        if lens_result.refused:
            notes.append(lens_result.refused)
        searchable = weekend_cut([(ticket.ticker, searchable)], "same_ticker")[0][1]

        result = engine.search(searchable.assign(ticker=ticket.ticker), snapshot.features, query_ts=snapshot.bar_ts, query_bucket=query_bucket, query_ticker=ticket.ticker, hold_h=horizon_h)
        scope = "same_ticker"
        same_ticker_episodes = result.n_distinct_available
        # A lens the token's own past cannot support is the main reason to widen. TSLA has 96
        # earnings hours and the universe has 1,752, so "only earnings nights" is unanswerable
        # on one name and perfectly answerable across twenty-four. Widening for that is worth
        # doing even when the unfiltered same-ticker search succeeded, because a good answer
        # to a question nobody asked is not an answer.
        lens_needs_more = bool(names) and not lens_result.applied
        if not result.ok or result.n < ctx.analog_config.k or lens_needs_more:
            # The unfiltered frame: the lens is applied to every part below, and counting
            # "of how many" from an already-narrowed one would understate what it cost.
            pooled_parts = [(ticket.ticker, frame)]
            tickers = ctx.pooled_tickers or ctx.tickers_with_data()
            for t in tickers:
                if t == ticket.ticker:
                    continue
                try:
                    f = frames[t] if t in frames else ctx.feature_frame(t, as_of)
                except InsufficientData:
                    continue
                frames[t] = f
                pooled_parts.append((t, f))
            if len(pooled_parts) > 1:
                # The same lens, across the wider history. A condition that is too rare in one
                # token's past is often common enough across twenty-four of them - earnings
                # nights are 96 hours for TSLA alone and 1,752 pooled - so this is usually
                # where a narrow question becomes answerable at all. Narrowing each part before
                # stacking gives the same rows without building the whole haystack first.
                pooled_parts, pooled_lens = lens_mod.apply_to_parts(pooled_parts, list(names), min_rows=floor)
                pooled_parts = weekend_cut(pooled_parts, "pooled")
                pooled = pooled_history(pooled_parts)
                pooled_result = engine.search(pooled, snapshot.features, query_ts=snapshot.bar_ts, query_bucket=query_bucket, query_ticker=ticket.ticker, hold_h=horizon_h)
                # A pooled cohort that honours the lens beats a same-ticker one that ignores
                # it, whatever their sizes: they are answers to different questions.
                honours_lens = lens_needs_more and pooled_lens.applied
                if pooled_result.ok and (honours_lens or not result.ok or pooled_result.n > result.n):
                    if honours_lens:
                        # The pooled search honoured what the token's own past could not, so
                        # the refusal recorded a moment ago is no longer true.
                        notes = [w for w in notes if w != lens_result.refused]
                        notes.append(
                            f"{lens_mod.describe(pooled_lens.lenses)} is too rare in {ticket.ticker}'s own past; "
                            f"searched the pooled history across {len(pooled_parts)} tokens instead"
                        )
                    else:
                        notes.append(f"same-ticker history has only {same_ticker_episodes} distinct episodes; using pooled history across {len(pooled_parts)} tickers")
                    result, scope, lens_result = pooled_result, "pooled", pooled_lens
                elif lens_needs_more and pooled_lens.applied and not pooled_result.ok:
                    # The pooled history had the hours but not the separate events, so the
                    # unfiltered same-token answer stands - and the reason given has to be
                    # the one that decided it, not the "too few hours" from one token.
                    why = (
                        f"{lens_mod.describe(pooled_lens.lenses)} covers {pooled_lens.n_after:,} past hours across the pooled history, "
                        f"but {pooled_result.reason} - they fall on too few separate dates to count as independent evidence; "
                        f"the answer below is the unfiltered one"
                    )
                    notes = [w for w in notes if w != lens_result.refused] + [why]
                    lens_result = replace(lens_result, refused=why, n_before=pooled_lens.n_before, n_after=pooled_lens.n_after)
        return result, scope, lens_result, notes

    result, scope, lens_result, notes = search_with(tuple(ticket.lenses))
    if ticket.lenses and lens_result.applied and not result.ok:
        # Enough hours, too few separate events. FOMC nights fall on the same dates for
        # every token, so a thousand pooled hours can be a dozen meetings, and the engine
        # rightly refuses to call a dozen a distribution. Measured across every past
        # overnight hold, this happened on 471 of 474 FOMC nights. Answering nothing would
        # be the worst response to it; the unfiltered answer, labelled as such, is the
        # same one given when a condition leaves too few hours.
        narrowed_reason = result.reason
        result, scope, _, notes = search_with(())
        lens_result = replace(
            lens_result, applied=False,
            refused=(
                f"{lens_mod.describe(lens_result.lenses)} covers {lens_result.n_after:,} past hours, but {narrowed_reason} - "
                f"they fall on too few separate dates to count as independent evidence; the answer below is the unfiltered one"
            ),
        )
        notes.append(lens_result.refused)
    warnings.extend(notes)
    weekend_hold = weekend_state.get(scope) if wk_query else None
    if weekend_hold is not None and result.ok and result.matches:
        k = int(lens_mod.spans_weekend(pd.DatetimeIndex([pd.Timestamp(m.ts) for m in result.matches]), horizon_h).sum())
        weekend_hold = replace(weekend_hold, k_weekend=k, n_matches=result.n)
        if weekend_hold.note:
            warnings.append(weekend_hold.note)
    if not result.ok:
        warnings.append(f"analog search refused: {result.reason}")
        return AnalogSection(result=result, scope=scope, horizons={}, matches_outcomes=[], lens=lens_result, weekend_hold=weekend_hold)

    # The ticket's own horizon length is applied uniformly to every analog (that is the
    # cohort the verdict uses); the structural horizons are each analog's *own* next
    # open / window end and are reported alongside for context.
    ticket_h = max(1, round_half_up(horizon_h))
    fixed = tuple(sorted({24, 72, ticket_h}))
    outcomes: list[MatchOutcome] = []
    for m in result.matches:
        f = frames.get(m.ticker)
        if f is None:
            continue
        try:
            outcomes.append(ctx.match_outcomes(f, m.ts, fixed))
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
    base_outcomes = [ctx.match_outcomes(frame, t.to_pydatetime(), fixed) for t in base_ts]
    factors = ctx.tail_factors(as_of)
    for name in horizon_names:
        table = outcomes_table(outcomes, name)
        stats = summarize(table, weights=weights, min_sample=ctx.analog_config.min_matches)
        base_table = outcomes_table(base_outcomes, name)
        comparison = ctx.baseline_comparison(table, base_table, ctx.analog_config.min_matches) if not table.empty and not base_table.empty else None
        hours = float(table["hours"].mean()) if not table.empty else float("nan")
        p5_adj = p95_adj = None
        adjustment = None
        # Each horizon is widened by the factor fitted on windows of its own length. An
        # overnight hold and a weekend hold need very different corrections, and the
        # single pooled factor was the average of the two - too tight for one, roughly
        # twice too wide for the other.
        band_factors = factors.for_hours(hours) if factors is not None else None
        if hours > CALIBRATED_MAX_H:
            # Every scored forecast is 90 hours or shorter, and the multi-day factor was fitted
            # on weekends, when the stock barely trades. Applied to a week that includes five
            # sessions it shrank a -6.4% tail to -4.9%, beside a base rate of 13% falling 5%.
            # Past the longest scored hold the raw history stands, and says it is uncalibrated.
            band_factors = None
            adjustment = {"uncalibrated": True, "longest_scored_h": CALIBRATED_MAX_H}
        if band_factors is not None and not stats.insufficient:
            from nightwatch.journal.adjust import apply_factors

            p5_adj, p95_adj = apply_factors(stats.p5, stats.median_pct, stats.p95, band_factors)
            adjustment = {
                "k_lo": band_factors.k_lo, "k_hi": band_factors.k_hi, "c_lo": band_factors.c_lo, "n_fit": band_factors.n_fit,
                "fitted_through": band_factors.fitted_through.isoformat() if band_factors.fitted_through else None,
                "scope": band_factors.scope,
            }
        horizons[name] = HorizonReport(horizon=name, hours=hours, cohort=stats, baseline=comparison, p5_adjusted=p5_adj, p95_adjusted=p95_adj, adjustment=adjustment)
    _floor_longer_holds(horizons)
    short_factors = ctx.tail_factors(as_of, side="short") if ticket.side.value == "short" else None
    for h in horizons.values():
        _position_view(h, ticket.side.value, short_factors)
    if primary in horizons and horizons[primary].cohort.insufficient:
        warnings.append(f"analog cohort for the {primary} horizon is below the minimum sample; verdict falls back to the stop for risk")

    # The scenarios as paths, over the ticket's own horizon only. Drawing all five
    # horizons would multiply the report size for four pictures nobody asked for.
    from nightwatch.analog import paths as paths_mod

    scenario_paths = paths_mod.build(
        result.matches, frames, horizon_h=float(ticket_h), side=ticket.side.value,
        stop_price=ticket.stop_price, entry_price=entry_price, liquidation_price=liquidation_price,
    )
    return AnalogSection(result=result, scope=scope, horizons=horizons, matches_outcomes=outcomes, paths=scenario_paths, lens=lens_result, weekend_hold=weekend_hold)


def _cautious_of(narrowed: AnalogSection, plain: AnalogSection | None) -> list[str]:
    """Hold each narrowed horizon's loss line to at least the unfiltered one's. Returns the
    horizons where the unfiltered answer was the more cautious and was used."""
    used: list[str] = []
    if plain is None:
        return used
    for name, h in narrowed.horizons.items():
        other = plain.horizons.get(name)
        if other is None or other.loss_p5_pct is None:
            continue
        if h.loss_p5_pct is None or other.loss_p5_pct < h.loss_p5_pct:
            h.loss_p5_pct = other.loss_p5_pct
            h.adjustment = {**(h.adjustment or {}), "cautious_of_two": "unfiltered"}
            used.append(name)
    return used


def _floor_longer_holds(horizons: dict[str, HorizonReport]) -> None:
    """A longer hold's one-in-twenty loss is never shown milder than a shorter hold's.

    Each horizon is its own cohort and its own calibration band, so they can disagree: a
    re-test found a 5-hour hold at -4.5% beside a 173-hour hold at -4.4%, and a judge will
    not believe a week carries less risk than an evening. The longer hold passes through the
    shorter one, so its tail is floored at the worst shorter tail. The multi-day band was
    already breached 6.3% of the time against a 5% target - too narrow, not too wide - so
    the floor moves it the way the scorecard says it should go.
    """
    # Both tails: the lower one is a long's loss, the upper one a short's.
    worst: tuple[float, str] | None = None
    worst_up: tuple[float, str] | None = None
    for name, h in sorted(horizons.items(), key=lambda kv: kv[1].hours):
        if h.cohort.insufficient:
            continue
        p5 = h.p5_adjusted if h.p5_adjusted is not None else h.cohort.p5
        if p5 is not None:
            if worst is not None and p5 > worst[0]:
                h.p5_adjusted = worst[0]
                h.adjustment = {**(h.adjustment or {}), "floored_by": worst[1]}
            elif worst is None or p5 < worst[0]:
                worst = (p5, name)
        p95 = h.p95_adjusted if h.p95_adjusted is not None else getattr(h.cohort, "p95", None)
        if p95 is not None:
            if worst_up is not None and p95 < worst_up[0]:
                h.p95_adjusted = worst_up[0]
                h.adjustment = {**(h.adjustment or {}), "floored_up_by": worst_up[1]}
            elif worst_up is None or p95 > worst_up[0]:
                worst_up = (p95, name)


def _stress_section(ctx: AnalysisContext, ticket: TradeTicket, spec: SeriesSpec, snapshot: FeatureSnapshot, frame: pd.DataFrame, book: OrderBookSnapshot | None, taker_fee: float, horizon_h: float, entry_price: float, warnings: list[str], *, as_of: datetime | None = None, analog_p5: float | None = None, options_move_pct: float | None = None) -> StressSection:
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
    inp = EmpiricalInputs(closed_window_ret_pct=closed, earnings_gap_pct=gaps, abs_basis_closed_bps=basis_closed, rv_24h_now=float(snapshot.features.get("rv_24h") or 0.0), rv_168h_now=float(snapshot.features.get("rv_168h") or 0.0), horizon_h=horizon_h, funding_rate_abs_p95=funding_p95,
                          hours_to_earnings=snapshot.features.get("hours_to_earnings"), hours_since_earnings=snapshot.features.get("hours_since_earnings"),
                          adverse_sign=-1.0 if ticket.closing_long else 1.0,
                          ticker=ticket.ticker, crash_moves=crash_replays().get(ticket.ticker) or {},
                          closed_windows_in_hold=closed_windows_in_hold(as_of, horizon_h) if as_of is not None else 1, analog_p5_loss_pct=analog_p5, options_implied_move_pct=options_move_pct)
    presets = build_presets(inp)
    position = Position(ticket.ticker, ticket.side, ticket.notional_quote, entry_price, hedge_ratio=ticket.hedge_ratio or 0.0)
    impacts = [apply_scenario(position, p, book=book, taker_fee=taker_fee) for p in presets]

    mc = None
    rets = hourly_log_returns(frame, closed_only=ticket.horizon_kind != HorizonKind.HOURS)
    if rets.size < 48:
        rets = hourly_log_returns(frame, closed_only=False)
    if rets.size >= 48 and horizon_h >= 1:
        mc = simulate(position.sign, rets, round_half_up(horizon_h))
    else:
        warnings.append("not enough hourly history for a Monte Carlo over the horizon")
    reverse = reverse_stress(position, book=book, taker_fee=taker_fee, target_loss_pct=ctx.sizing_policy.max_stress_loss_pct, horizon_h=horizon_h) if book is not None else None
    return StressSection(
        presets=presets, impacts=impacts, monte_carlo=mc, reverse_move_pct_for_5pct_loss=reverse,
        inputs_summary={"closed_windows_n": int(closed.size), "earnings_gaps_n": int(gaps.size), "closed_basis_obs_n": int(basis_closed.size), "rv_24h": inp.rv_24h_now, "rv_168h": inp.rv_168h_now, "funding_abs_p95": funding_p95, "mc_source_hours": int(rets.size),
                        "earnings_in_window": earnings_in_window(inp), "hours_to_earnings": inp.hours_to_earnings},
    )


def _execution_section(ctx: AnalysisContext, ticket: TradeTicket, spec: SeriesSpec, frame: pd.DataFrame, book: OrderBookSnapshot | None, book_source: str, fees: dict[str, float], horizon_h: float, entry: UniverseEntry, as_of: datetime) -> ExecutionSection:
    exit_quote = curve = None
    max_n = None
    if book is not None:
        exit_quote = quote_exit(book, ticket.notional_quote, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"])
        curve = cost_curve(book, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"])
        max_n = max_notional_within(book, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"], budget_bps=ctx.sizing_policy.exit_cost_budget_bps)
    # One wide snapshot must not decide the size. The same ticket read NO GO with "nothing
    # to size" at a 37 bps exit and GO at 11 bps ten minutes later. When the book now is far
    # wider than it has been over the last two hours, the size limit is taken from the
    # typical book of those two hours, and the report says the book is wide right now.
    book_note = None
    if book is not None and book.mid:
        now_spread = (book.asks[0].price - book.bids[0].price) / book.mid * 1e4 if book.asks and book.bids else None
        typical, typical_spread = ctx.store.typical_orderbook(Venue.BITGET_SPOT, spec.spot_symbol, as_of - WIDE_BOOK_LOOKBACK, as_of)
        if now_spread is not None and typical is not None and typical_spread and now_spread > max(WIDE_BOOK_RATIO * typical_spread, typical_spread + WIDE_BOOK_MIN_BPS):
            max_typ = max_notional_within(typical, closing_long=ticket.closing_long, taker_fee=fees["spot_taker"], budget_bps=ctx.sizing_policy.exit_cost_budget_bps)
            if max_typ is not None and (max_n is None or max_typ > max_n):
                max_n = max_typ
                book_note = (
                    f"the book is unusually wide right now ({now_spread:.0f} bps spread against {typical_spread:.0f} typical over the last two hours): "
                    "the size limit uses the typical book, but getting in or out this minute costs more - wait, or use a limit order"
                )
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
        book_ts=book.ts if book else None, book_source=book_source, liquidity_history=history, book_note=book_note,
    )


# -------------------------------------------------------------------- helpers


def _get_book(ctx: AnalysisContext, symbol: str, as_of: datetime) -> tuple[OrderBookSnapshot | None, str]:
    # The book as of the moment asked about. A what-if re-runs an earlier report at that
    # report's moment, and used to pick up whatever book was newest - so "against the
    # same moment" compared two different books.
    snap = ctx.store.latest_orderbook(Venue.BITGET_SPOT, symbol, at=as_of)
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


FEES_TTL_S = 600.0


def _fees(ctx: AnalysisContext, spec: SeriesSpec) -> dict[str, float]:
    key = (spec.spot_symbol, spec.perp_symbol)
    hit = ctx._fee_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < FEES_TTL_S:
        return dict(hit[1])
    fees = _read_fees(ctx, spec)
    ctx._fee_cache[key] = (time.monotonic(), fees)
    return dict(fees)


def _read_fees(ctx: AnalysisContext, spec: SeriesSpec) -> dict[str, float]:
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
    return h.loss_p5_pct


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _book_stress(ctx: AnalysisContext, ticket: TradeTicket, model: Any, held: list[BookPosition], fees: dict[str, float], horizon_h: float, lev_view: Any) -> Any:  # noqa: ANN401
    """Crash replays, rebalance plans and reverse stress for the whole book; never breaks a report."""
    t0 = time.perf_counter()
    try:
        from nightwatch.decision import book_plans

        perps: set[str] = set()
        for name in {p.ticker for p in held} | {ticket.ticker}:
            try:
                if ctx.spec(name).perp_symbol:
                    perps.add(name)
            except Exception:  # noqa: BLE001 - a name outside the universe simply cannot be hedged
                continue
        out = book_plans.build(
            model, held, BookPosition(ticket.ticker, ticket.side.value, ticket.notional_quote),
            equity=ticket.account_equity_quote, limit_pct_of_equity=ctx.sizing_policy.max_book_tail_pct_of_equity,
            horizon_h=horizon_h, perp_names=perps, spot_taker=fees["spot_taker"], perp_taker=fees["perp_taker"],
            leverage=lev_view.to_dict() if lev_view is not None else None,
        )
        log.debug("book stress took %d ms", _ms(t0))
        return out
    except Exception:  # noqa: BLE001 - the plans are an extra; the verdict does not wait on them
        log.exception("book stress failed")
        return None


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
