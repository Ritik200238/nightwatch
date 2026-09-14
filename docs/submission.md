# Submission drafts

Form: Bitget AI Base Camp Hackathon S2, deadline 2026-09-21 UTC+8.
Track: AI Trading Desk. Sub-theme: Decision Stress Testing.

Two placeholders are left, both waiting on the recording: `<video URL>` and the forecast
id of the verdict shown in it. Everything else is filled in. Every number below is
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
   to normal (measured against the same hour of the week, so a quiet Sunday is not
   mistaken for a liquidity crisis), time-of-week, hours to the next earnings report and
   FOMC decision, headline count, hours since the last SEC filing, and the macro weather
   (VIX, the yield curve, the dollar, the 10-year, each as a percentile of its own
   trailing year).
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
6. Passes the ticket through a nine-rule discipline gate and five independent sizing
   caps, and returns a verdict: go, reduce to a size, hedge a ratio, or do not trade.
   The gate is built to decide, not to abstain: where a missing input is a caution rather
   than a danger - no stop given, thin weekend trading - it says so in the verdict and
   sizes against the calibrated 5th percentile instead of refusing.

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
* Forecast calibration, historical replay of 2,345 closed-market windows across 24
  tokens, every forecast scored against what actually happened:
  * Raw analog distribution: 8.5% of outcomes below the 5th percentile, 10.1% above the
    95th, 81.1% inside the band (targets 5 / 5 / 90). Kupiec failure-rate test p < 0.001.
    Tail band: red. The median is inside its interval, so the centre is right and the
    tails are not.
  * With tail factors fitted only on forecasts that had matured earlier (expanding
    window, out of sample, 2,301 forecasts): 5.6% below p5, 5.6% above p95, 88.7% inside
    the band. Tail band: amber — most of the way from red, not all of it. Aiming the fit
    slightly under 5% would show green, and would be choosing the target by looking at
    the out-of-sample answer, so it was not done. The cost of the widening is sharpness:
    the honest band is 12.9 points wide instead of 8.5.
  * Scored month by month, the gap to 90% coverage closes by about 2.9 points per month.
    The journal's first month has too little history to fit the factors and breached
    11.5%; June breached 11.7% even with them. The page says both.
  * Median absolute error of the median forecast: 2.22 percentage points.
* Does the retrieval beat not bothering? Each replay point is paired with the
  distribution of random past hours from the same time-of-week bucket, and both are
  scored with the pinball loss on the same outcome (2,328 pairs). Averaged over the five
  quantiles the analogs are indistinguishable from random hours (skill −1.0%, CI −0.017
  to +0.002). The one place they help is the loss tail: 8.5% of outcomes fall below the
  analog 5th percentile against 10.3% below the random-hours one. **The analogs do not
  predict direction; they improve the loss tail.** That is the only claim this product
  makes, and the verdict never takes a direction from them.
* Whether a feature joins the search is decided by measurement. The macro layer was
  tested three times: 95 pairs showed nothing, 453 showed a favourable direction with
  intervals spanning zero, and 1,605 pairs across 20 tokens showed a 1.3% lower forecast
  loss with an interval excluding zero. It ships on the third result;
  `research/feature_ab.py` reruns the test.
* Exit cost is quoted from the live book, not assumed: on 14 September a 20,000 USDT
  RTSLAUSDT exit cost 15.1 bps (5.1 walk + 10 fee) and the largest size that exits inside
  a 25 bps budget was 193,000 USDT. The same book read by time of week is thinner at the
  weekend: the recorded archive could not absorb 20,000 within budget 35% of the time on
  a weekend, against 0% on a weeknight.
* Basis vs index is 2.5 times wider when the US market is closed than during regular
  hours (27.8 bps vs 10.9 bps, mean absolute, TSLA).
* Latency: a full verdict in about 2.1 s on the server after warm-up (analog retrieval
  is 1.6 s of it), 2.4-3.1 s end to end through the public URL. The first request after a
  deploy is slower while the feature cache rebuilds, and the API says so in `/health`.
* Tests: 265 automated tests; lint, tests and the web build run in CI on every push, and
  the backend only deploys a commit whose CI passed. A cron job restarts a container that
  is running but unhealthy, because judging runs for two weeks unattended.

**Usage validation plan (targeted):** demo live for the judging window; a public
calibration page that updates as live tickets mature; 20 external users submitting at
least one ticket during the window; every submitted ticket journaled and scored. Success
is a green tail band on live tickets after 100 matured forecasts.

### 4. Progress

**Built and live:** everything in section 1, plus a layer that most tools stop short of.
Every matured forecast writes a post-mortem in plain language, classified against the
band it stated beforehand, and the desk recalls the relevant ones for the ticket in front
of you. A circuit breaker counts realised losses on trades the trader marked as taken and
refuses new ones past daily, weekly or monthly limits. Calibration is scored month by
month, not once. Given the rest of the book it measures correlation from the tokens' own
history and says which position carries the bad case. A regime map groups past hours into
states and reports what followed each. The recorded order-book archive is read back by
time of week. And every report argues against its own verdict using its own numbers.

**Problems and fixes:** Bitget omits hourly bars when nothing traded, so gaps are
forward-filled and flagged rather than treated as flat hours. Two consequences of that
took a while to find, and both were measurement errors rather than market facts: realised
volatility computed over calendar hours went blank after half a day of no trades, taking
the regime label with it, and liquidity compared against a flat 30-day average made every
weekend look like a crisis - 15 of 48 test tickets came back "hostile regime, review" for
no better reason than that it was Sunday. Volatility is now measured over traded hours and
carried forward; liquidity is compared against the same hour of the week. Earnings distance dominated
the similarity metric; capped at 30 days. Whitening blew up on constant features. The
first calibration run showed tails too narrow, which became the tail-adjustment layer.
A token that has gone quiet used to be refused outright; it is now analysed with a flag
that forces the gate to ask, because "this has not traded for fourteen hours" is the most
useful thing to say about it. Bitget's research data hub answers the handshake but
returns empty results, so public REST endpoints are used directly.

**Deployment:** the desk is on Vercel and the backend on one small always-on box. A push
to the main branch reaches both: the box only deploys a commit whose CI run passed and
rolls itself back if the new build fails its health check. A scheduled job checks every
fifteen minutes that the desk loads, the API answers, the recorder is still writing and a
verdict still comes back.

**Not built:** funding as a similarity feature, because Bitget's public funding history
stops at 90 days and the search covers twenty months; it would have to be imputed. Per
token tail factors, until each token has enough scored forecasts of its own.

**Stack:** Python 3.11, numpy/pandas, SQLite, FastAPI; Next.js 16, Recharts; Claude
Opus 5 for the language layer only. Six live data sources, all listed with their
freshness on the desk itself and at `/sources`: Bitget public API (spot, USDT perps with
index and mark candles, order books, funding), Yahoo chart API, Nasdaq earnings calendar,
FRED, RSS headlines, and SEC EDGAR filings timed to the second they were accepted.

### 5. Deliverables

Behind the Submission Materials Link:

1. Live demo: https://nightwatch-gules.vercel.app — the desk, the calibration page and
   the journal. No login. Service health: https://nightwatch-gules.vercel.app/api/health,
   and every upstream feed with its freshness at
   https://nightwatch-gules.vercel.app/api/sources
2. Source: https://github.com/Ritik200238/nightwatch (public). `README.md` has run instructions.
3. Screen recording: `<video URL>`, one complete research task: trade idea in, verdict
   out, calibration page.
4. `docs/research-notes.md`: the findings behind every preset and threshold, with
   reproduction commands.
5. Calibration evidence: https://nightwatch-gules.vercel.app/calibration, live, updates as forecasts mature.
6. One worked verdict, fixed in place: `https://nightwatch-gules.vercel.app/r/<forecast id>`. Every analysis the
   desk produces gets a link that reopens it exactly as it was argued — same analogs,
   same stress table, same order book, same hash of the inputs, nothing recomputed. Run
   the trade in the recording, then paste its link here, so a judge can read the argument
   rather than trust a screenshot of it.

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
independently of the model.

Both of those jobs also have a rule-based implementation, and the desk falls back to it
when there is no API key or the provider is unreachable. The parser reads the shapes a
trader actually types ("long 25k TSLA overnight, stop 340"), names any field it is
missing rather than guessing it, and invents nothing — no thesis, no stop, no size the
trader did not state. The briefing is assembled from the report's own fields, so the rule
the model is held to is structurally unbreakable there. The response says which one
answered. The point is not that rules are as good as the model; it is that the desk has
no single point of failure, and every number on it has one source either way.

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
> Try it: https://nightwatch-gules.vercel.app
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
