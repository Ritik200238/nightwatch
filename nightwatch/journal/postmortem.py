"""What actually happened, written down in a sentence, and shown again next time.

Calibration answers "are the numbers honest" across thousands of forecasts. It cannot
answer "what happened to *me* last time I did this", which is the question a trader
actually asks. So when a journaled forecast matures, we classify the outcome against the
distribution that was stated beforehand, write one plain sentence about it, and file it
so a future ticket in similar conditions can show it.

Three rules keep this from becoming horoscope:

* **Nothing is inferred.** The sentence only contains numbers already in the journal: the
  quantiles that were stated, the realised return, the worst point inside the window, and
  the size the desk recommended.
* **One episode is not evidence.** A lesson is labelled as a single past event, and the
  interface says so. The cohort statistics remain the thing you size against.
* **Point in time.** A lesson can only be shown by a ticket whose as-of is later than the
  moment the lesson's outcome became known, so a replay can never read its own future.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from nightwatch.time_utils import ensure_utc, from_epoch_ms, to_epoch_ms, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
    forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(id),
    written_at INTEGER NOT NULL,
    matured_at INTEGER NOT NULL,
    as_of INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    kind TEXT NOT NULL,
    bucket TEXT,
    regime_label TEXT,
    horizon_h REAL NOT NULL,
    classification TEXT NOT NULL,
    breached_low INTEGER NOT NULL,
    breached_high INTEGER NOT NULL,
    touched_stress INTEGER NOT NULL,
    recovered INTEGER NOT NULL,
    ret_pct REAL, p5 REAL, p50 REAL, p95 REAL, mae_pct REAL,
    verdict TEXT, requested_notional REAL, recommended_notional REAL,
    size_effect_quote REAL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_lookup ON lessons (ticker, matured_at);
"""


class Classification(str, Enum):
    """Where the realised return fell against the distribution stated beforehand."""

    WORSE_THAN_STRESS = "worse_than_stress"  # below the 5th percentile we size against
    BAD_TAIL = "bad_tail"  # between p5 and p25
    AS_EXPECTED = "as_expected"  # the middle half
    GOOD_TAIL = "good_tail"  # between p75 and p95
    BETTER_THAN_FORECAST = "better_than_forecast"  # above the 95th percentile
    NO_DISTRIBUTION = "no_distribution"  # the engine refused; only the outcome is known


@dataclass(frozen=True)
class Lesson:
    forecast_id: int
    as_of: datetime
    matured_at: datetime
    ticker: str
    side: str
    kind: str
    bucket: str | None
    regime_label: str | None
    horizon_h: float
    classification: Classification
    breached_low: bool
    breached_high: bool
    touched_stress: bool
    recovered: bool
    ret_pct: float
    p5: float | None
    p50: float | None
    p95: float | None
    mae_pct: float | None
    verdict: str | None
    requested_notional: float | None
    recommended_notional: float | None
    size_effect_quote: float | None
    text: str

    @property
    def notable(self) -> bool:
        """Worth showing a trader. An outcome in the middle of the band taught nothing."""
        return self.breached_low or self.breached_high or self.touched_stress or bool(self.size_effect_quote)


def classify(ret_pct: float, p5: float | None, p25: float | None, p75: float | None, p95: float | None) -> Classification:
    if p5 is None or p95 is None:
        return Classification.NO_DISTRIBUTION
    if ret_pct < p5:
        return Classification.WORSE_THAN_STRESS
    if ret_pct > p95:
        return Classification.BETTER_THAN_FORECAST
    if p25 is not None and ret_pct < p25:
        return Classification.BAD_TAIL
    if p75 is not None and ret_pct > p75:
        return Classification.GOOD_TAIL
    return Classification.AS_EXPECTED


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def compose(row: pd.Series, cls: Classification, *, touched_stress: bool, recovered: bool, size_effect: float | None) -> str:
    """One sentence, built only from numbers the journal already holds."""
    at = ensure_utc(row["as_of"])
    when = f"{at.day} {at:%b}"  # "%-d" is a glibc extension and dies on Windows
    side = str(row["side"]).lower()
    head = f"{row['ticker']} {side} over {row['horizon_h']:.0f}h from {when}"
    ret = float(row["ret_pct"])

    if cls is Classification.NO_DISTRIBUTION:
        body = f"the engine refused to forecast (too few similar moments). It closed {_pct(ret)}."
    elif cls is Classification.WORSE_THAN_STRESS:
        body = f"it closed {_pct(ret)}, below the {_pct(row.get('p5'))} we sized against."
    elif cls is Classification.BETTER_THAN_FORECAST:
        body = f"it closed {_pct(ret)}, above the {_pct(row.get('p95'))} upper bound."
    else:
        body = f"it closed {_pct(ret)}, inside the {_pct(row.get('p5'))} to {_pct(row.get('p95'))} band."

    extra = ""
    if touched_stress and recovered:
        extra = f" It went through that level intraday, worst point {_pct(row.get('mae_pct'))}, then came back."
    elif touched_stress:
        extra = f" Worst point inside the window {_pct(row.get('mae_pct'))}."

    money = ""
    if size_effect is not None and abs(size_effect) >= 1:
        verb = "avoided" if size_effect > 0 else "cost"
        money = f" The desk cut the size from {row['notional']:,.0f} to {row['recommended_notional']:,.0f}, which {verb} about {abs(size_effect):,.0f} USDT."
    return head + ": " + body + extra + money


def build(row: pd.Series, payload: dict) -> Lesson:
    """Turn one matured forecast row into a lesson. ``payload`` is the journal's stored blob."""
    ret = float(row["ret_pct"])
    p5, p25, p50, p75, p95 = (None if pd.isna(row.get(q)) else float(row.get(q)) for q in ("p5", "p25", "p50", "p75", "p95"))
    mae = None if pd.isna(row.get("mae_pct")) else float(row["mae_pct"])
    cls = classify(ret, p5, p25, p75, p95)
    # Did the position trade through the level we sized against at any point in the window?
    touched = bool(p5 is not None and mae is not None and mae < p5)
    recovered = bool(touched and ret >= (p5 or 0.0))

    requested = None if pd.isna(row.get("notional")) else float(row["notional"])
    recommended = None if pd.isna(row.get("recommended_notional")) else float(row["recommended_notional"])
    # What the size advice was worth, in money: the part of the position the desk removed,
    # multiplied by the move it missed. Positive means the cut avoided a loss.
    size_effect = None
    if requested is not None and recommended is not None and recommended < requested:
        size_effect = (requested - recommended) * (-ret / 100.0)

    labels = payload.get("labels") or {}
    return Lesson(
        forecast_id=int(row["id"]), as_of=ensure_utc(row["as_of"]), matured_at=ensure_utc(row["matured_at"]),
        ticker=str(row["ticker"]), side=str(row["side"]), kind=str(row["kind"]),
        bucket=labels.get("bucket"), regime_label=labels.get("regime_label"), horizon_h=float(row["horizon_h"]),
        classification=cls, breached_low=bool(p5 is not None and ret < p5), breached_high=bool(p95 is not None and ret > p95),
        touched_stress=touched, recovered=recovered, ret_pct=ret, p5=p5, p50=p50, p95=p95, mae_pct=mae,
        verdict=None if pd.isna(row.get("verdict")) else str(row["verdict"]),
        requested_notional=requested, recommended_notional=recommended, size_effect_quote=size_effect,
        text=compose(row, cls, touched_stress=touched, recovered=recovered, size_effect=size_effect),
    )


class LessonBook:
    """Storage and point-in-time retrieval of lessons."""

    def __init__(self, journal):  # noqa: ANN001 - nightwatch.journal.journal.Journal
        self.journal = journal
        self._conn = journal._conn
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ writing

    def write_pending(self, *, limit: int | None = None) -> int:
        """Write a lesson for every matured forecast that does not have one yet."""
        sql = """SELECT f.id, f.kind, f.ticker, f.side, f.notional, f.as_of, f.horizon_h, f.p5, f.p25, f.p50, f.p75, f.p95,
                        f.verdict, f.recommended_notional, f.payload, o.ret_pct, o.mae_pct, o.matured_at
                 FROM forecasts f JOIN forecast_outcomes o ON o.forecast_id = f.id
                 LEFT JOIN lessons l ON l.forecast_id = f.id
                 WHERE l.forecast_id IS NULL ORDER BY o.matured_at"""
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self._conn.execute(sql).fetchall()
        cols = [d[0] for d in self._conn.execute(sql).description]
        written = 0
        for raw in rows:
            row = pd.Series(dict(zip(cols, raw, strict=True)))
            for col in ("as_of", "matured_at"):
                row[col] = from_epoch_ms(int(row[col]))
            try:
                payload = json.loads(row["payload"]) if row["payload"] else {}
            except json.JSONDecodeError:
                payload = {}
            lesson = build(row, payload)
            self._insert(lesson)
            written += 1
        return written

    def _insert(self, x: Lesson) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO lessons (forecast_id, written_at, matured_at, as_of, ticker, side, kind, bucket, regime_label,
                   horizon_h, classification, breached_low, breached_high, touched_stress, recovered, ret_pct, p5, p50, p95, mae_pct,
                   verdict, requested_notional, recommended_notional, size_effect_quote, text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    x.forecast_id, to_epoch_ms(utc_now()), to_epoch_ms(x.matured_at), to_epoch_ms(x.as_of), x.ticker, x.side, x.kind,
                    x.bucket, x.regime_label, x.horizon_h, x.classification.value, int(x.breached_low), int(x.breached_high),
                    int(x.touched_stress), int(x.recovered), x.ret_pct, x.p5, x.p50, x.p95, x.mae_pct, x.verdict,
                    x.requested_notional, x.recommended_notional, x.size_effect_quote, x.text,
                ),
            )

    # ------------------------------------------------------------------ reading

    def recall(self, *, ticker: str, bucket: str | None = None, regime_label: str | None = None, as_of: datetime | None = None, limit: int = 3) -> list[Lesson]:
        """The most relevant past lessons for a ticket being analysed now.

        Relevance, in order: the same token beats another token; a matching time-of-week
        bucket and regime beat a mismatch; a lesson that taught something (a breach, a
        stress level touched, a size cut worth money) beats one that did not; and newer
        beats older. Only lessons whose outcome was already known at ``as_of`` qualify.
        """
        cutoff = to_epoch_ms(ensure_utc(as_of)) if as_of else to_epoch_ms(utc_now())
        rows = self._conn.execute(
            """SELECT *,
                      (ticker = ?) * 4 + (bucket IS NOT NULL AND bucket = ?) * 2 + (regime_label IS NOT NULL AND regime_label = ?) * 1
                        + (breached_low OR breached_high) * 3 + touched_stress * 2 + (size_effect_quote IS NOT NULL) * 2 AS score
               FROM lessons WHERE matured_at < ? AND (ticker = ? OR bucket = ?)
               ORDER BY score DESC, matured_at DESC LIMIT ?""",
            (ticker, bucket, regime_label, cutoff, ticker, bucket, int(limit)),
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM lessons LIMIT 0").description]
        out: list[Lesson] = []
        for raw in rows:
            d = dict(zip(cols, raw[: len(cols)], strict=True))
            out.append(
                Lesson(
                    forecast_id=d["forecast_id"], as_of=from_epoch_ms(d["as_of"]), matured_at=from_epoch_ms(d["matured_at"]),
                    ticker=d["ticker"], side=d["side"], kind=d["kind"], bucket=d["bucket"], regime_label=d["regime_label"],
                    horizon_h=d["horizon_h"], classification=Classification(d["classification"]),
                    breached_low=bool(d["breached_low"]), breached_high=bool(d["breached_high"]),
                    touched_stress=bool(d["touched_stress"]), recovered=bool(d["recovered"]), ret_pct=d["ret_pct"],
                    p5=d["p5"], p50=d["p50"], p95=d["p95"], mae_pct=d["mae_pct"], verdict=d["verdict"],
                    requested_notional=d["requested_notional"], recommended_notional=d["recommended_notional"],
                    size_effect_quote=d["size_effect_quote"], text=d["text"],
                )
            )
        return out

    def summary(self, *, ticker: str | None = None) -> dict[str, int]:
        """How the outcomes have been classified so far, for the interface to show."""
        sql = "SELECT classification, COUNT(*) FROM lessons"
        args: tuple = ()
        if ticker:
            sql += " WHERE ticker = ?"
            args = (ticker,)
        sql += " GROUP BY classification"
        return {k: int(v) for k, v in self._conn.execute(sql, args).fetchall()}


def mature_and_learn(journal, *, spot_symbol_for: dict[str, str], now: datetime | None = None) -> tuple[int, int]:  # noqa: ANN001
    """Score what has matured, then write the lessons. Returns (matured, lessons)."""
    matured = journal.mature(spot_symbol_for=spot_symbol_for, now=now)
    return matured, LessonBook(journal).write_pending()
