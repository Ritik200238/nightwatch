# Submission drafts

Form: Bitget AI Base Camp Hackathon S2, deadline 2026-09-21 UTC+8.
Track: AI Trading Desk. Sub-theme: Decision Stress Testing.

Placeholders in `<angle brackets>` must be filled before submitting. Every number below is
labelled **observed** (measured on this build), **estimated**, or **targeted**.

---

## Field 1: Project Description

### 1. Thesis

Tokenized US stocks on Bitget trade 24/7. The underlying stocks trade 6.5 hours a day.
So for roughly 70% of every week, a position in RTSLAUSDT can move while the market that
sets its fair value is shut. Overnight and weekend news, earnings after the close, a
Sunday-night macro shock: the token prices all of it alone, on a thin book, with no way
to hedge in the real stock.

Existing tools do not help with this decision. Backtesters answer "would this strategy
have worked", not "what tends to happen after a moment like this one". Position-sizing
calculators assume a volatility number and ignore that the book can be five times
thinner at 3 a.m. on Sunday. Chat assistants give confident prose with no numbers anyone
can audit.

Nightwatch answers one question before a position is opened: **what happened after past
moments that looked like this, and can I survive the bad cases?** Given a trade idea, it:

1. Builds a point-in-time snapshot of the token: realised volatility and its percentile,
   trend, gap between token and fair value (basis) and its z-score, liquidity relative
   to normal, time-of-week, hours to the next earnings report and FOMC decision,
   headline count.
2. Retrieves the most similar past hours by Mahalanobis distance over those features,
   de-duplicated into distinct episodes, and refuses to answer when fewer than 15
   distinct matches exist.
3. Measures what followed each match over the trade's own horizon: return, worst
   point in the window, excess over the native stock, with bootstrap confidence
   intervals and a permutation test against random hours from the same time-of-week
   bucket.
4. Runs preset stress tests calibrated from the token's own history: closed-window gap
   percentiles, worst and typical earnings gaps, volatility spikes, basis blowouts,
   liquidity drought, cannot-exit-for-24h, funding spike on the hedge leg, plus a
   block-bootstrap Monte Carlo and a reverse stress ("what move loses 5%").
5. Walks the recorded live order book for the ticket size and quotes the real cost of
   getting out, and the cost of hedging with the perpetual.
6. Passes the ticket through an eight-rule discipline gate and five independent sizing
   caps, and returns a verdict: go, reduce to a size, hedge a ratio, or do not trade.

The core hypothesis is that a forecast which is never scored is a guess. So every
verdict is journaled before its outcome is known and scored when the horizon passes.
The calibration page shows whether 5% of outcomes really fall below the 5th
percentile. When they did not, the system fits tail-widening factors on past scored
forecasts only and applies them to new verdicts. Judges can see the before and after.

### 2. Target user and product value

**Segment:** retail and semi-professional discretionary traders who hold tokenized US
stock positions on Bitget through the US close, with 5,000 to 200,000 USDT per position,
trading a few times a week, primarily in the large-cap names (TSLA, NVDA, AAPL, MSFT,
AMZN, GOOGL, META) and leveraged ETFs (TQQQ, SQQQ). Risk appetite: willing to hold
overnight and over weekends, unwilling to be caught by a gap they never priced.

**Why they need it:** this trader's losses come from a small number of closed-market
events, not from average days. Nightwatch prices exactly those events, from this
token's own history, and tells them the size at which the worst preset stays inside
their loss limit. The verdict is a number they can act on, and every number carries its
source, sample size and confidence interval.

**Not for:** market makers, high-frequency systems, or anyone who wants an AI to place
orders. Nightwatch never places orders.

### 3. Validation data and key metrics

All figures **observed** on the build as of 2026-09-12 unless labelled otherwise.

* Data: 24 tokenized stocks with hourly bars from January 2025 (891,800 bars across
  spot, perpetual trade/index/mark and native), order-book snapshots recorded every 60
  seconds (48 books per tick), earnings and FOMC calendars, headline feeds.
* Forecast calibration, historical replay of 2,343 closed-market windows across 24
  tokens, every forecast scored against what actually happened:
  * Raw analog distribution: 8.7% of outcomes below the 5th percentile, 11.9% above the
    95th, 79.3% inside the band (targets 5 / 5 / 90). Kupiec failure-rate test p < 0.001.
    Tail band: red.
  * With tail factors fitted only on forecasts that had matured earlier (expanding
    window, out of sample, 2,299 forecasts): 5.0% below p5, 5.4% above p95, 89.5% inside
    the band. Tail band: green. The cost is sharpness: the honest band is 12.7 points
    wide instead of 8.3.
  * Median absolute error of the median forecast: 2.30 percentage points.
* Does the retrieval beat not bothering? Each replay point is paired with the
  distribution of random past hours from the same time-of-week bucket, and both are
  scored with the pinball loss on the same outcome (2,304 pairs). Averaged over the five
  quantiles the analogs are indistinguishable from random hours (skill −0.6%, CI −0.014
  to +0.004). At the 5th percentile they are better, with an interval that excludes zero
  (skill +4.8%, CI +0.003 to +0.033), and 8.6% of outcomes fall below the analog p5
  against 10.4% below the random-hours p5. **The analogs do not predict direction; they
  improve the loss tail.** That is the only claim this product makes, and the verdict
  never takes a direction from them.
* Exit cost: a 20,000 USDT RTSLAUSDT exit costs 25 bps on the recorded book (15 bps
  walk + 10 bps fee); the largest size that exits inside a 25 bps budget is ~16,800 USDT.
* Basis vs index is 2.5 times wider when the US market is closed than during regular
  hours (27.8 bps vs 10.9 bps, mean absolute, TSLA).
* Latency: a full verdict in 1.5 s after warm-up.
* Tests: 160 automated tests; lint, tests and the web build run in CI on every push.

**Usage validation plan (targeted):** demo live for the judging window; a public
calibration page that updates as live tickets mature; 20 external users submitting at
least one ticket during the window; every submitted ticket journaled and scored. Success
is a green tail band on live tickets after 100 matured forecasts.

### 4. Progress

**Built:** everything in section 1, end to end, with a web desk, a plain-language chat
entry, a CLI, a FastAPI service, an always-on recorder, and container images.

**Problems and fixes:** Bitget omits hourly bars when nothing traded, so gaps are
forward-filled and flagged rather than treated as flat hours. Earnings distance
dominated the similarity metric; capped at 30 days. Whitening blew up on constant
features; constants are dropped and eigenvalues floored. The first calibration run
showed tails too narrow; that became the tail-adjustment layer above. Bitget's free
research data hub answered the handshake but returned empty results; public REST
endpoints are used directly instead.

**Not built yet / next:** per-token tail factors once each token has enough scored
forecasts; a location correction (outcomes skew slightly above the forecast median);
feature weighting aimed at the loss tail, which is the only place the retrieval earns its
keep; funding as a similarity feature.

**Stack:** Python 3.11, numpy/pandas, SQLite, FastAPI; Next.js 16, Recharts; Claude
Opus 5 for the language layer only. Data: Bitget public API (spot, USDT perps with
index and mark candles, order books, funding), Yahoo chart API, Nasdaq earnings
calendar, FRED, RSS.

### 5. Deliverables

Behind the Submission Materials Link:

1. Live demo: https://nightwatch-gules.vercel.app — the desk, the calibration page and
   the journal. No login. Service health: https://nightwatch-gules.vercel.app/api/health
2. Source: `<GitHub URL>` (public). `README.md` has run instructions.
3. Screen recording: `<video URL>`, one complete research task: trade idea in, verdict
   out, calibration page.
4. `docs/research-notes.md`: the findings behind every preset and threshold, with
   reproduction commands.
5. Calibration evidence: `<demo URL>/calibration`, live, updates as forecasts mature.

### 6. Take on AI trading

The useful role for a language model on a trading desk is translation, not judgement:
turn a trader's sentence into a precise ticket, and turn a table of numbers into a
sentence the trader can act on. Every number should come from code that can be scored
against what actually happened. A model that is never scored is a model that is never
wrong, and that is the problem.

---

## Field 2: Role of the LLM in Your Project

Claude Opus 5 (Anthropic) does two things at run time, and nothing else.

1. **Intent parsing.** A trader types "long 20k TSLA into Monday, out if it loses 350".
   The model returns a structured ticket (token, side, size, horizon, stop, thesis,
   invalidation) using constrained structured output, and asks for any missing field.
2. **Narration.** After the numeric pipeline produces the report, the model writes a
   short plain-language summary. Every number in that summary is checked against the
   report; any number that does not appear in the report is flagged as unverified in the
   interface.

The model does not retrieve analogs, compute statistics, run stress tests, size the
position, or issue the verdict. Those are deterministic code and are journaled and scored
independently of the model. The desk works fully without an API key; only the chat entry
needs one.

During development, Claude Code was used as a coding assistant. No Qwen credits were
used.

---

## Field 3: Submission Materials Link

One page (GitHub README or a short Notion page) linking: demo, API health, repository,
video, research notes, calibration page.

---

## X post draft

> Tokenized US stocks trade 24/7. The stock behind them trades 6.5 hours a day.
> Nightwatch stress-tests a trade before you place it: finds the past moments that
> looked like now, shows what followed (with sample sizes), runs gap/earnings/liquidity
> stress from the token's own history, walks the live book for your exit, and sizes the
> verdict. Every forecast is journaled and scored, so you can see when it is wrong.
> Try it: <demo URL>
> #BitgetHackathon @Bitget_AI

Attach: a screenshot of a verdict and one of the calibration page.

---

## Pre-submission checklist

- [ ] Demo reachable over HTTPS; `/health` green; recorder heartbeat advancing
- [ ] Repository public (or judge-accessible); README run instructions verified on a clean machine
- [ ] Video recorded and linked
- [ ] Placeholders above filled; "to be measured" numbers measured or removed
- [ ] X post published with `#BitgetHackathon` and `@Bitget_AI`
- [ ] Form: track AI Trading Desk, sub-theme Decision Stress Testing
- [ ] University name (optional), Demo Day (optional)
