"""Nearest-neighbour search over historical market states.

Given the feature vector describing *now* and a matrix of the same features for every
past hour, return the most similar past moments as **distinct episodes**, with
distances that are comparable across queries.

Method
------
1. **Feature selection** – use the configured features that are present in the query;
   drop history rows with missing values in those features. Report both counts.
2. **Robust scaling** – centre by median and scale by MAD (1.4826·MAD ≈ σ for normal
   data). Medians/MADs are fit on the history only, so the query is measured against
   the past, never the other way round.
3. **Whitening** – correlated features (24h vs 168h vol, basis level vs z-score) would
   otherwise be double-counted. We whiten with the inverse Cholesky factor of a
   shrinkage covariance (Σ_shrunk = (1−λ)Σ + λ·diag(Σ)), which is Mahalanobis
   distance with numerical safety. Feature weights are applied after whitening as
   per-dimension multipliers.
4. **Hard filters** – optional same-bucket / same-ticker constraints; a minimum age so
   the query cannot match its own recent past (whose outcomes are not yet known).
5. **Episode de-duplication** – hours next to each other look alike; we walk candidates
   by distance and skip any within ``min_separation_h`` of an already-selected match, so
   *k* neighbours are *k* separate historical situations.
6. **Similarity** – ``exp(−d² / (2·σ_d²))`` where σ_d is the distance scale from the
   history's own nearest-neighbour distances, plus the percentile of each match's
   distance among all candidates. Both are reported; neither is hidden behind a score.
7. **Refusal** – if fewer than ``min_matches`` distinct episodes exist, the result says
   so explicitly instead of returning a thin, misleading sample.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from nightwatch.features.snapshot import FEATURE_COLUMNS

MAD_SCALE = 1.4826


@dataclass(frozen=True)
class AnalogConfig:
    features: tuple[str, ...] = FEATURE_COLUMNS
    weights: dict[str, float] = field(default_factory=dict)  # default 1.0 each
    k: int = 40
    min_matches: int = 15
    min_separation_h: int = 36
    min_age_h: int = 96  # exclude the most recent hours: their outcomes are incomplete
    same_bucket: bool = False
    same_ticker: bool = False
    shrinkage: float = 0.10
    whiten: bool = True


@dataclass(frozen=True)
class AnalogMatch:
    ts: datetime
    ticker: str
    distance: float
    similarity: float
    distance_percentile: float  # 0 = closest of all candidates, 100 = farthest
    bucket: str
    features: dict[str, float]


@dataclass(frozen=True)
class AnalogResult:
    ok: bool
    reason: str
    matches: list[AnalogMatch]
    features_used: tuple[str, ...]
    features_dropped: tuple[str, ...]
    n_history_rows: int
    n_candidates: int  # rows with complete features after hard filters
    n_distinct_available: int  # distinct episodes found before capping at k
    distance_scale: float
    query: dict[str, float]

    @property
    def n(self) -> int:
        return len(self.matches)


# ----------------------------------------------------------------------------- core


class AnalogEngine:
    def __init__(self, config: AnalogConfig | None = None):
        self.config = config or AnalogConfig()

    def search(
        self,
        history: pd.DataFrame,
        query: dict[str, float | None],
        *,
        query_ts: datetime,
        query_bucket: str | None = None,
        query_ticker: str | None = None,
    ) -> AnalogResult:
        cfg = self.config
        used = tuple(f for f in cfg.features if f in history.columns and query.get(f) is not None and not _isnan(query[f]))
        dropped = tuple(f for f in cfg.features if f not in used)
        if len(used) < 3:
            return self._refuse("fewer than 3 usable features in the query", history, used, dropped, query)

        hist = history.copy()
        if "bucket" not in hist.columns:
            hist["bucket"] = "unknown"
        if "ticker" not in hist.columns:
            hist["ticker"] = query_ticker or ""

        # Hard filters.
        age_cut = pd.Timestamp(query_ts) - pd.Timedelta(hours=cfg.min_age_h)
        hist = hist[hist.index <= age_cut]
        if cfg.same_bucket and query_bucket is not None:
            hist = hist[hist["bucket"] == query_bucket]
        if cfg.same_ticker and query_ticker is not None:
            hist = hist[hist["ticker"] == query_ticker]
        hist = hist.dropna(subset=list(used))
        n_candidates = len(hist)
        if n_candidates < cfg.min_matches:
            return self._refuse(f"only {n_candidates} candidate rows with complete features", history, used, dropped, query, n_candidates=n_candidates)

        X = hist[list(used)].to_numpy(dtype=float)

        # Features that do not vary in this history carry no information and would
        # explode the scaling; drop them and say so.
        med = np.median(X, axis=0)
        mad = np.median(np.abs(X - med), axis=0) * MAD_SCALE
        std = np.std(X, axis=0)
        keep = ~((mad <= 1e-12) & (std <= 1e-9))
        if not keep.all():
            constant = tuple(f for f, k in zip(used, keep, strict=True) if not k)
            used = tuple(f for f, k in zip(used, keep, strict=True) if k)
            dropped = dropped + tuple(f"{f} (constant in history)" for f in constant)
            X, med, mad, std = X[:, keep], med[keep], mad[keep], std[keep]
            if len(used) < 3:
                return self._refuse("fewer than 3 informative features in the history", history, used, dropped, query, n_candidates=n_candidates)
        q = np.array([float(query[f]) for f in used], dtype=float)

        # Robust scaling fit on history; where the MAD collapses (heavy zero mass) fall
        # back to the standard deviation so a rare feature is not scaled to infinity.
        scale_vec = np.where(mad <= 1e-12, std, mad)
        Z = (X - med) / scale_vec
        zq = (q - med) / scale_vec

        w = np.array([cfg.weights.get(f, 1.0) for f in used], dtype=float)
        if cfg.whiten and Z.shape[0] > Z.shape[1] * 5:
            L_inv = _whitener(Z, cfg.shrinkage)
            Zw = (Z @ L_inv.T) * w
            zqw = (zq @ L_inv.T) * w
        else:
            Zw, zqw = Z * w, zq * w

        d = np.sqrt(np.sum((Zw - zqw) ** 2, axis=1))
        scale = _distance_scale(Zw)

        order = np.argsort(d, kind="stable")
        chosen: list[int] = []
        chosen_ts: list[pd.Timestamp] = []
        sep = pd.Timedelta(hours=cfg.min_separation_h)
        n_distinct = 0
        for i in order:
            ts_i = hist.index[i]
            if any(abs(ts_i - t) < sep for t in chosen_ts):
                continue
            n_distinct += 1
            if len(chosen) < cfg.k:
                chosen.append(int(i))
                chosen_ts.append(ts_i)
        if len(chosen) < cfg.min_matches:
            return self._refuse(f"only {len(chosen)} distinct episodes (need {cfg.min_matches})", history, used, dropped, query, n_candidates=n_candidates, n_distinct=len(chosen))

        pct = _percentiles(d)
        matches = [
            AnalogMatch(
                ts=hist.index[i].to_pydatetime(),
                ticker=str(hist["ticker"].iloc[i]),
                distance=float(d[i]),
                similarity=float(np.exp(-(d[i] ** 2) / (2.0 * scale**2))) if scale > 0 else 0.0,
                distance_percentile=float(pct[i]),
                bucket=str(hist["bucket"].iloc[i]),
                features={f: float(X[i, j]) for j, f in enumerate(used)},
            )
            for i in chosen
        ]
        return AnalogResult(
            ok=True,
            reason="ok",
            matches=matches,
            features_used=used,
            features_dropped=dropped,
            n_history_rows=len(history),
            n_candidates=n_candidates,
            n_distinct_available=n_distinct,
            distance_scale=float(scale),
            query={f: float(query[f]) for f in used},
        )

    @staticmethod
    def _refuse(reason: str, history: pd.DataFrame, used, dropped, query, *, n_candidates: int = 0, n_distinct: int = 0) -> AnalogResult:  # noqa: ANN001
        return AnalogResult(
            ok=False, reason=reason, matches=[], features_used=tuple(used), features_dropped=tuple(dropped),
            n_history_rows=len(history), n_candidates=n_candidates, n_distinct_available=n_distinct,
            distance_scale=float("nan"), query={f: float(query[f]) for f in used if query.get(f) is not None},
        )


# -------------------------------------------------------------------------- helpers


def _isnan(v) -> bool:  # noqa: ANN001
    try:
        return bool(np.isnan(float(v)))
    except (TypeError, ValueError):
        return True


EIGEN_FLOOR = 1e-3  # relative to the largest eigenvalue


def _whitener(Z: np.ndarray, shrinkage: float) -> np.ndarray:
    """Symmetric whitening matrix W such that (Z @ W.T) has (approximately) identity
    covariance. Built from the eigen-decomposition of a shrinkage covariance with an
    eigenvalue floor, so near-collinear features cannot produce astronomical distances."""
    cov = np.atleast_2d(np.cov(Z, rowvar=False))
    diag = np.diag(np.diag(cov))
    shrunk = (1.0 - shrinkage) * cov + shrinkage * diag
    vals, vecs = np.linalg.eigh(shrunk)
    floor = max(vals.max(), 1e-12) * EIGEN_FLOOR
    vals = np.maximum(vals, floor)
    return vecs @ np.diag(1.0 / np.sqrt(vals)) @ vecs.T


def _distance_scale(Zw: np.ndarray, sample: int = 2000, seed: int = 7) -> float:
    """Typical nearest-neighbour distance inside the history (median over a sample)."""
    n = Zw.shape[0]
    if n < 3:
        return 1.0
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=min(sample, n), replace=False)
    S = Zw[idx]
    # Pairwise distances within the sample; ignore self (diagonal).
    sq = np.sum(S**2, axis=1)
    D2 = sq[:, None] + sq[None, :] - 2.0 * (S @ S.T)
    np.fill_diagonal(D2, np.inf)
    nn = np.sqrt(np.maximum(D2.min(axis=1), 0.0))
    med = float(np.median(nn))
    return med if med > 0 else 1.0


def _percentiles(d: np.ndarray) -> np.ndarray:
    ranks = np.argsort(np.argsort(d, kind="stable"), kind="stable")
    return ranks / max(1, len(d) - 1) * 100.0


def matches_frame(result: AnalogResult) -> pd.DataFrame:
    rows = [
        {"ts": m.ts, "ticker": m.ticker, "bucket": m.bucket, "distance": m.distance, "similarity": m.similarity, "distance_pct": m.distance_percentile, **m.features}
        for m in result.matches
    ]
    return pd.DataFrame(rows).set_index("ts") if rows else pd.DataFrame()


def pooled_history(frames: Sequence[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    """Stack per-ticker feature frames into one history with a ``ticker`` column."""
    parts = []
    for ticker, f in frames:
        g = f.copy()
        g["ticker"] = ticker
        parts.append(g)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts)
    return out.sort_index(kind="stable")


def default_lookback(query_ts: datetime, days: int = 400) -> datetime:
    return query_ts - timedelta(days=days)
