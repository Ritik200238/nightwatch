"""A coarse map of the states this token has been in, and what followed each one.

The analog engine answers "what happened after the forty moments most like now". This
answers the blunter question underneath it: "what kind of market is this, how long does
that kind usually last, and what does it tend to do next". It is a check on the fine
retrieval as much as a feature in its own right, because if the two disagree the trader
should know.

How it works, and why each choice:

* **Clusters, fitted on history only.** Hours are grouped by a handful of state
  descriptors with k-means. The fit uses only rows before the moment being described, so
  a regime label can never have been shaped by the future it is used to predict.
* **Standardised by median and absolute deviation**, not mean and variance, so one
  violent week cannot define the axes, and then clipped at four deviations before the
  fit. Without the clip a single freak hour is its own cluster: k-means minimises squared
  distance, so one point a thousand deviations out is worth more than a thousand ordinary
  hours. Clipping keeps the extreme hour in the map, in the group it belongs to, instead
  of letting it take a whole regime with it.
* **Named by their own statistics**, never by a story: a regime is described as what it
  measurably is (volatility percentile, basis, trend), not as "risk-off".
* **Judged by outcomes.** Each regime carries the distribution of what followed it, with
  its sample size. A regime with eleven observations is reported as such.
* **The flat share is reported, because the medians need it.** A tokenized US stock does
  not trade every hour, so a window can begin and end on the same last trade and return
  exactly zero. Roughly a sixth of them do, which is enough mass at zero to put the median
  there for every state. Printing "median 0.00%" and nothing else invites the reader to
  assume the table is broken; printing how often a window simply does not move says what
  is actually true about this market, and points at the p5 column as the useful one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# The state descriptors. Deliberately few: clusters in twenty dimensions are noise.
REGIME_FEATURES: tuple[str, ...] = ("vol_pctl_90d", "basis_index_z", "trend_sma_pct", "liq_ratio", "rv_24h")
DEFAULT_K = 5
MIN_ROWS_PER_FIT = 500
MIN_ROWS_PER_REGIME = 30
CLIP_DEVIATIONS = 4.0  # no single hour may own a cluster


@dataclass(frozen=True)
class Regime:
    id: int
    n: int
    share: float
    centre: dict[str, float]
    description: str
    persistence: float | None  # chance the next day is still this regime
    next_ret_median_pct: float | None
    next_ret_p5_pct: float | None
    next_ret_p95_pct: float | None
    n_outcomes: int
    flat_share: float | None = None  # windows that ended exactly where they started


@dataclass(frozen=True)
class RegimeMap:
    regimes: list[Regime] = field(default_factory=list)
    transitions: list[list[float]] = field(default_factory=list)  # row i -> chance of j next
    current: int | None = None
    horizon_h: int = 24
    n_fitted: int = 0
    note: str = ""

    def regime(self, rid: int | None) -> Regime | None:
        return next((r for r in self.regimes if r.id == rid), None)


def _standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre on the median, scale by the median absolute deviation."""
    med = np.nanmedian(x, axis=0)
    mad = np.nanmedian(np.abs(x - med), axis=0) * 1.4826
    mad = np.where(mad < 1e-9, 1.0, mad)
    return (x - med) / mad, med, mad


def _kmeans(x: np.ndarray, k: int, *, seed: int = 17, iters: int = 60) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means with k-means++ starts. Deterministic for a given seed.

    Written out rather than pulled in: it is forty lines, it keeps the dependency list
    short on a small box, and the seeding and stopping rule stay visible.
    """
    rng = np.random.default_rng(seed)
    n = len(x)
    centres = np.empty((k, x.shape[1]))
    centres[0] = x[rng.integers(n)]
    d2 = ((x - centres[0]) ** 2).sum(axis=1)
    for i in range(1, k):
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1 / n)
        centres[i] = x[rng.choice(n, p=probs)]
        d2 = np.minimum(d2, ((x - centres[i]) ** 2).sum(axis=1))

    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dist = ((x[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        new = dist.argmin(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for i in range(k):
            members = x[labels == i]
            if len(members):
                centres[i] = members.mean(axis=0)
    return labels, centres


def _describe(centre: dict[str, float]) -> str:
    """What this cluster measurably is. No narrative."""
    bits = []
    vol = centre.get("vol_pctl_90d")
    if vol is not None and not np.isnan(vol):
        bits.append("calm" if vol < 35 else "turbulent" if vol > 70 else "ordinary vol")
    basis = centre.get("basis_index_z")
    if basis is not None and not np.isnan(basis):
        if abs(basis) > 0.75:
            bits.append("token rich vs fair value" if basis > 0 else "token cheap vs fair value")
        else:
            bits.append("basis near normal")
    trend = centre.get("trend_sma_pct")
    if trend is not None and not np.isnan(trend):
        bits.append("above trend" if trend > 1.5 else "below trend" if trend < -1.5 else "flat trend")
    liq = centre.get("liq_ratio")
    if liq is not None and not np.isnan(liq) and liq < 0.7:
        bits.append("thin")
    return ", ".join(bits) or "unremarkable"


def build(frame: pd.DataFrame, *, as_of: pd.Timestamp | None = None, k: int = DEFAULT_K, horizon_h: int = 24, seed: int = 17) -> RegimeMap:
    """Fit regimes on everything before ``as_of`` and describe the state at it."""
    cols = [c for c in REGIME_FEATURES if c in frame.columns]
    if len(cols) < 3:
        return RegimeMap(note="not enough state columns to describe a regime")

    hist = frame if as_of is None else frame.loc[frame.index <= as_of]
    data = hist[cols].astype(float)
    usable = data.dropna()
    if len(usable) < MIN_ROWS_PER_FIT:
        return RegimeMap(note=f"only {len(usable)} complete hours: too few to fit regimes", n_fitted=len(usable))

    x, med, mad = _standardise(usable.to_numpy())
    labels, centres = _kmeans(np.clip(x, -CLIP_DEVIATIONS, CLIP_DEVIATIONS), k, seed=seed)

    # Outcomes: what the next ``horizon_h`` hours did, from each labelled hour.
    close = hist["spot_close"].astype(float)
    fwd = (close.shift(-horizon_h) / close - 1.0) * 100.0
    lab = pd.Series(labels, index=usable.index, name="regime")
    joined = pd.concat([lab, fwd.rename("fwd")], axis=1, join="inner")

    # Transitions one holding period ahead, on the labels themselves.
    nxt = lab.shift(-horizon_h)
    trans = np.zeros((k, k))
    pair = pd.concat([lab.rename("a"), nxt.rename("b")], axis=1).dropna()
    for a in range(k):
        row = pair[pair["a"] == a]["b"].value_counts(normalize=True)
        for b, share in row.items():
            trans[a, int(b)] = float(share)

    regimes: list[Regime] = []
    for i in range(k):
        members = joined[joined["regime"] == i]
        outcomes = members["fwd"].dropna()
        centre = {c: float(centres[i][j] * mad[j] + med[j]) for j, c in enumerate(cols)}
        enough = len(outcomes) >= MIN_ROWS_PER_REGIME
        regimes.append(
            Regime(
                id=i, n=int((labels == i).sum()), share=float((labels == i).mean()), centre=centre, description=_describe(centre),
                persistence=float(trans[i, i]) if pair.size else None,
                next_ret_median_pct=float(outcomes.median()) if enough else None,
                next_ret_p5_pct=float(np.percentile(outcomes, 5)) if enough else None,
                next_ret_p95_pct=float(np.percentile(outcomes, 95)) if enough else None,
                n_outcomes=int(len(outcomes)),
                flat_share=float((outcomes.abs() < 1e-9).mean()) if enough else None,
            )
        )

    current = None
    if as_of is not None or len(usable):
        last = usable.iloc[-1].to_numpy(float)
        z = np.clip((last - med) / mad, -CLIP_DEVIATIONS, CLIP_DEVIATIONS)
        current = int(((z - centres) ** 2).sum(axis=1).argmin())
    order = sorted(range(k), key=lambda i: regimes[i].centre.get("vol_pctl_90d", 0.0))
    remap = {old: new for new, old in enumerate(order)}
    regimes = [
        Regime(**{**r.__dict__, "id": remap[r.id]}) for r in sorted(regimes, key=lambda r: remap[r.id])
    ]
    trans = trans[np.ix_(order, order)]
    return RegimeMap(
        regimes=regimes, transitions=trans.tolist(), current=remap[current] if current is not None else None,
        horizon_h=horizon_h, n_fitted=int(len(usable)),
        note="regimes fitted only on hours before this moment; sorted from calmest to most turbulent",
    )
