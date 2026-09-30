"""Which tail calibration fits a short's loss best, scored out of sample on paired short replays.

A: today - the short's loss line is the token's upper tail widened by k_hi fitted on longs.
B: a short's own loss tail, fitted (k_lo and margin c_lo) on earlier short replays only.
C: one loss-tail fit on earlier replays of both sides, side-signed.
Each forecast uses only factors fitted on forecasts that had matured before it.
"""
import numpy as np
import pandas as pd

from nightwatch.config import Settings
from nightwatch.data.store import Store
from nightwatch.journal.adjust import factors_as_of
from nightwatch.journal.journal import Journal

with Store(Settings().db_path) as store:
    j = Journal(store)
    from nightwatch.cli import _entries_from_store

    j.mature(spot_symbol_for={e.ticker: e.spot_symbol for e in _entries_from_store(store, Settings())})
    df = j.forecasts(kind="replay", matured_only=True)
longs, shorts = df[df.side == "long"], df[df.side == "short"]
print("matured long", len(longs), "short", len(shorts))
rows = []
cache: dict = {}
for _, x in shorts.sort_values("as_of").iterrows():
    key = x.as_of.floor("D")
    if key not in cache:
        cache[key] = (factors_as_of(longs, x.as_of), factors_as_of(shorts, x.as_of), factors_as_of(df, x.as_of))
    fl, fs, fb = cache[key]
    if not (fl and fs and fb):
        continue
    p5, p50, r = x.p5, x.p50, x.ret_pct
    a = fl.for_hours(x.horizon_h); b = fs.for_hours(x.horizon_h); c = fb.for_hours(x.horizon_h)
    rows.append({"ticker": x.ticker, "r": r, "w": p50 - p5,
                 "A": p50 + a.k_hi * (p5 - p50), "B": p50 + b.k_lo * (p5 - p50) - b.c_lo, "C": p50 + c.k_lo * (p5 - p50) - c.c_lo})
e = pd.DataFrame(rows)
e["D"] = e[["A", "B"]].min(axis=1)  # the more cautious of today's line and the short's own
t3 = pd.qcut(e.w.rank(method="first"), 3, labels=["narrow", "middle", "wide"])
pin = lambda r, q: np.where(r - q >= 0, 0.05 * (r - q), -0.95 * (r - q))  # noqa: E731
for m in "ABCD":
    br = e.r < e[m]
    print(m, f"breach {br.mean():.2%}", {k: f"{br[t3 == k].mean():.1%}" for k in ["narrow", "middle", "wide"]}, f"mean line {e[m].mean():.2f}", f"pinball {pin(e.r, e[m]).mean():.4f}")
for m in "BCD":
    d = pd.DataFrame({"t": e.ticker, "d": pin(e.r, e.A) - pin(e.r, e[m])}).groupby("t").d.mean()
    print(f"{m} vs A: better on {(d > 0).sum()} of {len(d)} tokens, clustered t = {d.mean() / (d.std(ddof=1) / np.sqrt(len(d))):+.2f}")
print("n evaluated", len(e))
