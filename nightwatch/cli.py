"""Command-line entry points: sync, record, status."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

import pandas as pd

from nightwatch.config import Settings, load_settings
from nightwatch.data.bitget import BitgetPublicClient
from nightwatch.data.fred import CORE_SERIES, FredClient
from nightwatch.data.models import Interval, Venue
from nightwatch.data.nasdaq import NasdaqEarningsClient
from nightwatch.data.rss import RssNewsClient
from nightwatch.data.store import Store
from nightwatch.data.sync import (
    HISTORY_START,
    UniverseEntry,
    coverage_report,
    refresh_universe,
    resolve_universe,
    sync_calendars,
    sync_macro_series,
    sync_news,
    sync_universe,
)
from nightwatch.data.yahoo import YahooChartClient
from nightwatch.recorder.orderbook_recorder import OrderBookRecorder, PeriodicJob
from nightwatch.time_utils import UTC


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _clients(settings: Settings) -> tuple[BitgetPublicClient, BitgetPublicClient]:
    return (
        BitgetPublicClient(Venue.BITGET_SPOT, rate_per_sec=settings.bitget_rate_per_sec),
        BitgetPublicClient(Venue.BITGET_UMCBL, rate_per_sec=settings.bitget_rate_per_sec),
    )


def _select(entries: list[UniverseEntry], *, core_only: bool, tickers: list[str] | None, limit: int | None) -> list[UniverseEntry]:
    if tickers:
        wanted = {t.upper() for t in tickers}
        entries = [e for e in entries if e.ticker in wanted]
    elif core_only:
        entries = [e for e in entries if e.is_core]
    if limit:
        entries = entries[:limit]
    return entries


# ------------------------------------------------------------------- commands


def cmd_universe(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    with Store(settings.db_path) as store:
        entries = resolve_universe(store, spot, perp, settings)
    entries = _select(entries, core_only=args.core, tickers=args.tickers, limit=args.limit)
    df = pd.DataFrame([e.__dict__ for e in entries])
    with pd.option_context("display.max_rows", None, "display.width", 160):
        print(df.to_string(index=False))
    print(f"\n{len(entries)} entries; {sum(1 for e in entries if e.perp_symbol)} with a perp")
    return 0


def cmd_sync(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    yahoo = YahooChartClient()
    nasdaq = NasdaqEarningsClient()
    start = datetime.fromisoformat(args.since).replace(tzinfo=UTC) if args.since else HISTORY_START
    intervals = [Interval(i) for i in args.intervals]
    with Store(settings.db_path) as store:
        entries = _select(resolve_universe(store, spot, perp, settings), core_only=args.core, tickers=args.tickers, limit=args.limit)
        logging.getLogger(__name__).info("syncing %d entries from %s", len(entries), start.date())
        stats = sync_universe(
            store, entries, spot=spot, perp=perp, yahoo=yahoo, nasdaq=None if args.no_earnings else nasdaq,
            intervals=intervals, start=start, include_equity=not args.no_equity,
        )
    print(stats)
    return 1 if stats.errors else 0


def cmd_refresh(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    with Store(settings.db_path) as store:
        entries = _select(resolve_universe(store, spot, perp, settings), core_only=args.core, tickers=args.tickers, limit=args.limit)
        n = refresh_universe(store, entries, spot=spot, perp=perp)
    print(f"refreshed {n} rows")
    return 0


def cmd_calendars(args: argparse.Namespace, settings: Settings) -> int:
    fred = FredClient(settings.fred_api_key)
    nasdaq = NasdaqEarningsClient()
    with Store(settings.db_path) as store:
        n_e, n_m = sync_calendars(store, nasdaq=nasdaq, fred=fred, days_ahead=args.days_ahead)
        n_s = sync_macro_series(store, fred, CORE_SERIES) if not args.no_series else 0
    print(f"earnings calendar rows: {n_e}; macro calendar rows: {n_m}; macro series rows: {n_s}")
    return 0


def cmd_news(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    with Store(settings.db_path) as store:
        tickers = [i.underlying_ticker for i in store.list_instruments(Venue.BITGET_SPOT, tokenized_only=True) if i.underlying_ticker]
        if not tickers:
            tickers = list(settings.core_tickers)
        n = sync_news(store, RssNewsClient(tickers=tickers))
    print(f"news rows: {n}")
    return 0


def cmd_record(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    with Store(settings.db_path) as store:
        entries = _select(resolve_universe(store, spot, perp, settings), core_only=not args.all, tickers=args.tickers, limit=args.limit)
        jobs: list[PeriodicJob] = []
        if not args.no_jobs:
            from nightwatch.journal.journal import Journal
            from nightwatch.journal.postmortem import mature_and_learn

            fred = FredClient(settings.fred_api_key)
            nasdaq = NasdaqEarningsClient()
            tickers = [e.ticker for e in entries]
            journal = Journal(store)
            jobs = [
                # Earnings dates move and macro releases get scheduled; six-hourly is plenty.
                PeriodicJob("calendars", 6 * 3600, lambda: sync_calendars(store, nasdaq=nasdaq, fred=fred), run_at_start=False),
                PeriodicJob("news", 1800, lambda: sync_news(store, RssNewsClient(tickers=tickers)), run_at_start=False),
                # Score live tickets as soon as their horizon has passed so calibration stays current.
                PeriodicJob("mature-forecasts", 900, lambda: mature_and_learn(journal, spot_symbol_for={e.ticker: e.spot_symbol for e in entries})),
            ]
        rec = OrderBookRecorder(
            store, spot=spot, perp=perp, entries=entries, interval_sec=args.interval,
            record_perp_books=not args.no_perp_books,
            refresh_bars_every_sec=None if args.no_bar_refresh else args.bar_refresh,
            retention_days=settings.recorder_retention_days, jobs=jobs,
        )
        rec.install_signal_handlers()
        rec.run_forever()
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    spot, perp = _clients(settings)
    with Store(settings.db_path) as store:
        entries = _select(resolve_universe(store, spot, perp, settings), core_only=args.core, tickers=args.tickers, limit=args.limit)
        df = coverage_report(store, entries)
        if df.empty:
            print("no data yet")
            return 0
        df = df[df["bars"] > 0] if not args.all_rows else df
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(df.to_string(index=False))
        ob = store._conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM orderbook_snapshots").fetchone()
        print(f"\norder-book snapshots: {ob[0]}")
        for name in ("tickers", "funding", "earnings", "macro", "news"):
            print(f"{name}: {store._conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]}")
    return 0


def cmd_analyze(args: argparse.Namespace, settings: Settings) -> int:
    from nightwatch.decision.ticket import HorizonKind, TradeTicket
    from nightwatch.pipeline.analyze import AnalysisContext, analyze
    from nightwatch.pipeline.render import render_text
    from nightwatch.stress.scenarios import Side

    spot, perp = _clients(settings)
    from nightwatch.journal.journal import Journal

    with Store(settings.db_path) as store:
        entries = resolve_universe(store, spot, perp, settings) if not args.offline else _entries_from_store(store, settings)
        ctx = AnalysisContext(store=store, entries=entries, spot_client=None if args.offline else spot, perp_client=None if args.offline else perp, journal=Journal(store))
        ticket = TradeTicket(
            ticker=args.ticker.upper(), side=Side(args.side), notional_quote=args.notional, account_equity_quote=args.equity,
            horizon_kind=HorizonKind(args.horizon), horizon_hours=args.hours, entry_price=args.entry, stop_price=args.stop,
            target_price=args.target, thesis=args.thesis or "", invalidation=args.invalidation or "", hedge_ratio=args.hedge,
        )
        as_of = datetime.fromisoformat(args.as_of).replace(tzinfo=UTC) if args.as_of else None
        report = analyze(ctx, ticket, as_of=as_of)
        if args.json:
            import json

            print(json.dumps(report.to_dict(), indent=1, default=str))
        else:
            print(render_text(report))
    return 0


def cmd_replay(args: argparse.Namespace, settings: Settings) -> int:
    from nightwatch.journal.journal import Journal
    from nightwatch.journal.replay import replay_ticker
    from nightwatch.pipeline.analyze import AnalysisContext

    with Store(settings.db_path) as store:
        entries = _entries_from_store(store, settings)
        journal = Journal(store)
        ctx = AnalysisContext(store=store, entries=entries, journal=journal)
        total = 0
        for t in args.tickers:
            if args.reset:
                print(f"{t.upper()}: removed {journal.delete_replays(t.upper())} earlier replay forecasts")
            n = replay_ticker(ctx, journal, t.upper(), lookback_days=args.lookback_days, max_points=args.max_points, horizon=args.horizon, side=args.side)
            print(f"{t.upper()}: {n} replay forecasts recorded")
            total += n
        matured = journal.mature(spot_symbol_for={e.ticker: e.spot_symbol for e in entries})
        print(f"matured {matured} forecasts")
    return 0


def cmd_calibration(args: argparse.Namespace, settings: Settings) -> int:
    from nightwatch.journal.calibration import calibrate, render_calibration
    from nightwatch.journal.journal import Journal

    with Store(settings.db_path) as store:
        entries = _entries_from_store(store, settings)
        journal = Journal(store)
        matured = journal.mature(spot_symbol_for={e.ticker: e.spot_symbol for e in entries})
        df = journal.forecasts(ticker=args.ticker.upper() if args.ticker else None, kind=args.kind, matured_only=True)
        print(f"(matured {matured} new forecasts)")
        print(render_calibration(calibrate(df)))
        from nightwatch.journal.skill import compare_skill, render_skill

        print()
        print(render_skill(compare_skill(df)))
        from nightwatch.journal.walkforward import by_period
        from nightwatch.journal.walkforward import render as render_walk

        print()
        print(render_walk(by_period(df)))
        from nightwatch.journal.adjust import evaluate_expanding

        ev = evaluate_expanding(df) if not df.empty else None
        if ev:
            print(
                f"\nTAIL ADJUSTMENT (expanding-window, out-of-sample on {ev.n_evaluated} forecasts; last k_lo {ev.k_lo_last:.2f}, k_hi {ev.k_hi_last:.2f})\n"
                f"  below p5 : raw {ev.raw_lo_coverage:.1%} -> adjusted {ev.adj_lo_coverage:.1%} (target 5%)\n"
                f"  above p95: raw {ev.raw_hi_coverage:.1%} -> adjusted {ev.adj_hi_coverage:.1%} (target 5%)\n"
                f"  inside p5-p95: raw {ev.raw_band_coverage:.1%} -> adjusted {ev.adj_band_coverage:.1%} (target 90%)\n"
                f"  5% tail band: raw {ev.raw_tail_band} -> adjusted {ev.adj_tail_band} | mean width {ev.raw_width:.2f}% -> {ev.adj_width:.2f}%"
            )
    return 0


def _entries_from_store(store: Store, settings: Settings) -> list[UniverseEntry]:
    from nightwatch.data.sync import build_universe

    return build_universe(store.list_instruments(Venue.BITGET_SPOT), store.list_instruments(Venue.BITGET_UMCBL), settings.core_tickers)


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nightwatch", description="Nightwatch data tools")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--core", action="store_true", help="only the configured core tickers")
        sp.add_argument("--tickers", nargs="*", help="explicit tickers")
        sp.add_argument("--limit", type=int, help="first N entries after selection")

    sp = sub.add_parser("universe", help="resolve and print the tokenized-stock universe")
    common(sp)
    sp.set_defaults(func=cmd_universe)

    sp = sub.add_parser("sync", help="backfill bars, funding, earnings history")
    common(sp)
    sp.add_argument("--since", help="ISO date, default 2025-01-01")
    sp.add_argument("--intervals", nargs="*", default=["1h", "1d"])
    sp.add_argument("--no-equity", action="store_true")
    sp.add_argument("--no-earnings", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("refresh", help="bring hourly bars up to date")
    common(sp)
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("calendars", help="earnings + macro calendars and FRED series")
    sp.add_argument("--days-ahead", type=int, default=120)
    sp.add_argument("--no-series", action="store_true")
    sp.set_defaults(func=cmd_calendars)

    sp = sub.add_parser("news", help="fetch RSS headlines")
    sp.set_defaults(func=cmd_news)

    sp = sub.add_parser("record", help="run the order-book recorder (core tickers by default)")
    sp.add_argument("--all", action="store_true", help="record the whole universe (heavy)")
    sp.add_argument("--tickers", nargs="*")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--interval", type=int, default=60)
    sp.add_argument("--no-perp-books", action="store_true")
    sp.add_argument("--bar-refresh", type=int, default=900, help="seconds between hourly-bar refreshes")
    sp.add_argument("--no-bar-refresh", action="store_true")
    sp.add_argument("--no-jobs", action="store_true", help="skip the periodic calendar/news/maturation jobs")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("status", help="coverage report")
    common(sp)
    sp.add_argument("--all-rows", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("analyze", help="stress-test a trade ticket")
    sp.add_argument("--ticker", required=True)
    sp.add_argument("--side", choices=["long", "short"], default="long")
    sp.add_argument("--notional", type=float, required=True, help="position size in USDT")
    sp.add_argument("--equity", type=float, help="account equity in USDT")
    sp.add_argument("--horizon", choices=["next_open", "window_end", "hours"], default="next_open")
    sp.add_argument("--hours", type=float)
    sp.add_argument("--entry", type=float)
    sp.add_argument("--stop", type=float)
    sp.add_argument("--target", type=float)
    sp.add_argument("--thesis")
    sp.add_argument("--invalidation")
    sp.add_argument("--hedge", type=float)
    sp.add_argument("--as-of", help="ISO UTC timestamp for a point-in-time analysis")
    sp.add_argument("--offline", action="store_true", help="use stored instruments/books only, no network")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("replay", help="record point-in-time forecasts over stored history and mature them")
    sp.add_argument("--tickers", nargs="+", required=True)
    sp.add_argument("--lookback-days", type=int, default=180)
    sp.add_argument("--max-points", type=int, default=150)
    sp.add_argument("--horizon", default="next_open")
    sp.add_argument("--side", choices=["long", "short"], default="long")
    sp.add_argument("--reset", action="store_true", help="delete earlier replay forecasts for these tickers first")
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser("calibration", help="score matured forecasts against realised outcomes")
    sp.add_argument("--ticker")
    sp.add_argument("--kind", choices=["ticket", "replay"])
    sp.set_defaults(func=cmd_calibration)
    return p


def main(argv: list[str] | None = None) -> int:
    # Reports use a few non-ASCII glyphs; legacy Windows consoles default to cp1252
    # and would abort mid-print, so make stdout tolerant rather than dropping the glyphs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    _logging(args.verbose)
    settings = load_settings()
    return int(args.func(args, settings))


if __name__ == "__main__":
    sys.exit(main())
