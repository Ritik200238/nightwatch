# Submission drafts

Form: Bitget AI Base Camp Hackathon S2. Track: AI Trading Desk.
Sub-theme: **Decision Stress Testing** — one winner, so this is the only box that matters.

Track 3 is judged 100% subjectively, and parts 1-3 of the Project Description carry the
most weight. Field 1 and Field 2 below are written to be pasted into the form verbatim.

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
   distinct matches exist. The retrieved moments are shown as paths, not just as a
   summary: forty past windows replayed from their own entry over the same holding
   period, with the outcome fan and the trader's own stop drawn across them, so the
   answer includes how many of them would have taken the stop out on the way.
3. **Lets the trader change what counts as comparable, in words.** "Only show me what
   happened on earnings nights" narrows the searched history *before* the ranking runs,
   so the answer is the forty nearest earnings nights rather than the survivors of an
   unfiltered search - two different cohorts, and only the first answers the question.
   Seventeen named conditions; the model picks names from that list and never writes a
   threshold or a column, so each one prints the predicate it resolved to next to the
   result. Narrowing costs evidence and the desk says what it cost: TSLA's own past holds
   96 hours with earnings ahead against 1,752 across the universe, which is why that
   question is answered from the pooled history and the page says so. Asking for
   something too rare - FOMC ahead *and* volatile, 44 hours out of 15,129 - is refused
   rather than answered from a handful of hours.
4. Measures what followed each match over the trade's own horizon: return, worst
   point in the window, excess over the native stock, with bootstrap confidence
   intervals and a permutation test against random hours from the same time-of-week
   bucket.
5. Runs preset stress tests calibrated from the token's own history: closed-window gap
   percentiles, worst and typical earnings gaps, volatility spikes, basis blowouts,
   liquidity drought, cannot-exit-for-24h, funding spike on the hedge leg, plus a
   block-bootstrap Monte Carlo and a reverse stress ("what move loses 5%").
6. Walks the recorded live order book for the ticket size and quotes the real cost of
   getting out, and the cost of hedging with the perpetual.
7. Reads any SEC filing the market has not opened since. 99% of the 8-Ks in this
   history landed while the US market was shut, and until now the desk only knew *when*
   one arrived — item 5.02 covers a routine board appointment and a chief executive
   resigning overnight. A model reads the filing's own words and says what it is and how
   much it matters; the number beside it is not the model's, but what this token's own
   bars did after every other filing given that same label.
8. Passes the ticket through a nine-rule discipline gate and five independent sizing
   caps, and returns a verdict: go, reduce to a size, hedge a ratio, or do not trade.
   The gate is built to decide, not to abstain: where a missing input is a caution rather
   than a danger - no stop given, thin weekend trading - it says so in the verdict and
   sizes against the calibrated 5th percentile instead of refusing.
9. **Re-runs itself when the trader asks a what-if.** "What if I only held it six
   hours?", "was it worse on earnings nights?" - none of those are a rearrangement of a
   report that has already been computed, so the desk computes another one against the
   same moment. The model names what changed, from a fixed set of fields; the engine does
   everything that follows and the comparison is assembled from the two reports' own
   fields. What moves is not only the distribution. On TSLA at 2026-09-19T02:00Z, 60,000
   USDT requested against 200,000 of equity, narrowing to earnings nights takes the 5th
   percentile from **-3.33% to -10.72%** and the size the desk will allow from **50,000
   to 18,655 USDT**, with the binding cap changing from concentration to the risk budget.
   Both runs are reproducible against the public API by passing `lenses` and that `as_of`.

The core hypothesis is that a forecast which is never scored is a guess. So every
verdict is journaled before its outcome is known and scored when the horizon passes. The
calibration page shows whether 5% of outcomes really fall below the 5th percentile. When
they did not, the system fits tail-widening factors on past scored forecasts only and
applies them to new verdicts. Judges can see the before and after.

The second hypothesis follows from the first, and is the one we would most like to be
judged on: **if a forecast that is never scored is a guess, so is a retrieval engine that
is never tested.** So the engine is put through the same treatment as its own forecasts.
Ten falsifiable questions about it — does closeness predict a tighter outcome, does
weighting the close matches help, does one tail factor fit every holding period, does a
model reading a filing spot a night that matters, does narrowing the search to the nights
a trader asks about give a truer loss tail — each recomputed from the stored data, each
published whichever way it came out. Five came back no, including the one that would
have made the product look cleverer, two could not be decided, and each one says what
changed because of it. The
page is at `/studies` and the failures are the point of it.

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

All figures **observed** on the build as of 2026-09-22 unless labelled otherwise.

* Data: 24 tokenized stocks with hourly bars from January 2025 (909,890 bars across
  spot, perpetual trade/index/mark and native), 43,691 order-book snapshots recorded
  every 60 seconds, 3,020 SEC filings, 4,128 earnings dates, 19,959 macro observations.
* Forecast calibration, historical replay of 2,345 closed-market windows across 24
  tokens, every forecast scored against what actually happened:
  * Raw analog distribution: 8.5% of outcomes below the 5th percentile, 10.3% above the
    95th, 81.0% inside the band (targets 5 / 5 / 90). Kupiec failure-rate test p < 0.001.
    Tail band: red. The median is inside its interval, so the centre is right and the
    tails are not.
  * With tail factors fitted only on forecasts that had matured earlier (expanding
    window, out of sample, 2,301 forecasts): **5.6% below p5, 5.8% above p95.** Tail
    band: amber — most of the way from red, not all of it. Aiming the fit slightly under
    5% would show green, and would be choosing the target by looking at the
    out-of-sample answer, so it was not done.
  * **That pooled number was hiding two opposite errors, and we found it by testing for
    it.** One tail factor was fitted across every holding period. Split by how long the
    position is actually held, the same 2,301 forecasts read: **7.1% breaches on
    overnight holds, and 0.2% on multi-day ones inside a band 20.0 points wide** — a
    weekend band so over-wide it broke twice in 468 forecasts, cancelling out an
    overnight band that was too narrow. Two wrongs averaging to look right is worse than
    either alone, because the headline hides both.
  * Fitting per holding period fixed both: **overnight now 5.1% and green on 1,718
    forecasts; multi-day 6.5% in a 10.6-point band instead of 20.0.** The remaining
    breaches sit in the 230 earliest forecasts, made before either band had enough
    history to fit on, and those are shown on the page rather than dropped.
  * **This changed what a trader is told.** Checked end to end through the gate: TSLA, a
    Saturday, 60,000 USDT requested, no stop, 200,000 equity. The analog 5th percentile
    the desk sizes against moved from −8.38% to −4.76%, and the binding risk-budget cap
    from **23,880 to 42,011 USDT**. The desk had been cutting weekend positions by 43%
    against a loss the history does not support.
  * Median absolute error of the median forecast: 2.22 percentage points.
* **We tested the retrieval itself, and published what failed.** Ten falsifiable
  questions about the engine, each recomputed from the stored bars and the journal by
  `nightwatch studies`, each reported whichever way it came out. **Five came back no and
  two could not be decided.** The two that cost us most:
  * *Do closer analogs have tighter outcomes?* **No — the opposite.** The near half of a
    retrieval is 14% wider by standard deviation and 22% by interquartile range, and
    **not one of 24 tokens goes the other way** (clustered t = −6.59, n = 960). The
    distance is dominated by the volatility features, so a query made in a wild moment
    retrieves wild neighbours.
  * *So should closer analogs count for more?* **No.** None of four weighting schemes
    beat counting every match equally, and the engine's own similarity weights — already
    computed in the codebase since the beginning — push the 5th percentile in far enough
    to breach **11.0% of the time against 5.9%**, at a 5% target. Wiring in the obvious
    improvement would have broken the calibration the desk is judged on. Those fields
    stay computed and unread, which is now a measurement rather than an oversight.
  * A "we have never seen anything like this" warning looked significant at t = +3.60
    and died at t = −0.07 once clustered by token: it was measuring which tokens are
    volatile, not which moments are unfamiliar. Not shipped.
  * An online conformal update (Gibbs & Candès), the published fix for our exact
    symptom, gave 4.43% against 4.43% on a held-out half. Not adopted. Chosen on the
    whole sample instead it would have read amber → green, which is what picking a
    hyperparameter on the data you report it against buys you.
* **Narrowing the search is scored, not assumed.** Every past overnight hold where a
  condition was true, 1,419 of them across 24 tokens, with the desk's 5th percentile
  computed twice from the history before that moment: once from all past hours, once
  from only the hours where the condition also held. On nights with earnings due within
  three days the unfiltered tail was breached **22.0%** of the time against a 5% target;
  the narrowed one **7.0%** (n = 100, 12 of 18 tokens better, clustered t = +2.9). On the
  night before earnings itself it was **54.2% against 4.2%** — but on 24 nights, under the
  30-night bar set before the run, so it is reported and not counted. Volatile nights
  improved narrowly (15.8% to 13.9%, t = +2.0); five other conditions showed no separable
  difference, and none scored worse. The same sweep found a bug: "FOMC ahead" had enough
  hours but only a dozen separate meeting dates on 471 of 474 nights, and the desk used to
  return no history at all for it. It now answers unfiltered and says why.
* Does the retrieval beat not bothering? Each replay point is paired with the
  distribution of random past hours from the same time-of-week bucket, and both are
  scored with the pinball loss on the same outcome (2,325 pairs). Averaged over the five
  quantiles the analogs are indistinguishable from random hours (skill −0.8%, CI −0.015
  to +0.003). The one place they help is the loss tail: 8.4% of outcomes fall below the
  analog 5th percentile against 10.2% below the random-hours one, and the pinball gain at
  p5 is +4.0% with an interval that excludes zero — though on three of the five engines
  this has been re-scored on, it did not. **The analogs do not
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
* **Reading the filings, not just timing them.** 99% of the 8-Ks in this history (480 of
  486) were accepted while the US market was shut. Qwen 3.8 Max read 682 of them from
  their own text (2.55M tokens) and labelled how likely each was to move the stock.
  Scored against what the token then did before the next open: filings it flagged were
  followed by a **2.66% move against 1.64%, 1.62× larger, on 18 of 20 tokens**
  (clustered t = +4.07, n = 622). A filing it calls high-impact carries a −6.60% 5th
  percentile against −3.37% for one it calls routine — roughly double the tail. Its
  **directional** call measured **49.5% on 202 calls, interval [42.7%, 56.3%]**, so it
  is shown nowhere and reaches nothing.
* Tests: 390 automated tests; lint, tests and the web build run in CI on every push, and
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

**Stack:** Python 3.11, numpy/pandas, SQLite, FastAPI; Next.js 16, Recharts. Two models,
neither of which produces a number: Qwen 3.8 Max reads SEC filings, Claude Opus 5 parses
intent and narrates. Six live data sources, all listed with their
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
5. Calibration evidence: https://nightwatch-gules.vercel.app/calibration, live, updates
   as forecasts mature — including the split by holding period, where the pooled figure
   was hiding two opposite errors.
6. **What we tested about our own retrieval:**
   https://nightwatch-gules.vercel.app/studies — ten falsifiable questions about the
   engine, five answered no and two undecided, each with the method, the numbers and what changed in the
   product because of it. Recomputed by `nightwatch studies`; nothing on it is typed in.
7. One worked verdict, fixed in place: `https://nightwatch-gules.vercel.app/r/<forecast id>`. Every analysis the
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

**The deployed demo runs on Qwen 3.8 Max.** Four jobs, one rule that governs all of
them: **a model may read text, choose from a vocabulary this codebase defines, and write
English. It may not produce a number, write a filter, or pick a threshold.** Every figure
in the product comes from stored market data or from a measurement over it, and every
condition the search can be narrowed to is a predicate written in Python with its
definition printed next to the result.

That second clause is the one we would most like to be argued with. The sub-theme asks
how AI retrieves historically similar scenarios, and the tempting answer is to let a
model write the query. We think that is the wrong answer: a model that can write a filter
can write one that flatters the result, and nobody reading the output can see what it
did. So the model picks *names* - "earnings_soon", "thin_liquidity" - from a fixed list
of seventeen, and each name resolves to a predicate a reader can check. The model decides
**which history is comparable**. It never decides what comparable means.

Every one of the four jobs is also *scored or bounded*, never asserted. The filing
judgement is graded against what the token actually did. The speed of writing was
measured and found wanting, so that job stayed on the rules. The retrieval vocabulary is
closed, and a name outside it is dropped before the engine sees it. And a what-if runs
the real engine, so its numbers are the desk's, not the model's.

### Qwen 3.8 Max — reading the filings (Alibaba Cloud, via the Bitget hackathon gateway)

This is the job we could not do without a model, and it is the one the product needed
most. 99% of the 8-Ks in our history (480 of 486) were accepted while the US market was
shut. That is the entire reason this product exists — the stock cannot react and the
token can — and until we had Qwen the desk only knew *when* a filing landed, never what
it said. SEC item 5.02 covers a routine board appointment and a chief executive resigning
overnight; "hours since the last filing" treats them identically.

Qwen reads each filing's own text from EDGAR and returns four things: a category, a
one-line headline, how likely it is to move the share price, and which way. It never sees
a price and never sees what happened afterwards, so a read is information that existed
when the filing became public.

**682 filings read, 2,553,333 tokens** (1,871,729 prompt + 681,604 completion).

Its judgement is then **scored, not trusted**. Each read is stored against the filing and
joined to what the token actually did before the next US open:

| what Qwen said | n | mean overnight move | 5th percentile |
|---|---|---|---|
| high | 146 | 3.15% | −6.60% |
| medium | 119 | 2.06% | −5.94% |
| low | 218 | 1.55% | −3.66% |
| none | 139 | 1.79% | −3.37% |

Flagged (high + medium) against the rest: **2.66% vs 1.64%, a 1.62× larger move, holding
on 18 of 20 tokens, clustered t = +4.07** (observed). So the read appears on the report,
next to the measured distribution for that label — roughly double the tail for a filing
it calls high-impact.

Its **directional** call was measured the same way and came back at **49.5% correct on
202 calls, interval [42.7%, 56.3%]** (observed) — a coin. So it is not shown anywhere and
reaches nothing. Both results are published on the Studies page as studies 8 and 9.

**Did Qwen meet our needs?** Yes, for this job. The reads are accurate by eye — it
separated three MicroStrategy financings from each other and caught that Meta's strong
quarter was offset by capex guidance — and it follows a hard instruction to decline
rather than guess, answering "unclear" on two thirds of filings. Two caveats worth
reporting: its content filter rejected **31 of 706** legitimate SEC filings as
"inappropriate content" (`DataInspectionFailed`, mostly TSM), and it is a reasoning model
that returns its thinking in a separate field, so a naive integration reads the wrong one.
Both were handled; neither is a reason not to use it.

### Qwen 3.8 Max — understanding the trader (live in the demo)

The same model also runs the chat. A trader types

> *"im nervous about the fed thing wednesday, thinking 15k nvidia short overnight"*

and Qwen returns NVDA, **short**, 15,000 USDT, held to the next US open, with the thesis
kept — in 12 seconds, from lowercase, unpunctuated text with the direction buried mid
sentence. The rule-based parser underneath it reads the shapes traders usually type and
would have missed that one. `GET /health` names the provider and model, so anyone can
check which is answering.

### Qwen 3.8 Max — steering the retrieval (live in the demo)

This is the sub-theme's own question, so it is the job we care most about. A trader who
is carrying a position into an earnings night does not want the average of every night.
Those are two different distributions, and until this layer existed there was no way to
ask for the second one.

> *"only show me what happened on earnings nights"* → `["earnings_soon"]`
> *"only compare against weekends when the book was thin"* → `["weekend", "thin_liquidity"]`
> *"long 20k TSLA into Monday"* → `[]`

Names, not filters. The model is shown seventeen conditions with their definitions and
the phrasings traders use for them, and returns names from that list. A name it invents
is resolved away before the engine sees it. The instruction is explicit that describing a
situation is not asking for a filter - a trader saying "earnings are tomorrow" wants the
general answer with that fact in view - and the third example above is the model getting
that right.

The narrowing then happens **before** the ranking, not after it. Filtering the matches
that come back from an unfiltered search would give the survivors of the wrong ranking:
the forty nearest hours overall, minus the ones that were not earnings nights. What the
trader asked for is the forty nearest earnings nights, which is a different set.

What it costs is on the page, because narrowing thins the evidence fast:

| asked for | hours left | searched | 5th percentile | size allowed |
|---|---|---|---|---|
| nothing | 15,026 of 15,026 | TSLA's own past | −3.33% | 50,000 USDT |
| thin book | 2,829 of 15,026 | TSLA's own past | −2.53% | 50,000 USDT |
| earnings ahead | 1,752 of 323,520 | pooled, 24 tokens | **−10.72%** | **18,655 USDT** |
| FOMC ahead **and** volatile | 44 of 15,026 | refused | — | — |

(TSLA, `as_of` 2026-09-19T02:00Z, 60,000 USDT requested against 200,000 of equity;
observed, and reproducible against the public API.) Two things there matter more than the
numbers. TSLA's own history holds 96 hours with earnings ahead, which is not enough to
build a distribution from, so the desk widens to the pooled history across 24 tokens and
*says on the page that it did*. And "FOMC ahead and volatile" leaves 44 hours out of
15,129, so it is **refused** — the desk answers the unfiltered question out loud instead
of quietly passing off a distribution built from 44 hours as the answer to a narrower
question. Being told there is not enough evidence is a correct outcome, and the common one.

### Qwen 3.8 Max — running the counterfactual (live in the demo)

The report on screen can be quoted and rearranged, and thirteen kinds of follow-up are
answered that way with no model involved. *"What if I only held it six hours?"* is not
one of them: it is a different report. So the model names what changed - from a closed
set of five fields, the same restraint as the lenses - and the engine runs a second,
complete analysis against the same moment. The comparison a trader reads is assembled
from the two reports' own fields, which is why the answer carries no unverified numbers:
there is no step at which one could be written. A test asserts that by running the
comparison through the same invented-number check the narrator is held to.

Two deliberate limits. A what-if is never journalled, because a forecast nobody took
should not be scored, and a cohort narrowed by a lens is a different estimator from the
one that sizes real trades - scoring them together would corrupt the calibration both
depend on. And size and stop are not variable here, because the sensitivity sweep already
ran the whole gate across a grid of both; re-running for those would be slower and no
more correct.

### What the model is *not* allowed to do, measured rather than asserted

Qwen reasons before it answers, and here the reasoning dominates: rewriting a full report
took **88 seconds**, with 3,311 of 3,562 completion tokens spent thinking, against a
gateway that returns 504 at about 120. Stripped to a 739-character digest and a lean
instruction it still took 34.

Thirty-four seconds to rephrase text the desk already has instantly is a bad trade, so
the written briefing stays on the deterministic path — assembled from the report's own
fields, which is structurally incapable of inventing a number. The provider declares
`narrates=False` and the response says `parsed_by: qwen, written_by: rules`. **The desk
never makes a person wait on a model.**

### Claude Opus 5 — supported, second in line (Anthropic)

The layer is provider-shaped, not vendor-shaped. With an Anthropic key present, Claude
takes both jobs including the briefing, and every number it prints is checked against the
report — an answer containing a figure the report does not contain is **discarded**, not
flagged, and the deterministic answer ships instead. The deployed demo runs on Qwen.

### What no model does

Retrieval, cohort statistics, calibration, stress presets, Monte Carlo, order-book
walking, the discipline gate, the sizing caps, and the verdict. All deterministic, all
journaled, all scored independently of any model.

That holds even where a model steers. When the search is narrowed, the model has supplied
a list of names and nothing else: the predicates, the distance metric, the episode
de-duplication, the minimum sample, the refusal rule and every statistic on the far side
are the same code that runs when nobody asks for anything. The model changes which rows
are searched. It does not touch how they are ranked or what is measured about them.

Both language jobs also have a rule-based implementation, and the desk falls back to it
when no provider has credentials or the provider is unreachable. The parser reads the shapes a trader
actually types, names any field it is missing rather than guessing, and invents nothing.
The briefing is assembled from the report's own fields, so the rule the model is held to
is structurally unbreakable there. The response says which one answered. The point is not
that rules are as good as the model; it is that the desk has no single point of failure.

During development, Claude Code was used as a coding assistant.

---

## Field 3: Submission Materials Link

One page (GitHub README or a short Notion page) linking: demo, API health, repository,
video, research notes, calibration page.

---

## X post draft

A thread, not a single post: reach is judged, and the honest-failure angle is the part
people actually repost. Post 1 must carry the hashtag and the handle — that is the
compliance requirement and a reply does not satisfy it.

**1/**

> We built a decision stress tester for tokenized US stocks, then tested the engine
> itself with 10 falsifiable questions.
>
> 5 came back NO. 2 we could not decide.
>
> Including the one that would have made us look clever. All of them are published.
>
> https://nightwatch-gules.vercel.app/studies
> #BitgetHackathon @Bitget_AI

*Attach: screenshot of the Studies scoreboard — 10 asked, 3 yes, 5 no, 2 cannot tell yet.*

**2/**

> The one that hurt: everyone assumes the closest historical matches are the most
> informative.
>
> We checked. The near half of a retrieval has **wider** outcomes than the far half.
> 14% by std dev. Not 1 of 24 tokens goes the other way.
>
> So weighting the close ones more makes the forecast measurably worse.

**3/**

> We had those weights already computed, sitting in the code.
>
> Wiring them in would have doubled the rate the real outcome falls outside our band
> (11.0% vs 5.9%, target 5%).
>
> They stay unused. That is now a measurement, not an oversight.

**4/**

> The test that found a real bug: one tail factor was serving every holding period.
>
> Overall it read 5.6% — respectable. Underneath: 7.1% breaches overnight, 0.2% on
> weekends inside a band 2x too wide.
>
> Two wrongs averaging to look right.

**5/**

> Fixed, and it changed what a trader is told. A 60k weekend hold with no stop was
> capped at 23,880 USDT. Now 42,011.
>
> We were cutting weekend positions by 43% against a loss the history doesn't support.

**6/**

> Why this product exists: 99% of the 8-Ks in our history landed while the US market was
> SHUT.
>
> The stock can't react. The token can.
>
> Qwen 3.8 Max reads each filing's text. Filings it flags precede a 1.62x larger
> overnight move, on 18 of 20 tokens.

**7/**

> It also calls a direction. That measured 49.5% against a coin.
>
> So we don't show it. Anywhere.
>
> A model may read text and write English here. It may not produce a number that reaches
> a decision.

**8/**

> Live, no login, nothing to install:
> https://nightwatch-gules.vercel.app
>
> Calibration (still amber, and it says so):
> https://nightwatch-gules.vercel.app/calibration
>
> Code: https://github.com/Ritik200238/nightwatch

*Also required, separately from your own post: retweet the official Bitget post.*

---

## Pre-submission checklist

Done:

- [x] Demo reachable over HTTPS; `/health` green; recorder heartbeat advancing
- [x] Repository public; README run instructions verified by cloning it cold (14 Sep):
      lint clean, CLI runs, web builds. 390 tests green as of 22 Sep
- [x] Every feed live and fresh, visible at `/api/sources` and on the desk
- [x] Links filled in: demo, health, sources, repository, calibration
- [x] Uptime check every 15 minutes through the judging window; the box restarts a
      container that is running but unhealthy

Left, and each one needs a person:

- [ ] **Video recorded and linked** — script in `docs/demo-script.md`, record against the
      live URL, then paste the link here and in the form
- [ ] **The worked verdict**: after the take, click "copy link" in the report footer and
      put that `/r/<id>` link in deliverable 6
- [ ] **X post** published — thread drafted above. Post 1 carries `#BitgetHackathon`
      and `@Bitget_AI`; a reply does not satisfy that. **Missing or non-compliant makes
      the whole submission ineligible for review**, so do this one first
- [ ] **Retweet the official Bitget post** — separate requirement from your own post
- [ ] **Form**: track AI Trading Desk, sub-theme Decision Stress Testing. Paste Field 1
      and Field 2 from this document verbatim; they are written to the form's own six
      parts and the LLM field is now a scored strength rather than a footnote
- [ ] **Qwen usage is in Field 2** and is worth points: the form asks explicitly where
      Qwen was used and whether it met your needs. Both answered, with the token count
      and the two caveats
- [ ] University name (optional), Demo Day (optional)
- [ ] **AWS budget alert** still emails the wrong address; change it to
      ritik.pandey72@gmail.com in the console
- [ ] *Optional*: set `ANTHROPIC_API_KEY` in `/home/ubuntu/nightwatch/.env` and
      `docker compose up -d api` — the chat already works without it, but the model reads
      a sentence with more range than the parser does
