"""Replay the short side at exactly the moments the long replays were taken.

Every scored replay in the journal was a long, so the tail a short is sized on - the
token rising - had never been scored as a short's own loss. Replaying the same closed-
window starts with the side flipped gives a paired set: the same nights, the other way.

    python research/replay_shorts.py [TICKER ...]
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from nightwatch.cli import _entries_from_store
from nightwatch.config import Settings
from nightwatch.data.store import Store
from nightwatch.journal.journal import Journal
from nightwatch.journal.replay import replay_ticker
from nightwatch.pipeline.analyze import AnalysisContext


def main(tickers: list[str]) -> int:
    settings = Settings()
    with Store(settings.db_path) as store:
        journal = Journal(store)
        ctx = AnalysisContext(store=store, entries=_entries_from_store(store, settings), journal=journal)
        longs = journal.forecasts(kind="replay")
        longs = longs[longs["side"] == "long"]
        have = journal.forecasts(kind="replay")
        have = have[have["side"] == "short"]
        for t in tickers or sorted(longs["ticker"].unique()):
            points = [p.to_pydatetime() for p in pd.to_datetime(longs.loc[longs["ticker"] == t, "as_of"]).sort_values()]
            done = set(pd.to_datetime(have.loc[have["ticker"] == t, "as_of"]))
            points = [p for p in points if pd.Timestamp(p) not in done]
            if not points:
                print(f"{t}: already replayed", flush=True)
                continue
            t0 = time.time()
            n = replay_ticker(ctx, journal, t, points=points, side="short")
            print(f"{t}: {n} short replays in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
