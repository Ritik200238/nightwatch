"""Check the study numbers typed into the docs against the live /studies page.

The studies are recomputed from the journal, so the numbers move as forecasts mature,
and a hand-typed snapshot drifts: "not one of 24 tokens" had quietly become one of 24.
Run this before anything is submitted or recorded; it prints every claim the live page
no longer supports and exits non-zero if there is one.

    python research/check_doc_numbers.py [https://nightwatch-gules.vercel.app/api]
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORDS = {3: "three", 5: "five", 11: "eleven"}


def expected(studies: list[dict]) -> list[tuple[str, str]]:
    """(what the docs should say, where it comes from) for each drift-prone claim."""
    by = {s["key"]: s for s in studies}
    count = {v: sum(1 for s in studies if s["verdict"] == v) for v in ("yes", "no", "unclear")}
    out = [(f"{WORDS.get(len(studies), len(studies))}", "number of studies")]
    out.append((f"{WORDS.get(count['no'], count['no'])} came back no", "studies answered no"))
    near = by["closer_is_not_tighter"]["stats"]
    out.append((f"{near['tokens_near_tighter']:.0f} of 24", "tokens where closer is tighter"))
    out.append((f"t = {near['clustered_t']:.1f}".replace("-", "−"), "closer-is-tighter clustered t"))
    out.append((f"{round((near['sd_ratio_near_over_far'] - 1) * 100)}%", "near half wider by sd"))
    band = by["one_factor_hid_two_errors"]["stats"]
    out.append((f"{band['pooled_lo_multi_day'] * 100:.1f}%", "multi-day breach under one factor"))
    return out


def expected_record(verify: dict, misses: dict, cal: dict) -> list[tuple[str, str]]:
    """Counts the README and submission text quote from the receipt chain, /wrong and /calibration."""
    tk, rp = misses["totals"]["ticket"], misses["totals"]["replay"]
    adj = cal["adjusted"]
    return [
        (f"{verify['anchored_in_bitcoin']} of {verify['anchors']}", "anchors confirmed"),
        (f"{adj['raw_lo_coverage'] * 100:.1f}%", "raw breach rate"),
        (f"{adj['adj_lo_coverage'] * 100:.1f}%", "fitted-on-earlier breach rate"),
        (f"{rp['missed']} of {rp['scored']:,} replays", "replay misses"),
        (f"{tk['missed']} of {tk['scored']:,} live tickets", "live ticket misses"),
    ]


def main() -> int:
    api = sys.argv[1] if len(sys.argv) > 1 else "https://nightwatch-gules.vercel.app/api"
    live = json.load(urllib.request.urlopen(f"{api}/studies", timeout=120))
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").lower().split())  # a claim may wrap across lines
    missing = [(want, why) for want, why in expected(live["studies"]) if want.lower() not in readme]
    fetch = lambda name: json.load(urllib.request.urlopen(f"{api}/{name}", timeout=120))  # noqa: E731
    record = expected_record(fetch("verify"), fetch("misses"), fetch("calibration"))
    print(f"live run: {live.get('last_run')}")
    for want, why in missing:
        print(f"README no longer says '{want}' ({why})")
    # Record figures drift daily; every doc that quotes them carries an "as of" date, so a
    # mismatch here means refresh the text and the date together.
    stale = 0
    for name in ("README.md", "docs/submission.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").lower().split())
        for want, why in record:
            if want.lower() not in text:
                print(f"{name} no longer says '{want}' ({why})")
                stale += 1
    # Growing counts: the doc may lag by a day, but not by more than 5% (and must carry a date).
    verify, cal = fetch("verify"), fetch("calibration")
    for name in ("README.md", "docs/submission.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for pat, now, why in (
            (r"([\d,]+) (?:chained verdicts|checked)", verify["checked"], "receipts verified"),
            (r"([\d,]+) (?:matured|scored) forecasts", cal["n_matured"], "matured forecasts"),
        ):
            quoted = [int(m.replace(",", "")) for m in re.findall(pat, text)]
            if not quoted or abs(max(quoted) - now) > 0.05 * now:  # other, smaller counts may share the phrase
                print(f"{name}: {why} quoted as {quoted or 'nothing'}, live {now:,}")
                stale += 1
        if "as of" not in text.lower():
            print(f"{name} has no 'as of' date on its figures")
            stale += 1
    return 1 if (missing or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
