"""Keep the numbers quoted in README.md and docs/submission.md equal to the live API.

The Proof table and the submission's "Current figures" carry counts that move every
day (receipts checked, forecasts scored, live tickets, anchors). Typed by hand they drift
and sit next to the words "recomputed live", which reads as sloppiness. This fetches
``/api/verify``, ``/api/calibration``, ``/api/misses`` and ``/api/anchors`` and rewrites
only those figures, in place, with an "as of" date.

Only numbers are replaced. Every other word, and the user's placeholders
(``<video URL>``, ``<forecast id>``), are left alone. A pattern that no longer matches
raises instead of silently skipping, so a reworded sentence cannot go stale unnoticed.

    nightwatch proof-sync            # fetch and rewrite
    nightwatch proof-sync --check    # fetch and report what would change, write nothing
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://nightwatch-gules.vercel.app/api"
ENDPOINTS = ("verify", "calibration", "misses", "anchors")
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Figures:
    as_of: str
    receipts_checked: int
    receipts_ok: bool
    anchors: int
    anchors_in_bitcoin: int
    n_forecasts: int
    n_evaluated: int
    raw_rate: float
    raw_band: str
    adj_rate: float
    adj_band: str
    n_nights: int | None
    night_ci: tuple[float, float] | None
    replay_missed: int
    replay_scored: int
    live_missed: int
    live_scored: int
    live_distinct_missed: int | None


def fetch(base: str = DEFAULT_BASE, *, timeout: float = 90.0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ENDPOINTS:
        req = urllib.request.Request(f"{base.rstrip('/')}/{name}", headers={"User-Agent": "nightwatch-proof-sync", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https base, read-only
            out[name] = json.loads(r.read().decode("utf-8"))
    return out


def _date(now: datetime) -> str:
    return f"{now.day} {now:%b %Y}"


def figures(api: dict[str, Any], now: datetime | None = None) -> Figures:
    now = now or datetime.now(UTC)
    v, c, m, a = api["verify"], api["calibration"], api["misses"], api["anchors"]
    adj = c["adjusted"]
    anchors = a.get("anchors", [])
    ticket, replay = m["totals"]["ticket"], m["totals"]["replay"]
    nci = adj.get("adj_lo_night_ci")
    return Figures(
        as_of=_date(now),
        receipts_checked=int(v["checked"]), receipts_ok=bool(v["ok"]),
        anchors=len(anchors), anchors_in_bitcoin=sum(1 for x in anchors if x.get("state") == "bitcoin"),
        n_forecasts=int(c["n_matured"]), n_evaluated=int(adj["n_evaluated"]),
        raw_rate=float(c["tail"]["observed_rate"]), raw_band=str(c["tail"]["band"]),
        adj_rate=float(adj["adj_lo_coverage"]), adj_band=str(adj["adj_tail_band"]),
        n_nights=int(adj["n_nights"]) if adj.get("n_nights") else None,
        night_ci=(float(nci[0]), float(nci[1])) if nci else None,
        replay_missed=int(replay["missed"]), replay_scored=int(replay["scored"]),
        live_missed=int(ticket["missed"]), live_scored=int(ticket["scored"]),
        live_distinct_missed=int(ticket["distinct_missed"]) if ticket.get("distinct_missed") is not None else None,
    )


def _n(x: int) -> str:
    return f"{x:,}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}"


def _nights(f: Figures) -> str:
    """The clause that says how many independent nights the forecasts come from."""
    if not f.n_nights:
        return ""
    ci = f"; resampling whole nights the interval is {_pct(f.night_ci[0])}% to {_pct(f.night_ci[1])}%" if f.night_ci else ""
    return f" ({_n(f.n_nights)} independent nights{ci})"


def _sub(pattern: str, repl: str, text: str, label: str, changes: list[str]) -> str:
    new, k = re.subn(pattern, lambda _m: repl, text, count=1, flags=re.S)
    if not k:
        raise ValueError(f"proof-sync: pattern for {label!r} no longer matches; the wording changed, update the pattern")
    if new != text:
        changes.append(label)
    return new


def _misses(f: Figures) -> str:
    live = f"{f.live_missed} of {_n(f.live_scored)} live tickets"
    if f.live_distinct_missed is not None:
        live += f" ({f.live_distinct_missed} distinct events)"
    return f"{_n(f.replay_missed)} of {_n(f.replay_scored)} replays and {live} went past the line"


_MISSES = r"[\d,]+ of [\d,]+ replays and \d+ of [\d,]+ live tickets(?: \(\d+ distinct events\))? went\s+past\s+the\s+line"
_SCORED_BAND = (
    r"(?: \([^()]*independent nights[^()]*\))?"
)


def rewrite_readme(text: str, f: Figures) -> tuple[str, list[str]]:
    ch: list[str] = []
    t = _sub(r"Figures as of \d+ \w+ \d{4}\.", f"Figures as of {f.as_of}.", text, "README as-of line", ch)
    verdict = "no break" if f.receipts_ok else "CHAIN BROKEN, see /api/verify"
    t = _sub(r"\([\d,]+ checked, [^,()]+(?:, see /api/verify)?, as of \d+ \w+ \d{4}\)", f"({_n(f.receipts_checked)} checked, {verdict}, as of {f.as_of})", t, "README receipts", ch)
    t = _sub(r"\(\d+ of \d+ in Bitcoin;", f"({f.anchors_in_bitcoin} of {f.anchors} in Bitcoin;", t, "README anchors", ch)
    t = _sub(
        r"[\d,]+ scored forecasts" + _SCORED_BAND + r", raw breach rate [\d.]+% \(\w+\), [\d.]+% with factors fitted only on earlier forecasts \(\w+\), as of \d+ \w+ \d{4}",
        f"{_n(f.n_forecasts)} scored forecasts{_nights(f)}, raw breach rate {_pct(f.raw_rate)}% ({f.raw_band}), {_pct(f.adj_rate)}% with factors fitted only on earlier forecasts ({f.adj_band}), as of {f.as_of}",
        t, "README calibration", ch,
    )
    t = _sub(_MISSES + r" \(as of \d+ \w+ \d{4}\)", f"{_misses(f)} (as of {f.as_of})", t, "README misses", ch)
    return t, ch


def rewrite_submission(text: str, f: Figures) -> tuple[str, list[str]]:
    ch: list[str] = []
    t = _sub(r"\*\*Current figures, as of \d+ \w+ \d{4}\*\*", f"**Current figures, as of {f.as_of}**", text, "submission as-of line", ch)
    verdict = "no break" if f.receipts_ok else "a BREAK (see /api/verify)"
    t = _sub(
        r"recomputes [\d,]+ chained verdicts with (?:no break|a BREAK \(see /api/verify\)); \d+ of \d+ daily\s+anchors are confirmed in Bitcoin",
        f"recomputes {_n(f.receipts_checked)} chained verdicts with {verdict}; {f.anchors_in_bitcoin} of {f.anchors} daily\n  anchors are confirmed in Bitcoin",
        t, "submission receipts", ch,
    )
    t = _sub(r"Scored out of sample: [\d,]+ matured forecasts" + _SCORED_BAND + r"\.", f"Scored out of sample: {_n(f.n_forecasts)} matured forecasts{_nights(f)}.", t, "submission forecasts", ch)
    t = _sub(r"was breached [\d.]+% of the time \(\w+ band\)", f"was breached {_pct(f.raw_rate)}% of the time ({f.raw_band} band)", t, "submission raw rate", ch)
    t = _sub(r"[\d.]+% on [\d,]+ evaluated \(\w+ band\)", f"{_pct(f.adj_rate)}% on {_n(f.n_evaluated)} evaluated ({f.adj_band} band)", t, "submission adjusted rate", ch)
    t = _sub(_MISSES, _misses(f), t, "submission misses", ch)
    return t, ch


def run(*, base: str = DEFAULT_BASE, check: bool = False, root: Path = ROOT, api: dict[str, Any] | None = None, now: datetime | None = None) -> list[str]:
    """Fetch (unless ``api`` is given), rewrite both files, return what changed."""
    f = figures(api if api is not None else fetch(base), now)
    changed: list[str] = []
    for rel, fn in (("README.md", rewrite_readme), ("docs/submission.md", rewrite_submission)):
        p = root / rel
        raw = p.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in raw else "\n"
        new, ch = fn(raw.replace("\r\n", "\n"), f)
        new = new.replace("\n", eol)
        if new != raw:
            changed += [f"{rel}: {c}" for c in ch] or [f"{rel}: as-of date"]
            if not check:
                p.write_bytes(new.encode("utf-8"))
    return changed
