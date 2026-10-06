# Backfilling the expanded universe safely

**This is a plan for a human (or the orchestrating session) to run step by step, one
batch at a time, watching `/health` between batches. It is not a script to run
unattended, and nothing in this document should be executed automatically.**

## Why this document exists

On 2026-10-06 the production box (1 GB AWS Lightsail, Mumbai, `api` + `recorder`
containers, one `uvicorn` worker, SQLite with WAL — see `docs/deploy.md`) was brought
down three times trying to run a background replay/backfill job alongside live
traffic. Each time it stalled, hit its memory cap, and had to be killed. The box has
209 MB resident for the API and 44 MB for the recorder with 24 tokens warm, on a 1 GB
box with `vm.swappiness=10` and zswap doing the rest — there is very little headroom,
and a naive "backfill everything now" job is exactly the kind of unthrottled, unbounded
work that caused today's failures.

`nightwatch.config.DEFAULT_CORE_TICKERS` now lists 112 tickers (see
`UNIVERSE_CANDIDATES.md` for the ranked shortlist and reasoning), up from 24. Nothing
on production has backfilled the 88 new tickers yet. This document is the safe way to
do that, designed around the tool that already exists for exactly this —
`nightwatch sync --core` (`nightwatch/cli.py`, `cmd_sync`) — rather than inventing a new
heavy job.

## Why `nightwatch sync --core` is already the right tool

- `nightwatch sync --core --tickers A B C --limit N` selects an explicit, small set of
  tickers (`cli.py` `_select`), so a run only ever touches the tickers you name.
- It is resumable *for free*, per ticker and per interval: `sync_universe` ->
  `_missing_ranges` (`nightwatch/data/sync.py:95`) diffs what the store already has
  (`store.bar_coverage`) against what's wanted, and only fetches the gap. Killing a run
  partway through and re-running the same command later picks up exactly where it left
  off — it will not re-download bars it already has, and it will not skip bars it's
  missing.
- `--since` controls how far back to backfill (default 2025-01-01, matching the
  existing 24 tokens' history, so the new tickers end up on the same footing).
- `--intervals` defaults to `1h 1d`; keep that default so new tickers get the same two
  interval types the dashboard and the analog engine expect.
- It talks to Bitget and Yahoo through `BitgetPublicClient`/`YahooChartClient`, which
  are already rate-limited (`settings.bitget_rate_per_sec`, default 8/s) and have their
  own backoff — this is not a job that hammers upstream, it is bounded by that rate
  limiter regardless of batch size.

So the plan is: run this exact command, in small ticker batches, with health checks
between batches — not a new backfill script.

## The procedure

### 0. Preconditions (check once, before starting)

```bash
ssh ubuntu@<ip> 'curl -s localhost:8000/health'
```

Confirm `ok: true`, `warm.state` is not `running`, and `last_book_ts` is recent (within
2 minutes). Do not start if the box is already unhealthy — fix that first.

```bash
ssh ubuntu@<ip> 'free -m; docker stats --no-stream'
```

Note the baseline: resident memory for `api` and `recorder`, and free memory. This is
the number every later health check compares against.

### 1. Batch the 88 new tickers into small groups

Use groups of **5 tickers**. At 112 total and 24 already backfilled, that's 88 new
tickers -> **18 batches of 5** (last batch has 3). Five is small enough that one bad
ticker (a delisted symbol, a Yahoo gap) doesn't stall a large chunk of work, and small
enough that each batch's own memory footprint (new bars loaded into the sync process,
not the long-running `api`/`recorder` containers) is bounded and short-lived.

Pull the exact new-ticker list by diffing what's already in the store from what's in
config:

```bash
ssh ubuntu@<ip> 'cd nightwatch && docker compose exec api python -m nightwatch.cli universe --core' > /tmp/core_universe.txt
# has_data == False rows are the ones that still need a backfill.
```

(Read-only — this just lists the universe, it does not sync anything.)

### 2. Run one batch, throttled, at low priority

From the box, **not** inside the `api` or `recorder` containers (don't compete with
live traffic's process for the same container's share of cgroup memory) — run the sync
as a one-off container with a memory limit and low CPU/IO priority:

```bash
ssh ubuntu@<ip> 'cd nightwatch && docker compose run --rm \
  --memory=256m --cpus=0.5 \
  -e NIGHTWATCH_BITGET_RPS=4 \
  --entrypoint nice \
  api -n 19 ionice -c3 python -m nightwatch.cli sync --core \
    --tickers TICKER1 TICKER2 TICKER3 TICKER4 TICKER5 \
    --since 2025-01-01'
```

Notes on every flag, since this is the part that must not repeat today's failure:

- `--memory=256m`: hard cap. If the batch's own process tries to exceed it, Docker
  kills *that one-off container*, not the live `api`/`recorder` containers. A kill here
  is safe and just means re-run the same command (it resumes).
- `--cpus=0.5`: half a vCPU, so the live `api` container (which needs to answer judge
  requests in under 5 s) is not starved.
- `nice -n 19` / `ionice -c3`: lowest CPU and I/O scheduling priority. This is the
  direct fix for "stalled... alongside live traffic" — the backfill yields to anything
  real.
- `NIGHTWATCH_BITGET_RPS=4`: half the normal 8/s, since this run competes with the
  recorder's own Bitget calls for the same upstream rate limits (Bitget rate-limits per
  IP, not per process).
- `--tickers ...` names exactly 5 tickers — never omit this and fall back to `--core`
  alone, which would attempt all 112 at once.

### 3. Check health before the next batch

```bash
ssh ubuntu@<ip> 'curl -s localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[\"ok\"], d[\"warm\"][\"state\"])"'
ssh ubuntu@<ip> 'free -m'
curl -s -o /dev/null -w "%{time_total}\n" https://nightwatch-gules.vercel.app/api/health
```

**Abort/pause conditions** — stop and do not run the next batch if any of these hold:

- `/health` returns anything other than `ok: true`.
- Free memory on the box is lower than the batch-0 baseline by more than ~150 MB
  (the one-off container's 256 MB cap should mean this doesn't happen, but check).
- The public desk's `/health` round-trip (through Vercel's proxy) takes noticeably
  longer than its usual ~1-2 s, or returns a non-200.
- `docker compose logs --tail=50 api recorder` shows new errors since the batch started.

If any of these fire: wait 5 minutes, re-check, and only continue once healthy. If still
unhealthy, stop entirely and investigate before resuming — do not push through.

### 4. Wait between batches

Sleep at least **60 seconds** between batches even when healthy, so the recorder's own
periodic jobs (order-book snapshots every 60 s) get a clean slot and the box's memory
has a chance to settle (zswap compaction, SQLite WAL checkpoint) before the next batch
adds load.

### 5. Repeat for all 18 batches

Same command, next 5 tickers, same health check after each. Do this one batch at a
time — this document assumes a human (or the orchestrating session) runs each step and
watches the result before issuing the next, not a loop left running unattended.

### 6. After all batches: verify, then update `docs/deploy.md`'s measured numbers

```bash
ssh ubuntu@<ip> 'curl -s localhost:8000/universe' | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for e in d if e['has_data']), '/', len(d))"
```

Re-measure what `docs/deploy.md` currently states for 24 tokens (API memory with all
warm, warm-up time, cold-sweep latency at N tokens at once) now that there are 112, and
update that doc — those numbers will have moved and the current doc would otherwise be
quietly wrong, the exact kind of drift `/wrong` on this project exists to catch.

## Time estimate

Each ticker needs: ~10 months of hourly bars (730 1h candles max per Yahoo chunk, well
within one chunk) + daily bars (one chunk) from both Bitget (for funding/basis) and
Yahoo (native close), plus earnings history. Bitget bar-fetching is the dominant cost:
at `NIGHTWATCH_BITGET_RPS=4` and roughly 10-20 paginated calls per ticker for ~10 months
of hourly bars, that's 3-5 s of API time per ticker, plus Yahoo (1-2 calls, under a
second) and earnings (1 call). Call it **10-20 s of actual work per ticker**, batches of
5 take roughly **1-2 minutes** of work plus the 60 s cooldown, so a batch-to-batch cycle
is about **2-3 minutes**. 18 batches: **roughly 40-55 minutes of wall-clock time**,
run interactively over a longer session so there's room to pause on an abort condition.
This is a rough estimate, not a measured one — NOT VERIFIED until a real batch is timed
on the box; the first batch's actual duration should be used to refine the estimate for
the remaining 17.

## What this plan deliberately does not do

- It does not touch `record` (the order-book recorder) or its periodic jobs — those
  keep running against the existing 24-core selection throughout. Order-book recording
  for the new tickers is a separate decision (it raises `record`'s own footprint
  continuously, not just during a backfill window) and is out of scope here.
- It does not change `NIGHTWATCH_CORE_TICKERS` or restart the `api`/`recorder`
  containers mid-backfill. The containers keep serving the current 24-ticker universe
  to judges throughout; only once backfill is verified complete and `docs/deploy.md` is
  re-measured should the box's env be updated to pick up the full 112 and the
  containers redeployed (a separate, deliberate step — not part of this document).
- It does not run anything unattended. Every batch is a single manual command with a
  manual health check after it.
