"""Journal: every forecast is written down, then judged by what actually happened.

Two tables:

* ``forecasts`` – one row per analysed ticket (or replay point): what was predicted
  for the primary horizon (p5/p25/p50/p75/p95, expected shortfall, verdict, size) and
  the exact inputs (snapshot hash) so the prediction is auditable.
* ``forecast_outcomes`` – filled in once the horizon has passed: the realised return,
  worst/best excursion and the maximum basis dislocation over the window.

Nothing here can be edited after the fact; maturation only *adds* outcome rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.analog.outcomes import compute_match_outcomes
from nightwatch.data.models import Interval, Venue
from nightwatch.data.store import Store
from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    kind TEXT NOT NULL,               -- 'ticket' | 'replay'
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    notional REAL NOT NULL,
    as_of INTEGER NOT NULL,
    bar_ts INTEGER NOT NULL,
    horizon_h REAL NOT NULL,
    horizon_end INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    snapshot_hash TEXT NOT NULL,
    analog_n INTEGER,
    analog_scope TEXT,
    p5 REAL, p25 REAL, p50 REAL, p75 REAL, p95 REAL,
    es5 REAL,
    mc_p5 REAL, mc_p95 REAL,
    verdict TEXT,
    recommended_notional REAL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS forecasts_ticker_asof ON forecasts (ticker, as_of);

CREATE TABLE IF NOT EXISTS forecast_outcomes (
    forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(id),
    matured_at INTEGER NOT NULL,
    exit_ts INTEGER NOT NULL,
    exit_price REAL NOT NULL,
    ret_pct REAL NOT NULL,          -- signed by side (positive = profit)
    mfe_pct REAL, mae_pct REAL,
    max_abs_basis_bps REAL
);

CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY,
    forecast_id INTEGER REFERENCES forecasts(id),
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    closed_at INTEGER,
    entry_price REAL, exit_price REAL,
    notional REAL NOT NULL,
    realized_pnl_quote REAL,
    note TEXT
);
"""


@dataclass(frozen=True)
class ForecastRow:
    id: int
    created_at: datetime
    kind: str
    ticker: str
    side: str
    notional: float
    as_of: datetime
    bar_ts: datetime
    horizon_h: float
    horizon_end: datetime
    entry_price: float
    snapshot_hash: str
    analog_n: int | None
    analog_scope: str | None
    p5: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p95: float | None
    es5: float | None
    mc_p5: float | None
    mc_p95: float | None
    verdict: str | None
    recommended_notional: float | None


class Journal:
    def __init__(self, store: Store):
        self.store = store
        self._conn = store._conn
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ writes

    def record_forecast(
        self,
        *,
        kind: str,
        ticker: str,
        side: str,
        notional: float,
        as_of: datetime,
        bar_ts: datetime,
        horizon_h: float,
        entry_price: float,
        snapshot_hash: str,
        analog_n: int | None,
        analog_scope: str | None,
        quantiles: dict[str, float | None],
        es5: float | None,
        mc_p5: float | None,
        mc_p95: float | None,
        verdict: str | None,
        recommended_notional: float | None,
        payload: dict,
    ) -> int:
        as_of = ensure_utc(as_of)
        horizon_end = as_of + timedelta(hours=horizon_h)
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO forecasts (created_at, kind, ticker, side, notional, as_of, bar_ts, horizon_h, horizon_end, entry_price,
                   snapshot_hash, analog_n, analog_scope, p5, p25, p50, p75, p95, es5, mc_p5, mc_p95, verdict, recommended_notional, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    to_epoch_ms(utc_now()), kind, ticker, side, notional, to_epoch_ms(as_of), to_epoch_ms(bar_ts), horizon_h, to_epoch_ms(horizon_end), entry_price,
                    snapshot_hash, analog_n, analog_scope, quantiles.get("p5"), quantiles.get("p25"), quantiles.get("p50"), quantiles.get("p75"), quantiles.get("p95"),
                    es5, mc_p5, mc_p95, verdict, recommended_notional, json.dumps(payload, default=str, separators=(",", ":")),
                ),
            )
        return int(cur.lastrowid)

    def log_trade(self, *, forecast_id: int | None, ticker: str, side: str, opened_at: datetime, notional: float, entry_price: float | None, note: str | None = None) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO trade_log (forecast_id, ticker, side, opened_at, notional, entry_price, note) VALUES (?,?,?,?,?,?,?)",
                (forecast_id, ticker, side, to_epoch_ms(opened_at), notional, entry_price, note),
            )
        return int(cur.lastrowid)

    def close_trade(self, trade_id: int, *, closed_at: datetime, exit_price: float) -> None:
        row = self._conn.execute("SELECT side, notional, entry_price FROM trade_log WHERE id=?", (trade_id,)).fetchone()
        if row is None:
            raise KeyError(trade_id)
        side, notional, entry = row
        sign = 1.0 if side == "long" else -1.0
        pnl = sign * (exit_price / entry - 1.0) * notional if entry else None
        with self._conn:
            self._conn.execute("UPDATE trade_log SET closed_at=?, exit_price=?, realized_pnl_quote=? WHERE id=?", (to_epoch_ms(closed_at), exit_price, pnl, trade_id))

    def recent_losing_exits(self, *, since: datetime) -> tuple[datetime, ...]:
        rows = self._conn.execute(
            "SELECT closed_at FROM trade_log WHERE closed_at IS NOT NULL AND realized_pnl_quote < 0 AND closed_at >= ? ORDER BY closed_at", (to_epoch_ms(since),)
        ).fetchall()
        return tuple(from_epoch_ms(r[0]) for r in rows)

    # ------------------------------------------------------------------- reads

    def forecasts(self, *, ticker: str | None = None, kind: str | None = None, matured_only: bool = False) -> pd.DataFrame:
        sql = """SELECT f.*, o.exit_ts, o.exit_price, o.ret_pct, o.mfe_pct, o.mae_pct, o.max_abs_basis_bps, o.matured_at
                 FROM forecasts f LEFT JOIN forecast_outcomes o ON o.forecast_id = f.id WHERE 1=1"""
        args: list[object] = []
        if ticker:
            sql += " AND f.ticker=?"
            args.append(ticker)
        if kind:
            sql += " AND f.kind=?"
            args.append(kind)
        if matured_only:
            sql += " AND o.forecast_id IS NOT NULL"
        sql += " ORDER BY f.as_of"
        df = pd.read_sql_query(sql, self._conn, params=args)
        for col in ("created_at", "as_of", "bar_ts", "horizon_end", "exit_ts", "matured_at"):
            if col in df:
                df[col] = pd.to_datetime(df[col], unit="ms", utc=True)
        return df.drop(columns=["payload"], errors="ignore")

    # -------------------------------------------------------------- maturation

    def mature(self, *, spot_symbol_for: dict[str, str], now: datetime | None = None) -> int:
        """Fill outcomes for every forecast whose horizon has passed and whose bars exist."""
        now = ensure_utc(now or utc_now())
        rows = self._conn.execute(
            "SELECT f.id, f.ticker, f.side, f.as_of, f.horizon_h, f.horizon_end, f.entry_price FROM forecasts f LEFT JOIN forecast_outcomes o ON o.forecast_id=f.id WHERE o.forecast_id IS NULL AND f.horizon_end <= ?",
            (to_epoch_ms(now),),
        ).fetchall()
        n = 0
        for fid, ticker, side, as_of_ms, horizon_h, end_ms, entry in rows:
            symbol = spot_symbol_for.get(ticker)
            if symbol is None:
                continue
            as_of, end = from_epoch_ms(as_of_ms), from_epoch_ms(end_ms)
            bars = self.store.get_bars(Venue.BITGET_SPOT, symbol, Interval.H1, as_of - timedelta(hours=2), end + timedelta(hours=2))
            if bars.empty:
                continue
            # First completed bar at/after the horizon end.
            after = bars[bars.index >= pd.Timestamp(end).floor("1h")]
            if after.empty:
                continue
            exit_ts = after.index[0]
            exit_price = float(after["close"].iloc[0])
            window = bars[(bars.index > pd.Timestamp(as_of).floor("1h")) & (bars.index <= exit_ts)]
            sign = 1.0 if side == "long" else -1.0
            ret = sign * (exit_price / entry - 1.0) * 100.0
            mfe = mae = None
            if not window.empty:
                hi = float(window["high"].max()) / entry - 1.0
                lo = float(window["low"].min()) / entry - 1.0
                mfe, mae = (hi * 100.0, lo * 100.0) if sign > 0 else (-lo * 100.0, -hi * 100.0)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO forecast_outcomes (forecast_id, matured_at, exit_ts, exit_price, ret_pct, mfe_pct, mae_pct, max_abs_basis_bps) VALUES (?,?,?,?,?,?,?,?)",
                    (fid, to_epoch_ms(now), to_epoch_ms(exit_ts.to_pydatetime()), exit_price, ret, mfe, mae, None),
                )
            n += 1
        return n
