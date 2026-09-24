"""SQLite persistence with point-in-time reads.

One file, WAL mode, explicit schema, idempotent upserts. Chosen over Parquet/DuckDB
because the recorder appends every minute for weeks and the API server reads
concurrently; SQLite handles that on a single box with zero operational overhead.

Point-in-time rule
------------------
Every table stores ``observed_at`` (when *we* first saw the row). Readers may pass
``as_of``; rows observed after that instant are excluded. This is how the analog
engine and the calibration page avoid using information that did not exist yet.
On conflict we update values but keep the *earliest* ``observed_at``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from nightwatch.data.book_metrics import DEPTH_BPS_LEVELS, snapshot_metrics
from nightwatch.data.models import (
    Bar,
    EarningsEvent,
    Filing,
    FundingRate,
    Instrument,
    Interval,
    MacroRelease,
    NewsItem,
    OrderBookLevel,
    OrderBookSnapshot,
    PriceKind,
    Ticker,
    Venue,
)
from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms

_DEPTH_COLS = [f"depth_bid_{k}bps" for k in DEPTH_BPS_LEVELS] + [
    f"depth_ask_{k}bps" for k in DEPTH_BPS_LEVELS
] + [f"imbalance_{k}bps" for k in DEPTH_BPS_LEVELS]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS bars (
    venue TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, kind TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume_base REAL, volume_quote REAL,
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (venue, symbol, interval, kind, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS bars_observed ON bars (venue, symbol, interval, kind, observed_at);

CREATE TABLE IF NOT EXISTS instruments (
    venue TEXT NOT NULL, symbol TEXT NOT NULL,
    payload TEXT NOT NULL, observed_at INTEGER NOT NULL,
    PRIMARY KEY (venue, symbol)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY,
    venue TEXT NOT NULL, symbol TEXT NOT NULL,
    ts INTEGER NOT NULL, observed_at INTEGER NOT NULL,
    best_bid REAL, best_ask REAL, mid REAL, spread_bps REAL,
    n_bids INTEGER, n_asks INTEGER,
    bid_notional_total REAL, ask_notional_total REAL,
    {", ".join(f"{c} REAL" for c in _DEPTH_COLS)},
    levels TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ob_symbol_ts ON orderbook_snapshots (venue, symbol, ts);
-- Covering index for the liquidity archive, which reads five small columns of a month
-- of snapshots. Each row also carries ~2 KB of level JSON, so without this the read
-- pulled ~17k bulky rows off disk: 12 s per token on the live box, 0.04 s with it.
CREATE INDEX IF NOT EXISTS ob_metrics ON orderbook_snapshots (venue, symbol, ts, spread_bps, depth_bid_25bps, depth_ask_25bps, bid_notional_total);

CREATE TABLE IF NOT EXISTS funding (
    venue TEXT NOT NULL, symbol TEXT NOT NULL, ts INTEGER NOT NULL,
    rate REAL NOT NULL, interval_hours INTEGER, observed_at INTEGER NOT NULL,
    PRIMARY KEY (venue, symbol, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tickers (
    venue TEXT NOT NULL, symbol TEXT NOT NULL, ts INTEGER NOT NULL,
    last REAL, bid REAL, ask REAL, bid_size REAL, ask_size REAL,
    index_price REAL, mark_price REAL, funding_rate REAL, open_interest REAL,
    volume_24h_quote REAL, observed_at INTEGER NOT NULL,
    PRIMARY KEY (venue, symbol, ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS earnings (
    ticker TEXT NOT NULL, report_date INTEGER NOT NULL, source TEXT NOT NULL,
    timing TEXT, eps_estimate REAL, eps_actual REAL, surprise_pct REAL,
    fiscal_quarter_end TEXT, observed_at INTEGER NOT NULL,
    PRIMARY KEY (ticker, report_date, source)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS macro (
    series_id TEXT NOT NULL, release_ts INTEGER NOT NULL,
    name TEXT NOT NULL, value REAL, period TEXT, source TEXT NOT NULL,
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (series_id, release_ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS filings (
    ticker TEXT NOT NULL, accession TEXT NOT NULL,
    cik TEXT NOT NULL, form TEXT NOT NULL, accepted_at INTEGER NOT NULL, filed_date INTEGER NOT NULL,
    description TEXT, items TEXT, source TEXT NOT NULL, observed_at INTEGER NOT NULL,
    PRIMARY KEY (ticker, accession)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS filings_ticker_time ON filings (ticker, accepted_at);

CREATE TABLE IF NOT EXISTS news (
    source TEXT NOT NULL, id TEXT NOT NULL,
    published_at INTEGER NOT NULL, title TEXT NOT NULL, link TEXT, summary TEXT,
    tickers TEXT NOT NULL, observed_at INTEGER NOT NULL,
    PRIMARY KEY (source, id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS news_published ON news (published_at);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY,
    task TEXT NOT NULL, venue TEXT, symbol TEXT, interval TEXT, kind TEXT,
    range_start INTEGER, range_end INTEGER, rows INTEGER NOT NULL,
    started_at INTEGER NOT NULL, finished_at INTEGER NOT NULL, note TEXT
);
"""


def _ms(ts: datetime | None) -> int | None:
    return None if ts is None else to_epoch_ms(ts)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --------------------------------------------------------------------- bars

    def upsert_bars(self, bars: Iterable[Bar]) -> int:
        rows = [
            (
                b.venue.value, b.symbol, b.interval.value, b.kind.value, to_epoch_ms(b.ts),
                b.open, b.high, b.low, b.close, b.volume_base, b.volume_quote, to_epoch_ms(b.observed_at),
            )
            for b in bars
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO bars (venue, symbol, interval, kind, ts, open, high, low, close,
                                  volume_base, volume_quote, observed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (venue, symbol, interval, kind, ts) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                    volume_base=excluded.volume_base, volume_quote=excluded.volume_quote,
                    observed_at=MIN(bars.observed_at, excluded.observed_at)
                """,
                rows,
            )
        return len(rows)

    def get_bars(
        self,
        venue: Venue,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        kind: PriceKind = PriceKind.TRADE,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        """Bars as a DataFrame indexed by UTC ``ts`` (ascending). Empty frame if none.

        ``as_of`` keeps only bars that had *closed* by that instant (``ts + interval <=
        as_of``). Price bars are public the moment they close, so that — not the time we
        happened to download them — is the honest point-in-time boundary. (Revisable
        data such as earnings estimates and news use ``observed_at`` instead.)
        """
        sql = "SELECT ts, open, high, low, close, volume_base, volume_quote, observed_at FROM bars WHERE venue=? AND symbol=? AND interval=? AND kind=?"
        args: list[object] = [venue.value, symbol, interval.value, kind.value]
        if start is not None:
            sql += " AND ts >= ?"
            args.append(to_epoch_ms(start))
        if end is not None:
            sql += " AND ts < ?"
            args.append(to_epoch_ms(end))
        if as_of is not None:
            sql += " AND ts + ? <= ?"
            args.extend([interval.seconds * 1000, to_epoch_ms(as_of)])
        sql += " ORDER BY ts"
        df = pd.read_sql_query(sql, self._conn, params=args)
        if df.empty:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume_base", "volume_quote", "observed_at"],
                index=pd.DatetimeIndex([], tz="UTC", name="ts"),
            )
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df["observed_at"] = pd.to_datetime(df["observed_at"], unit="ms", utc=True)
        return df.set_index("ts")

    def bar_coverage(
        self, venue: Venue, symbol: str, interval: Interval, *, kind: PriceKind = PriceKind.TRADE
    ) -> tuple[datetime, datetime, int] | None:
        row = self._conn.execute(
            "SELECT MIN(ts), MAX(ts), COUNT(*) FROM bars WHERE venue=? AND symbol=? AND interval=? AND kind=?",
            (venue.value, symbol, interval.value, kind.value),
        ).fetchone()
        if not row or row[2] == 0:
            return None
        return from_epoch_ms(row[0]), from_epoch_ms(row[1]), int(row[2])

    def bar_gaps(
        self, venue: Venue, symbol: str, interval: Interval, *, kind: PriceKind = PriceKind.TRADE
    ) -> list[tuple[datetime, datetime, int]]:
        """(gap_start_ts_exclusive, gap_end_ts_exclusive, missing_count) for 24/7 series."""
        ts_list = [
            r[0]
            for r in self._conn.execute(
                "SELECT ts FROM bars WHERE venue=? AND symbol=? AND interval=? AND kind=? ORDER BY ts",
                (venue.value, symbol, interval.value, kind.value),
            )
        ]
        step = interval.seconds * 1000
        gaps = []
        for prev, cur in zip(ts_list, ts_list[1:], strict=False):
            if cur - prev > step:
                gaps.append((from_epoch_ms(prev), from_epoch_ms(cur), (cur - prev) // step - 1))
        return gaps

    # -------------------------------------------------------------- instruments

    def upsert_instruments(self, instruments: Iterable[Instrument]) -> int:
        rows = [
            (i.venue.value, i.symbol, i.model_dump_json(), to_epoch_ms(i.observed_at)) for i in instruments
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO instruments (venue, symbol, payload, observed_at) VALUES (?,?,?,?)
                ON CONFLICT (venue, symbol) DO UPDATE SET
                    payload=excluded.payload, observed_at=MIN(instruments.observed_at, excluded.observed_at)
                """,
                rows,
            )
        return len(rows)

    def list_instruments(self, venue: Venue | None = None, *, tokenized_only: bool = False) -> list[Instrument]:
        sql = "SELECT payload FROM instruments"
        args: list[object] = []
        if venue is not None:
            sql += " WHERE venue=?"
            args.append(venue.value)
        out = [Instrument.model_validate_json(r[0]) for r in self._conn.execute(sql, args)]
        if tokenized_only:
            out = [i for i in out if i.is_tokenized_stock]
        return sorted(out, key=lambda i: (i.venue.value, i.symbol))

    # -------------------------------------------------------------- order books

    def insert_orderbook(self, snap: OrderBookSnapshot) -> int:
        m = snapshot_metrics(snap)
        levels = json.dumps(
            {
                "bids": [[lv.price, lv.size] for lv in snap.bids],
                "asks": [[lv.price, lv.size] for lv in snap.asks],
            },
            separators=(",", ":"),
        )
        cols = ["venue", "symbol", "ts", "observed_at", "best_bid", "best_ask", "mid", "spread_bps",
                "n_bids", "n_asks", "bid_notional_total", "ask_notional_total", *_DEPTH_COLS, "levels"]
        vals = [snap.venue.value, snap.symbol, to_epoch_ms(snap.ts), to_epoch_ms(snap.observed_at),
                m["best_bid"], m["best_ask"], m["mid"], m["spread_bps"], m["n_bids"], m["n_asks"],
                m["bid_notional_total"], m["ask_notional_total"], *[m[c] for c in _DEPTH_COLS], levels]
        with self._conn:
            cur = self._conn.execute(
                f"INSERT INTO orderbook_snapshots ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals
            )
        return int(cur.lastrowid)

    def get_orderbook_metrics(
        self,
        venue: Venue,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        as_of: datetime | None = None,
    ) -> pd.DataFrame:
        sql = f"SELECT ts, observed_at, best_bid, best_ask, mid, spread_bps, n_bids, n_asks, bid_notional_total, ask_notional_total, {', '.join(_DEPTH_COLS)} FROM orderbook_snapshots WHERE venue=? AND symbol=?"
        args: list[object] = [venue.value, symbol]
        if start is not None:
            sql += " AND ts >= ?"
            args.append(to_epoch_ms(start))
        if end is not None:
            sql += " AND ts < ?"
            args.append(to_epoch_ms(end))
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY ts"
        df = pd.read_sql_query(sql, self._conn, params=args)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df["observed_at"] = pd.to_datetime(df["observed_at"], unit="ms", utc=True)
        return df.set_index("ts")

    def get_orderbook_snapshot(self, snapshot_id: int) -> OrderBookSnapshot | None:
        row = self._conn.execute(
            "SELECT venue, symbol, ts, observed_at, levels FROM orderbook_snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return None
        lv = json.loads(row[4])
        return OrderBookSnapshot(
            venue=Venue(row[0]), symbol=row[1], ts=from_epoch_ms(row[2]), observed_at=from_epoch_ms(row[3]),
            bids=tuple(OrderBookLevel(price=p, size=s) for p, s in lv["bids"]),
            asks=tuple(OrderBookLevel(price=p, size=s) for p, s in lv["asks"]),
        )

    def latest_orderbook(self, venue: Venue, symbol: str) -> OrderBookSnapshot | None:
        row = self._conn.execute(
            "SELECT id FROM orderbook_snapshots WHERE venue=? AND symbol=? ORDER BY ts DESC LIMIT 1",
            (venue.value, symbol),
        ).fetchone()
        return None if row is None else self.get_orderbook_snapshot(int(row[0]))

    # ------------------------------------------------------------------ funding

    def upsert_funding(self, rates: Iterable[FundingRate]) -> int:
        rows = [(f.venue.value, f.symbol, to_epoch_ms(f.ts), f.rate, f.interval_hours, to_epoch_ms(f.observed_at)) for f in rates]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO funding (venue, symbol, ts, rate, interval_hours, observed_at) VALUES (?,?,?,?,?,?)
                ON CONFLICT (venue, symbol, ts) DO UPDATE SET rate=excluded.rate,
                    interval_hours=COALESCE(excluded.interval_hours, funding.interval_hours),
                    observed_at=MIN(funding.observed_at, excluded.observed_at)
                """,
                rows,
            )
        return len(rows)

    def get_funding(
        self, venue: Venue, symbol: str, start: datetime | None = None, end: datetime | None = None, *, as_of: datetime | None = None
    ) -> pd.DataFrame:
        sql = "SELECT ts, rate, interval_hours, observed_at FROM funding WHERE venue=? AND symbol=?"
        args: list[object] = [venue.value, symbol]
        if start is not None:
            sql += " AND ts >= ?"
            args.append(to_epoch_ms(start))
        if end is not None:
            sql += " AND ts < ?"
            args.append(to_epoch_ms(end))
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY ts"
        df = pd.read_sql_query(sql, self._conn, params=args)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df["observed_at"] = pd.to_datetime(df["observed_at"], unit="ms", utc=True)
        return df.set_index("ts")

    # ------------------------------------------------------------------ tickers

    def insert_tickers(self, tickers: Iterable[Ticker]) -> int:
        rows = [
            (t.venue.value, t.symbol, to_epoch_ms(t.ts), t.last, t.bid, t.ask, t.bid_size, t.ask_size, t.index_price,
             t.mark_price, t.funding_rate, t.open_interest, t.volume_24h_quote, to_epoch_ms(t.observed_at))
            for t in tickers
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO tickers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
        return len(rows)

    # ----------------------------------------------------------------- earnings

    def upsert_earnings(self, events: Iterable[EarningsEvent]) -> int:
        rows = [
            (e.ticker, to_epoch_ms(e.report_date), e.source, e.timing, e.eps_estimate, e.eps_actual, e.surprise_pct,
             e.fiscal_quarter_end, to_epoch_ms(e.observed_at))
            for e in events
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO earnings VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT (ticker, report_date, source) DO UPDATE SET
                    timing=COALESCE(excluded.timing, earnings.timing),
                    eps_estimate=COALESCE(excluded.eps_estimate, earnings.eps_estimate),
                    eps_actual=COALESCE(excluded.eps_actual, earnings.eps_actual),
                    surprise_pct=COALESCE(excluded.surprise_pct, earnings.surprise_pct),
                    fiscal_quarter_end=COALESCE(excluded.fiscal_quarter_end, earnings.fiscal_quarter_end),
                    observed_at=MIN(earnings.observed_at, excluded.observed_at)
                """,
                rows,
            )
        return len(rows)

    def get_earnings(self, ticker: str, *, as_of: datetime | None = None) -> list[EarningsEvent]:
        sql = "SELECT ticker, report_date, source, timing, eps_estimate, eps_actual, surprise_pct, fiscal_quarter_end, observed_at FROM earnings WHERE ticker=?"
        args: list[object] = [ticker]
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY report_date"
        return [
            EarningsEvent(
                ticker=r[0], report_date=from_epoch_ms(r[1]), source=r[2], timing=r[3], eps_estimate=r[4],
                eps_actual=r[5], surprise_pct=r[6], fiscal_quarter_end=r[7], observed_at=from_epoch_ms(r[8]),
            )
            for r in self._conn.execute(sql, args)
        ]

    # -------------------------------------------------------------------- macro

    def upsert_macro(self, releases: Iterable[MacroRelease]) -> int:
        rows = [(m.series_id, to_epoch_ms(m.release_ts), m.name, m.value, m.period, m.source, to_epoch_ms(m.observed_at)) for m in releases]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO macro VALUES (?,?,?,?,?,?,?)
                ON CONFLICT (series_id, release_ts) DO UPDATE SET
                    value=COALESCE(excluded.value, macro.value), period=COALESCE(excluded.period, macro.period),
                    observed_at=MIN(macro.observed_at, excluded.observed_at)
                """,
                rows,
            )
        return len(rows)

    def get_macro(self, start: datetime, end: datetime, *, series: Sequence[str] | None = None, as_of: datetime | None = None) -> list[MacroRelease]:
        sql = "SELECT series_id, release_ts, name, value, period, source, observed_at FROM macro WHERE release_ts >= ? AND release_ts < ?"
        args: list[object] = [to_epoch_ms(start), to_epoch_ms(end)]
        if series:
            sql += f" AND series_id IN ({','.join('?' * len(series))})"
            args.extend(series)
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY release_ts"
        return [
            MacroRelease(series_id=r[0], release_ts=from_epoch_ms(r[1]), name=r[2], value=r[3], period=r[4], source=r[5], observed_at=from_epoch_ms(r[6]))
            for r in self._conn.execute(sql, args)
        ]

    # --------------------------------------------------------------------- news

    # ------------------------------------------------------------------ filings

    def upsert_filings(self, filings: Iterable[Filing]) -> int:
        rows = [
            (f.ticker, f.accession, f.cik, f.form, to_epoch_ms(f.accepted_at), to_epoch_ms(f.filed_date), f.description, f.items, f.source, to_epoch_ms(f.observed_at))
            for f in filings
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """INSERT INTO filings VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (ticker, accession) DO UPDATE SET description=COALESCE(excluded.description, filings.description),
                   items=COALESCE(excluded.items, filings.items), observed_at=MIN(filings.observed_at, excluded.observed_at)""",
                rows,
            )
        return len(rows)

    def get_filings(self, ticker: str, *, start: datetime | None = None, end: datetime | None = None, as_of: datetime | None = None) -> list[Filing]:
        sql = "SELECT ticker, accession, cik, form, accepted_at, filed_date, description, items, source, observed_at FROM filings WHERE ticker=?"
        args: list[object] = [ticker]
        if start is not None:
            sql += " AND accepted_at >= ?"
            args.append(to_epoch_ms(start))
        if end is not None:
            sql += " AND accepted_at < ?"
            args.append(to_epoch_ms(end))
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY accepted_at"
        return [
            Filing(ticker=r[0], accession=r[1], cik=r[2], form=r[3], accepted_at=from_epoch_ms(r[4]), filed_date=from_epoch_ms(r[5]),
                   description=r[6], items=r[7], source=r[8], observed_at=from_epoch_ms(r[9]))
            for r in self._conn.execute(sql, args)
        ]

    def upsert_news(self, items: Iterable[NewsItem]) -> int:
        rows = [(n.source, n.id, to_epoch_ms(n.published_at), n.title, n.link, n.summary, json.dumps(list(n.tickers)), to_epoch_ms(n.observed_at)) for n in items]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany("INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def get_news(self, start: datetime, end: datetime, *, ticker: str | None = None, as_of: datetime | None = None) -> list[NewsItem]:
        sql = "SELECT source, id, published_at, title, link, summary, tickers, observed_at FROM news WHERE published_at >= ? AND published_at < ?"
        args: list[object] = [to_epoch_ms(start), to_epoch_ms(end)]
        if as_of is not None:
            sql += " AND observed_at <= ?"
            args.append(to_epoch_ms(as_of))
        sql += " ORDER BY published_at"
        out = []
        for r in self._conn.execute(sql, args):
            tickers = tuple(json.loads(r[6]))
            if ticker is not None and ticker not in tickers:
                continue
            out.append(NewsItem(source=r[0], id=r[1], published_at=from_epoch_ms(r[2]), title=r[3], link=r[4], summary=r[5], tickers=tickers, observed_at=from_epoch_ms(r[7])))
        return out

    # ----------------------------------------------------------------- sync log

    def log_sync(
        self, task: str, *, venue: Venue | None = None, symbol: str | None = None, interval: Interval | None = None,
        kind: PriceKind | None = None, range_start: datetime | None = None, range_end: datetime | None = None,
        rows: int = 0, started_at: datetime, finished_at: datetime, note: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO sync_log (task, venue, symbol, interval, kind, range_start, range_end, rows, started_at, finished_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task, venue.value if venue else None, symbol, interval.value if interval else None, kind.value if kind else None,
                 _ms(range_start), _ms(range_end), rows, to_epoch_ms(started_at), to_epoch_ms(finished_at), note),
            )

    def last_sync(self, task: str, *, venue: Venue | None = None, symbol: str | None = None) -> datetime | None:
        sql = "SELECT MAX(finished_at) FROM sync_log WHERE task=?"
        args: list[object] = [task]
        if venue is not None:
            sql += " AND venue=?"
            args.append(venue.value)
        if symbol is not None:
            sql += " AND symbol=?"
            args.append(symbol)
        row = self._conn.execute(sql, args).fetchone()
        return None if not row or row[0] is None else from_epoch_ms(row[0])

    # ---------------------------------------------------------------- utilities

    def prune_orderbooks_older_than(self, cutoff: datetime) -> int:
        with self._conn:
            cur = self._conn.execute("DELETE FROM orderbook_snapshots WHERE ts < ?", (to_epoch_ms(ensure_utc(cutoff)),))
        return cur.rowcount

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")

    @staticmethod
    def expected_bar_count(start: datetime, end: datetime, interval: Interval) -> int:
        return max(0, int((ensure_utc(end) - ensure_utc(start)) / timedelta(seconds=interval.seconds)))
