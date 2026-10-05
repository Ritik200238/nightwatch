"""The method freeze, and the forecasts scored after it.

The tail adjustment in ``adjust.py`` was designed while looking at the same replayed
forecasts it is later scored on. Its walk-forward evaluation is leak-free in its
*parameters* (each factor is fitted only on earlier outcomes), but its *structure* was
chosen with the answers in view, so the headline breach rate on that history is
optimistic by an amount nobody can state.

The honest fix is a holdout that is out of sample by construction: record a date and a
git tag at which the method stopped changing (``method_freeze.json``), then report
separately every forecast made after that date. Nothing in that group could have shaped
the method. The group starts empty and grows by one night at a time; the page says how
many nights it holds so nobody reads three nights as proof.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nightwatch.journal.calibration import count_nights, night_bootstrap_ci, wilson_interval

RECORD_PATH = Path(__file__).with_name("method_freeze.json")


def load_freeze() -> dict[str, Any]:
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


def in_force(freeze: dict[str, Any] | None = None, now: pd.Timestamp | None = None) -> bool:
    """Has the freeze date arrived? Before it, "frozen" would be a claim about the future."""
    f = freeze or load_freeze()
    return (now if now is not None else pd.Timestamp.now(tz="UTC")) >= pd.Timestamp(f["frozen_at"])


def holdout(rows: pd.DataFrame, freeze: dict[str, Any] | None = None, now: pd.Timestamp | None = None) -> dict[str, Any]:
    """Breach rate of the adjusted 5% line on forecasts made at or after the freeze.

    ``rows`` is ``adjust.expanding_rows`` output (columns ``as_of``, ``r``, ``a5``, ``a95``).
    Reports the forecast-level Wilson interval, labelled as assuming independence, and the
    whole-night bootstrap interval beside it.
    """
    f = freeze or load_freeze()
    frozen_at = pd.Timestamp(f["frozen_at"])
    out: dict[str, Any] = {
        "frozen_at": f["frozen_at"], "git_tag": f.get("git_tag"), "git_commit": f.get("git_commit"),
        "note": f.get("note"), "n": 0, "breaches": 0, "rate": None, "wilson_ci": None,
        "n_nights": 0, "night_ci": None, "hi_breaches": 0, "hi_rate": None,
        "label": "scored after the method was frozen",
        "in_force": in_force(f, now),
    }
    if rows is None or rows.empty:
        return out
    r = rows.copy()
    r["as_of"] = pd.to_datetime(r["as_of"], utc=True)
    r = r[r["as_of"] >= frozen_at]
    n = len(r)
    if not n:
        return out
    lo_hit = (r["r"] < r["a5"]).to_numpy()
    hi_hit = (r["r"] > r["a95"]).to_numpy()
    k = int(lo_hit.sum())
    out.update(
        n=n, breaches=k, rate=k / n, wilson_ci=list(wilson_interval(k, n)),
        n_nights=count_nights(r["as_of"]), night_ci=night_bootstrap_ci(r["as_of"], lo_hit),
        hi_breaches=int(hi_hit.sum()), hi_rate=float(hi_hit.mean()),
    )
    if out["night_ci"] is not None:
        out["night_ci"] = list(out["night_ci"])
    return out
