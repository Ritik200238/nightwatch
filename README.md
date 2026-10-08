# Nightwatch

### Stress-test the trade before you place it.

A pre-trade desk for tokenized US stocks (rTokens) on Bitget — built for the hours a normal
stock tool goes blind: nights, weekends, holidays, the window where only the token moves.

[![ci](https://github.com/Ritik200238/nightwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/Ritik200238/nightwatch/actions/workflows/ci.yml)
[![uptime](https://github.com/Ritik200238/nightwatch/actions/workflows/uptime.yml/badge.svg)](https://github.com/Ritik200238/nightwatch/actions/workflows/uptime.yml)
[![browser-smoke](https://github.com/Ritik200238/nightwatch/actions/workflows/browser-smoke.yml/badge.svg)](https://github.com/Ritik200238/nightwatch/actions/workflows/browser-smoke.yml)
[![tests](https://img.shields.io/badge/tests-1%2C500%2B%20passing-brightgreen)](https://github.com/Ritik200238/nightwatch/actions/workflows/ci.yml)

**Live desk → https://nightwatch-gules.vercel.app** · **Demo video (2:22) → https://youtu.be/7R6LNyro4oM**

<p align="center">
  <a href="https://youtu.be/7R6LNyro4oM"><img src="https://img.youtube.com/vi/7R6LNyro4oM/maxresdefault.jpg" alt="Watch the Nightwatch demo video on YouTube" width="640"></a>
</p>

[Demo video](https://youtu.be/7R6LNyro4oM) · [Who it's for](#who-it-is-for-and-the-idea-behind-it) · [A full research task](#one-complete-research-task-start-to-finish) · [What we measured](#one-thing-we-measured-that-changes-how-you-read-a-night-quote) · [Built on Bitget](#built-on-bitget-not-just-mentioned-on-bitget) · [Proof](#the-proof-recompute-it-yourself--nothing-here-is-a-screenshot-of-a-claim) · [Claim boundaries](#claim-boundaries) · [Run it](#how-it-works-end-to-end)

<p align="center">
  <img src="docs/img/hero-home.png" alt="Nightwatch home page: type a trade, get a verdict, every number scored in public" width="860">
</p>

---

## The pitch in one sentence

Type a trade in plain English or 中文 → Nightwatch finds the real past moments like it,
shows what happened after them, stress-tests it against real crashes, prices your exit on
Bitget's live order book, and gives you a sized verdict — **GO, REDUCE TO, HEDGE, REVIEW,
or NO GO.** Every verdict is written down, hash-chained, and scored against reality in
public. It never places an order; the human decides.

That is exactly the sub-theme's own definition: *"before opening a position, AI retrieves
historically similar scenarios → historical distribution → preset stress tests."* You can
see all three steps, in order, on one screen, in under 60 seconds.

<p align="center">
  <img src="docs/img/three-steps.png" alt="How this verdict was built: Step 1 similar past moments, Step 2 what happened after, Step 3 stress tests, then the verdict" width="860">
</p>

---

## Who it is for, and the idea behind it

**Built for** retail and semi-professional traders who hold tokenized US stocks on Bitget through
the US close: roughly 5,000 to 200,000 USDT a position, a few trades a week, mostly the large
names (TSLA, NVDA, AAPL, MSFT, AMZN, GOOGL, META) and the leveraged index tokens (TQQQ, SQQQ).
They are happy to hold overnight or over a weekend and unhappy to be caught by a gap they never
priced. **Not for** market makers, high-frequency systems, or anyone who wants an AI to place
orders. Nightwatch never places one.

**The idea.** A tokenized stock trades all week, but the stock behind it only trades about a fifth of
the week (regular hours plus a few extended ones). The rest of the time the token's price is set by its own thin book, and
the trader's worst losses come from a handful of those closed-market nights, not from average
days. So the question worth asking before every position is: *if this goes wrong while the market
is shut, how wrong, and what size survives it?* Nightwatch answers that from the token's own
history, the stock's own 30-year record, and Bitget's live order book, and the AI only explains
what deterministic code computed.

## One complete research task, start to finish

> **Question (typed as is):** *long 15000 usdt nvda 5x over the weekend stop 160*
> **Asked on a Thursday, answered in about 13 seconds on the live desk, 8 Oct 2026.**

- **Read.** Long 15,000 USDT of NVDA, 5x (3,000 margin), Friday's close to Monday's open (66 h), stop 160. It asks for the account size, which it needs to size the trade.
- **Past moments and distribution.** A one-in-twenty bad night loses about 503 USDT at this size. Over NVDA's last 87 token weekends, 1 in 20 lost more than 3.5% and the worst was -13.7%. The stock's own record has 1,400+ weekends to set that against.
- **Stress tests.** Ten preset cases (weekend gap, volatility spike, token-vs-fair-value blowout, a thin book, being unable to exit for 24 h, and more), plus a leverage table from 2x to 20x checked against the same history.
- **Exit.** The live Bitget order book is walked for the exact size to price the real exit cost.
- **Verdict.** REVIEW. The stop is 32% away, wider than the 25% rule, and without an account size the position can't be sized. By account size it says 25k, 50k, 100k, 250k each come out NO GO.

That is the sub-theme's own loop, "retrieve similar scenarios, show the historical distribution,
run preset stress tests", on one screen, ending in a decision the human still makes.

## One thing we measured that changes how you read a night quote

At 3 a.m. the token has a price and the stock does not. Is that price a better guess at
Monday's real open than just "it will open where it closed"? We checked every US session in
the stored hourly bars (125,367 token quotes over 8,509 nights, 23 stocks, Sep 2024 to Sep 2026) against
the real 09:30 print:

| Token quote taken… | Median miss vs the real open | Last close's median miss | Token closer on |
|---|---:|---:|---:|
| in the last hour before the open | **20 bps** (19.4–20.9) | 85 bps | 81% of nights |
| 4–6 hours before | 55 bps | 86 bps | 65% |
| 12–24 hours before | **77 bps** (75.0–79.6) | 82 bps | 54% |

Read it plainly: the overnight quote is a good guide only in the last few hours. Twelve or more
hours out it is barely better than yesterday's close, so a stop placed against it is placed
against noise. Intervals resample whole nights, not hours. It describes this sample and never
feeds a verdict. [`/studies`](https://nightwatch-gules.vercel.app/studies) and
[`/api/quote-trust/NVDA`](https://nightwatch-gules.vercel.app/api/quote-trust/NVDA) show the rest,
including the control for how much of the gap is just the market moving.

---

## Why this is different from "an AI chatbot that talks about stocks"

| | Most AI trading bots | Nightwatch |
|---|---|---|
| Past moments | Vibes, or nothing | Real retrieval: named dates, a similarity score, what each one shares and differs on — [not hidden behind a claim](#claim-boundaries) |
| Stress tests | Generic, same for every trade | Fitted from the token's own history, sized to *your* position, scaled to *your* hold length, taken from the tail that actually hurts *your* side |
| The verdict | A vibe ("looks bullish!") | A number: GO / REDUCE TO X / HEDGE Y% / REVIEW / NO GO, with every figure traceable to a source |
| Getting out | Never mentioned | Walks Bitget's **live order book** for your exact size and prices the real exit cost |
| Leverage | Ignored | A full liquidation table, 2×–20×, each level checked against the same real history |
| Track record | Marketing copy | A public, scored, hash-chained, Bitcoin-anchored record you can recompute yourself — see below |
| When it's wrong | Not shown | Published, on purpose, at [`/wrong`](https://nightwatch-gules.vercel.app/wrong) |

---

## See it work

**1. Ask it anything, in plain words.** English, 中文, messy phrasing, leverage, stops,
holdings you already have — it reads the trade, tells you what it understood ("I read this
as…"), and runs the full chain. The reader is tested blind on 102 messy phrasings in English and
中文: 98 read fully right, 313 of 317 fields correct, and the misses are published on
[`/studies`](https://nightwatch-gules.vercel.app/studies).

**2. It checks your own reasoning.** Give it a reason ("because Nvidia hit record highs,
wrong if it closes below 170") and it holds that claim against real news headlines and SEC
filings stored *before* the report — "in the news," "the news says otherwise," or "not in
our feeds," every quote a real stored headline with a link.

**3. Leverage gets a real safety table**, not a single scary number — every level from 2×
to 20×, same position, same past moments, so you can see exactly where liquidation risk
turns from clear to reviewable.

<p align="center">
  <img src="docs/img/leverage-safety.png" alt="Leverage safety table: 2x to 20x, liquidation price, distance, margin, and how many of the last 80 similar moments would have liquidated you" width="860">
</p>

**4. Follow-ups are instant and literal — not a new chat.** "What if it gaps down 10%?"
re-runs the exact report against that shock, in under a second, with a chart:

<p align="center">
  <img src="docs/img/chat-followup.png" alt="Chat follow-up: a 10% move down loses about 1,000 USDT, with a bar chart comparing the shock to the 1-in-20 loss and worst stress scenario" width="860">
</p>

Notice the footer in that screenshot — **every number on that answer is traced to the exact
feed and how old it is**, down the millisecond. That line is generated from the real
pipeline, not written by hand.

---

## Built on Bitget, not just *mentioned* on Bitget

<p align="center">
  <img src="docs/img/bitget-integration.png" alt="Built on Bitget, checked live: Bitget candles and order books, Bitget perp margin tiers, Bitget US-stock MCP, bitget-signal skill, Qwen through the Bitget hackathon gateway, Agent Hub skill file" width="860">
</p>

The strip above was captured with every integration green. Each one is checked against
reality on every report, and [`/sources`](https://nightwatch-gules.vercel.app/sources) shows the live
status of each, including any that are down at that moment:

* **Bitget spot & perp candles, funding, and order books** — pulled every 30 s, 1.6M+ order-book
  snapshots recorded and counting. This *is* the price data the whole product runs on.
* **Bitget perp margin tiers** — real liquidation math, not a guessed maintenance margin.
* **Bitget's US-stock data MCP server** — live quotes, analyst targets, insider trades,
  fundamentals, dividends, calendar, consensus estimates, and sentiment, called directly.
* **Bitget perp open interest** — a crowded-trade flag on every leveraged report.
* **Bitget Wallet RWA listing status** — is the token even tradable right now.
* **bitget-signal skill** — an independent technical-analysis skill cross-checked against
  our own numbers.
* **Qwen 3.8 Max through Bitget's own hackathon gateway** — the language layer.
* **An Agent Hub-style skill file, shipped in this repo** ([`skills/nightwatch-stress-test`](skills/nightwatch-stress-test/SKILL.md)) —
  the pre-trade check any agent can call before drafting an order.
* **A read-only MCP server of our own** (`stress_test`, `list_conditions`, `list_tokens`) —
  so any AI tool can ask Nightwatch the same question a human would:

  ```bash
  claude mcp add nightwatch --transport http https://nightwatch-gules.vercel.app/api/mcp
  ```

Plus Yahoo, Nasdaq, FRED, SEC EDGAR, RSS news, and Cboe options data — **21 distinct data
sources in total**, each listed with its real row count and freshness on
[`/sources`](https://nightwatch-gules.vercel.app/sources):

<p align="center">
  <img src="docs/img/sources.png" alt="Data sources page: every feed with its row count, status and how recently it last delivered" width="860">
</p>

---

## The proof (recompute it yourself — nothing here is a screenshot of a claim)

Figures as of 8 Oct 2026. Pulled live from the production API — this whole block is
rewritten by a script (`nightwatch proof-sync`) that reads the same endpoints linked
below, so it can't drift from what the site shows.

| Claim | The real number, right now | Check it yourself |
|---|---:|---|
| Every live verdict is on the record, unedited | **(1,913 checked, no break, as of 8 Oct 2026)** | [`/api/verify`](https://nightwatch-gules.vercel.app/api/verify) recomputes the whole hash chain live |
| Anchored to something we can't fake | **(9 of 9 in Bitcoin; verify a `.ots` proof at opentimestamps.org)** | [`/api/anchors`](https://nightwatch-gules.vercel.app/api/anchors) |
| The "1-in-20 bad case" line roughly holds | **3,642 scored forecasts (141 independent nights; resampling whole nights the interval is 2.2% to 4.6%), raw breach rate 4.5% (green), 3.2% with factors fitted only on earlier forecasts (green), as of 8 Oct 2026** | [`/calibration`](https://nightwatch-gules.vercel.app/calibration), recomputed live |
| We publish our own misses | **104 of 2,131 replays and 12 of 1,438 live tickets (6 distinct events) went past the line (as of 8 Oct 2026)** | [`/wrong`](https://nightwatch-gules.vercel.app/wrong) — every one of them, listed |
| We test the method itself, not just the trades | **11 internal studies: 3 yes, 5 no, 3 unclear** (a 12th study, against a random-hours baseline, is built and merged but has not yet run on production) | [`/studies`](https://nightwatch-gules.vercel.app/studies), corrected for multiple testing |
| Universe coverage | **24 tokenized US stocks live now** (configured for 112 — the throttled backfill in `docs/universe-expansion.md` hasn't run yet; check the real count live, not this line) | [`/api/universe`](https://nightwatch-gules.vercel.app/api/universe) |
| Not verified by us | real-trader adoption; directional edge (measured: **none**) | — said plainly, not hidden |

<p align="center">
  <img src="docs/img/calibration.png" alt="Track record page: 3,497 forecasts tested, the 1-in-20 warning beaten 3.5% of the time against a 5% target, and an honest 'not proven' badge where the evidence doesn't support a claim" width="860">
</p>

### Check them all in a minute

```bash
python scripts/verify_live.py     # standard library only; exit code 0 only if every line holds
```

It recomputes, from the live API, that the verdict log is unbroken and anchored in Bitcoin, the
blind check of the chat reader (misses included), the table above, and that the long weekend
record is present. Any failed line prints what the desk actually said.

### Claim boundaries

What each claim is, said before anyone has to ask.

| Claim | Status | Where to check |
|---|---|---|
| Every live verdict is written down, hash-chained and anchored in Bitcoin | **Proven**, recomputable | [`/api/verify`](https://nightwatch-gules.vercel.app/api/verify), [`/api/anchors`](https://nightwatch-gules.vercel.app/api/anchors) |
| The "1-in-20 bad case" line roughly holds | **Measured**: breach rate near the 5% target on thousands of scored forecasts, interval resampled by whole nights | [`/calibration`](https://nightwatch-gules.vercel.app/calibration) |
| We publish the forecasts that went past the line | **Proven**: every one is listed, with a CSV | [`/wrong`](https://nightwatch-gules.vercel.app/wrong), [`/api/ledger`](https://nightwatch-gules.vercel.app/api/ledger) |
| The chat reads trades correctly, in English and 中文 | **Measured**: blind set of 102 phrasings, misses published | [`/studies`](https://nightwatch-gules.vercel.app/studies) |
| Stress tests use the stock's long record, not only two years of token bars | **Measured**: daily bars back to 1990 for 112 stocks | [`/api/deep-history/NVDA`](https://nightwatch-gules.vercel.app/api/deep-history/NVDA) |
| Retrieval of past moments beats picking random hours | **Not proven**: closer in 45% of 2,280 pairs, shown in amber on the track-record page | [`/calibration`](https://nightwatch-gules.vercel.app/calibration) |
| A directional edge (it tells you which way to bet) | **Not claimed**: measured, none. It sizes risk, it does not predict | [`/studies`](https://nightwatch-gules.vercel.app/studies) |
| Real-trader adoption | **Not yet**: the validation plan is in [docs/submission.md](docs/submission.md) | - |
| Places or touches orders | **Never**: read-only by design | - |

A few choices we made against looking clever: weighting near-identical past moments more heavily made
the forecast worse (clustered t = -6.2, n = 958), so we shipped the version that doesn't; eleven of
twelve internal studies started as "yes" candidates and only those that survive
Benjamini-Hochberg correction are called findings; and the whole scored record is a file you can
recount. If a judge can break a claim, we would rather have broken it first and said so.

---

## The AI's job — and the line it is not allowed to cross

Bitget's own lesson from last season: *"LLMs are not fortune-tellers, but analysts."*
Nightwatch holds that literally:

* **An *analyst*** reads the finished, fully-computed report and says what matters most and
  what would change its mind — connecting facts, never inventing one.
* **An *agent*** turns a messy sentence into a structured trade, runs a bounded loop of real
  tool calls (the same engine a human would trigger), and answers follow-ups.
* **A *guard*** checks every number the AI writes against the report it was given. A
  sentence citing a number that isn't there gets deleted before you ever see it — and we
  log that it happened.

**The AI never computes a price, a percentile, a liquidation level, or a verdict.** Every
number on every page comes from deterministic code that is tested, versioned, and frozen
(`method-freeze-3`, see [`nightwatch/journal/method_freeze.json`](nightwatch/journal/method_freeze.json)) before it is ever
scored against reality. The AI's only job is to read, explain, and translate — the job it's
actually good at.

---

## Talk to it however you want

* **Web desk** — https://nightwatch-gules.vercel.app, live progress steps streamed while it
  thinks, chat cards under every follow-up, English and 中文.
* **Telegram bot** — ships in this repo, switches on when `TELEGRAM_BOT_TOKEN` is set. Say
  the trade in plain words ("long 20k NVDA over the weekend", "周末做多特斯拉 2万U") and get
  the same sized verdict the site gives.
* **Any AI tool, via MCP** (read-only; `stress_test`, `list_conditions`, `list_tokens`):

  ```bash
  claude mcp add nightwatch --transport http https://nightwatch-gules.vercel.app/api/mcp
  ```

* **As an Agent Hub-style skill**, the pre-trade check that runs *before* an order is
  drafted:

  ```bash
  mkdir -p ~/.claude/skills/nightwatch-stress-test
  curl -fsSL https://raw.githubusercontent.com/Ritik200238/nightwatch/main/skills/nightwatch-stress-test/SKILL.md \
    -o ~/.claude/skills/nightwatch-stress-test/SKILL.md
  ```

---

## How it works, end to end

1. **Retrieve.** Search the token's own hourly history (and pool across all 24 tokens when
   one token's own history is too thin to answer a specific condition) for moments that
   genuinely resemble now — matched on volatility state and the shape of the hold, not on
   features that happen to look the same across the whole market.
2. **Distribute.** Compute what actually followed those moments over the exact same hold —
   median, 1-in-20, sample size, confidence interval, and the share that went your way.
3. **Stress-test.** Run presets fitted from the token's *own* history (weekend gap,
   earnings gap, volatility spike, token-vs-fair-value blowout, a thin book, being stuck
   unable to exit), scaled to how many closed windows your hold actually crosses — plus
   real crash replays (COVID, the 2022 inflation shock, March 2023 bank failures, the
   August 2024 carry-trade unwind, the April 2025 tariff shock) and what the *options
   market itself* is pricing for the same window.
4. **Price the exit.** Walk Bitget's live order book for your exact size.
5. **Size it.** A rule gate — concentration, risk budget, liquidation, your own loss
   limits, a written "why" and "what proves me wrong" — decides the verdict. Every tail
   width is corrected by factors fit **only on earlier, already-scored forecasts** — never
   on the forecast being judged.
6. **Watch it.** Arm a price tripwire, save a pre-commit plan ("if X happens, cut half"),
   or let the desk re-check the verdict at the next close. Every verdict gets a permanent,
   shareable link.

Full technical writeup: [docs/features.md](docs/features.md) · [docs/submission.md](docs/submission.md)

<details>
<summary><b>Run it yourself (no API key required)</b></summary>

Python 3.11+ and Node 22+. Everything works with zero API key — a rule-based parser and
briefing stand in for the language model; set `ANTHROPIC_API_KEY` to turn on Claude for the
conversation layer.

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e ".[api,dev]"   # macOS/Linux: .venv/bin/python

nightwatch universe && nightwatch sync --core    # resumable; hours for 24 tokens
nightwatch calendars && nightwatch news
nightwatch record                                 # order books every minute, the rest on cadence

uvicorn nightwatch.api.app:app --port 8000
cd web && npm ci && cp .env.local.example .env.local && npm run build && npm start   # :3000
```

Containers: `docker compose up -d` after seeding the database (see [docs/deploy.md](docs/deploy.md)).

```bash
nightwatch analyze TSLA --side long --notional 20000 --equity 100000 --stop 350
nightwatch replay --tickers TSLA --max-points 100
nightwatch calibration --kind replay
nightwatch status
.venv/Scripts/python.exe -m pytest     # 1,500+ tests
```

</details>

---

## Repo layout

| path | what |
|---|---|
| `nightwatch/data` | Bitget, Yahoo, Nasdaq, FRED, RSS, SEC EDGAR, Cboe, corporate-events clients; SQLite store; sync |
| `nightwatch/features` | session calendar, basis, regime, event features, Bitget MCP data, point-in-time snapshots |
| `nightwatch/analog` | retrieval of past moments like now, forward outcomes, cohort statistics, random baseline |
| `nightwatch/stress` | fitted presets, block-bootstrap Monte Carlo, reverse stress, crash replays |
| `nightwatch/execution` | order-book walk, exit cost curve, perp hedge economics |
| `nightwatch/decision` | trade ticket, rule gate, sizing caps, thesis-vs-news check, verdict |
| `nightwatch/journal` | forecast journal, calibration tests, replay, tail adjustment, receipts |
| `nightwatch/api` | FastAPI app, the language layer, the MCP server |
| `web` | Next.js desk |
| `skills` | the Agent Hub-style skill |

Docs: [features, Bitget integration and numbers](docs/features.md) ·
[research notes](docs/research-notes.md) · [plain-language explainer](docs/nightwatch-explained.md) ·
[submission](docs/submission.md) · [demo script](docs/demo-script.md) · [deployment](docs/deploy.md) ·
[full product overview](Overview.md)

---

**Research tool. Nightwatch never places orders; the human decides. Every number is
computed from stored market data and labelled with its source.**
