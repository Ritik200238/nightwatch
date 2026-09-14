# Research notes — measured facts behind Nightwatch

Every number here was computed from stored data with the code in this repository and
is labelled **observed** unless stated otherwise. Dates are UTC. Re-run instructions
are given so any figure can be reproduced.

## 1. The tokenized-stock universe on Bitget (observed 2026-09-12)

* **1,173 tokenized US stocks/ETFs on spot** (symbols `R<TICKER>USDT`, base coin
  `r<TICKER>`), all with non-zero 24h volume. Not "a couple of dozen".
* **321 perpetuals carry Bitget's `isRwa` flag**, but that flag also covers FX pairs,
  metals, indices and non-US listings. Cross-referencing against the spot list gives
  the stock-perp pairs; the 24 core names all have one.
* Hourly history on spot reaches back to **January 2025** for the large names; perps
  to at least October 2025. Bitget omits hours with no trades (≈3–5% of hours for a
  liquid token), so aligned series forward-fill and flag those hours.
* Fees (from `/spot/public/symbols`, `/mix/market/contracts`): rToken spot **10 bps
  taker / 10 bps maker**; stock perps **6 bps taker / 2 bps maker**, funding every 8h,
  funding on stock perps is mostly exactly 0.
* Bitget's perp `indexPrice` equals the perp's hourly close to the cent in every hour
  checked; the perp is effectively pinned to the index. `basis vs index` and
  `basis vs perp` are therefore the same measurement.

Reproduce: `nightwatch universe`, `nightwatch status`.

## 2. Basis behaviour: the token drifts from fair value when the US market is shut

RTSLAUSDT vs Bitget index, 2026-08-01 → 2026-09-12, hourly, n = 1,008 grid hours.

| bucket | n | mean \|basis\| bps | median bps | p95 bps | p99 \|basis\| bps |
|---|---|---|---|---|---|
| weekend | 264 | **27.8** | −23.2 | 21.0 | **79.0** |
| holiday | 24 | 18.2 | −16.7 | −6.7 | 35.9 |
| friday_night | 24 | 15.5 | −13.8 | 12.9 | 36.7 |
| sunday_night | 24 | 12.6 | −12.0 | −4.7 | 21.7 |
| us_pre | 174 | 11.6 | −11.4 | −2.2 | 30.0 |
| weeknight | 208 | 11.0 | −11.0 | −4.4 | 21.5 |
| us_regular | 174 | **10.9** | −9.9 | −2.8 | 24.4 |
| us_post | 116 | 10.2 | −10.1 | 0.3 | 26.3 |

* Weekend \|basis\| is **2.5×** the regular-session value; closed-hours overall are
  **1.53×** open hours. The token trades at a persistent *discount* (median −10 to
  −23 bps) that widens when the underlying cannot trade.
* Against the *native stock's last close* the gap is much larger in pre-market
  (mean 82 bps) — the token has already moved on overnight information the stock has
  not yet printed. That is the product's thesis in one row.

Reproduce: `features.basis.basis_by_bucket` on `load_aligned_hourly(...)`.

## 3. Exit liquidity is deeper than the top of book suggests — but session-dependent

Live RTSLAUSDT book, Saturday 2026-09-12 08:32 UTC (65 bid / 64 ask levels):

| size | total exit cost (walk + 10 bps fee) | levels | fills |
|---|---|---|---|
| $2,000 | 10.8 bps | 1 | yes |
| $20,000 | 11.1–13.1 bps | 4 | yes |
| $100,000 | 13.7 bps | — | yes |
| largest size within 25 bps | ≈ $278,000 | | |

The first level alone is ~$175, which is where the "books are $200 deep" impression
comes from; the whole book absorbs six figures at ~14 bps on a quiet Saturday. The
order-book recorder (`nightwatch record`) snapshots every core book each minute so
this can be measured by session over the coming weeks instead of asserted.

## 4. What the analog engine predicts, and how well (first calibration run; superseded by §7 and §8)

Replay: NVDA, 80 closed-window starts over the last 180 days, horizon = next US open,
same-ticker analogs (k = 40, ≥36h apart, history strictly before each point).

| quantile | nominal | observed share below | 95% interval |
|---|---|---|---|
| p5 | 5% | **10.0%** | [5.2%, 18.5%] |
| p25 | 25% | 37.5% | [27.7%, 48.5%] |
| p50 | 50% | **48.8%** | [38.1%, 59.5%] ✔ |
| p75 | 75% | 65.0% | [54.1%, 74.5%] |
| p95 | 95% | **87.5%** | [78.5%, 93.1%] |

* 5% tail: 8 breaches in 80 (expected 4) → **AMBER**; failure-rate LR 3.30 (p = 0.069),
  independence LR 1.81 (p = 0.18).
* Sharpness: mean p5–p95 width 5.9%; mean \|realised − p50\| 1.57%.
* Reading: the centre is right, the **tails are too narrow** — realised outcomes land
  outside the predicted 90% band ~22% of the time. This is what a small analog sample
  (k = 40) does to extreme quantiles. Planned fix (Tier 2): inflate the analog tails by
  the factor the calibration implies, and blend with the block-bootstrap Monte Carlo
  tails, then re-score. The page will show before/after.

Reproduce: `nightwatch replay --tickers NVDA --max-points 80` then `nightwatch calibration --kind replay`.

## 5. Stress presets calibrated from the token's own history (TSLA, 2026-09-12)

| preset | calibration | move / shock |
|---|---|---|
| Closed-window gap p10 / p5 / p1 | 28 past closed windows | −2.5% / −3.0% / −5.1% |
| Earnings gap: worst / typical | 4 past reports (close→next open) | −8.8% / −3.7% |
| Volatility spike ×2 / ×3 | rv24 = 38% annualised, 53h | −6.0% / −9.0% |
| Basis blowout p95 / p99 | 842 closed-hour observations | 41 / 61 bps |
| Liquidity drought | live book ÷ 5 | exit 27 → 32 quote on $20k |
| Cannot exit 24h | 2σ 24h move, half-depth book | −4.1% |

Monte Carlo (block bootstrap of closed-hour returns, 5,000 paths, 53h): p5 −3.3%,
p50 +0.6%, p95 +4.8%, expected shortfall(5%) −4.4%, P(loss > 5%) = 1.2%. Reverse
stress: a −4.87% move loses 5% of notional after exit costs on a $20k position.

## 7. Tail calibration: the analog tails were too narrow, and the fix holds out of sample

**Re-scored 2026-09-14 on the engine that ships** (the volatility and liquidity fixes of
§11 changed the features the retrieval searches, so the whole journal was rebuilt rather
than left describing an older build). 2,345 matured replay forecasts, 24 tokens, one point
per closed-market window.

| quantile | nominal | observed | 95% interval |
|---|---|---|---|
| p5 | 5% | 8.5% | 7.4–9.7 |
| p25 | 25% | 32.5% | 30.6–34.4 |
| p50 | 50% | 49.0% | 47.0–51.1 |
| p75 | 75% | 66.3% | 64.4–68.2 |
| p95 | 95% | 89.7% | 88.4–90.9 |

The centre is right (the median is inside its interval) and the tails are still too thin.
Kupiec failure-rate LR 50.1 and Christoffersen independence LR 20.6, both p < 0.001: too
many breaches, and they cluster. Band: red.

The correction is two multipliers, k_lo and k_hi, that widen p5 and p95 about the median
until exactly 5% of *already-matured* outcomes breach. They are fitted only on forecasts
whose outcome was known before the moment of use, so every number below is out of sample.

| metric | target | raw | adjusted |
|---|---|---|---|
| outcomes below p5 | 5% | 8.5% | **5.6%** |
| outcomes above p95 | 5% | 10.5% | **5.9%** |
| inside p5–p95 | 90% | 81.0% | **88.5%** |
| 5% tail band | green | red | **amber** |
| mean p5–p95 width | — | 8.44% | 12.87% |

Latest factors: k_lo 1.35, k_hi 1.57 on 2,301 evaluated forecasts.

**Amber, not green, and it stays amber.** The band is a z-score on the binomial count of
breaches: green is within one standard deviation of the expected number, amber up to two
and a half, red beyond. 5.6% against a 5% target on 2,301 forecasts is 1.3 deviations —
most of the way from red, not all of it. The gap has an obvious cause and an obvious
temptation. The factors are chosen to make breaches land on exactly 5% of the forecasts
that had already matured, and a factor fitted that way under-covers slightly on the
forecasts that come next, because the fit spends its slack on the sample it can see. The
temptation is to aim at 4.5% instead, or to weight recent breaches more heavily, either of
which would show green. Both would be chosen by looking at the out-of-sample answer first,
which is the thing this whole page exists to avoid, so neither was done. The verdict sizes
against the adjusted p5; raw quantiles stay journalled so later refits stay honest. The
cost is sharpness: an honest band is half again as wide.

Month by month (`nightwatch calibration` prints this):

| month | scored | below p5 raw → adjusted | inside band raw → adjusted |
|---|---|---|---|
| 2026-03 | 139 | 13.7% → 12.2% | 70.5% → 61.9% |
| 2026-04 | 413 | 5.6% → 4.6% | 77.2% → 86.0% |
| 2026-05 | 369 | 5.7% → 3.0% | 84.3% → 94.9% |
| 2026-06 | 392 | 16.1% → 11.7% | 76.8% → 86.5% |
| 2026-07 | 454 | 11.0% → 5.9% | 79.5% → 89.2% |
| 2026-08 | 413 | 3.1% → 1.5% | 90.1% → 94.9% |
| 2026-09 | 121 | 5.8% → 2.5% | 84.3% → 90.9% |

Two months to explain rather than hide. March is the first month of the journal: there are
too few already-matured forecasts behind it for the factors to be fitted at all, so the
adjustment barely moves and 12.2% of outcomes breach — the honest reading is that this
method needs a few hundred scored forecasts before it is worth anything. June is worse in
a different way: the factors were available and still more than one outcome in ten fell
below the level sized against. Across the period the gap to 90% coverage closes by about
3.0 points per month.

Reproduce: `nightwatch calibration --kind replay`.

## 8. Does the retrieval carry information? Only in the loss tail

**Re-scored 2026-09-14 on the shipped engine**, after the volatility and liquidity fixes
in §11 changed the features the retrieval searches over. Every replay point also journals
the distribution of *random past hours from the same time-of-week bucket*, drawn from
history strictly before it. Both are scored with the pinball loss on the same outcome,
2,325 pairs:

| quantile | analog loss | random-hours loss | skill | 95% CI of the gain |
|---|---|---|---|---|
| p5 | 0.362 | 0.378 | **+4.0%** | **+0.001 to +0.030** |
| p25 | 0.933 | 0.922 | −1.2% | −0.026 to +0.003 |
| p50 | 1.102 | 1.093 | −0.8% | −0.020 to +0.002 |
| p75 | 0.991 | 0.969 | −2.3% | −0.039 to −0.006 |
| p95 | 0.438 | 0.435 | −0.7% | −0.022 to +0.016 |
| all five | 0.765 | 0.759 | −0.8% | −0.015 to +0.003 |

Read plainly: **the analogs do not predict direction.** Over the whole distribution they
are indistinguishable from picking random hours of the same kind, and at p25 and p75 they
are measurably *worse* at the upper quartile — the resemblance concentrates the middle of
the distribution where the truth is wide. The one place they help is the loss tail: 8.4% of
outcomes fall below the analog p5 against 10.2% below the random-hours p5, and on this
engine the pinball interval at p5 excludes zero for the first time (+4.0%, +0.001 to
+0.030).

Do not read too much into that last part. This is the fifth re-score of this table on five
successive engines: +4.8%, +2.9%, +3.6%, +2.6%, +4.0% at p5, and only the first and the
last had an interval clear of zero. The sign has never changed, which is the finding; its
significance wanders around the 95% line from build to build, which is what a real effect
of this size looks like in 2,325 paired forecasts. The claim stays where it was: the
analogs do not predict direction, and they put fewer outcomes below the level the verdict
sizes against.

This is why the verdict never takes a direction from the cohort: it sizes against the
tail, and says so.

Reproduce: `nightwatch replay --tickers <list> --reset` then `nightwatch calibration --kind replay`.

## 9. Does the macro weather help the retrieval? Yes, but not where we hoped (2026-09-13)

Volatility, the yield curve and the dollar describe the market a token trades in. FRED
has them daily back to 2015, so unlike funding they can be used across the whole searched
history. Each is held until the day after it is dated, and ranked within its own trailing
year so a level cannot match on the calendar.

Whether they earn a place in the distance metric was decided by measurement, not taste.
`research/feature_ab.py` runs the same past moments through both configurations, scores
both with the pinball loss against what actually happened, and bootstraps the paired
difference. 1,605 paired forecasts, 20 tokens, 24-hour horizon:

| quantile | without macro | with macro | change | 95% CI of the gain |
|---|---|---|---|---|
| p5 | 0.3426 | 0.3402 | +0.72% | −0.0101 to +0.0166 |
| p25 | 0.8338 | 0.8275 | +0.75% | −0.0047 to +0.0173 |
| p50 | 0.9569 | 0.9494 | **+0.78%** | +0.0018 to +0.0133 |
| p75 | 0.8712 | 0.8617 | +1.09% | −0.0016 to +0.0208 |
| p95 | 0.3953 | 0.3770 | **+4.62%** | +0.0012 to +0.0347 |
| all five | 0.6800 | 0.6712 | **+1.29%** | +0.0024 to +0.0153 |

So the macro columns ship. Two honest caveats: the gain is concentrated in the median and
the upper tail, and the lower tail — the number the verdict sizes against — did not
improve (breach rate 8.5% without, 9.0% with, a difference inside the noise for this
sample). The tail-calibration layer is what fixes the breach rate either way.

An earlier run on 95 pairs showed nothing at all, and a second on 453 pairs showed a
favourable direction with intervals spanning zero. That is what a small sample does, and
it is why the decision waited for the third run.

Funding cannot be treated the same way. Bitget's public funding history returns about 90
days whatever start date is requested (verified 2026-09-13), so a funding feature would
have to be imputed across most of the searched period. It stays where the data supports
it: the stress presets and the hedge cost.

Reproduce: `python research/feature_ab.py --tickers <list> --points 100`.

## 11. Liquidity has to be judged against the same hour of the week (2026-09-14)

A tokenized US stock trades 24/7, but not evenly. Sunday afternoon is a fraction of
Tuesday's US open — for TSLA, a weekend day turns over $30k–$120k against weekday hours
an order of magnitude larger. The first liquidity ratio compared the last 24 hours with
the flat 30-day average of 24-hour volume, so every weekend looked like a collapse. On
the live box on Sunday morning, 14 September, every one of the 24 tokens had a
``liq_ratio`` between 0.00 and 0.01, every one was labelled ``thinning``, and 15 of 48
tickets came back "hostile regime — selective entries only, review". The desk had stopped
answering, and the reason was a measurement error, not the market.

The baseline is now the median of the same hour of the week over the previous four weeks,
strictly trailing and excluding the present hour, with the flat average as a fallback
while there is not yet same-hour history. Measured over the last 60 days on 12 tokens:

| baseline | mean abs. change in log ratio, hour to hour | share of hours labelled thinning |
|---|---|---|
| flat 30-day | 0.185 | 33.8% |
| same hour, 4 weeks | **0.102** | 19.7% |
| same hour, 8 weeks | 0.114 | 16.6% |
| same hour, 12 weeks | 0.116 | 17.4% |

The seasonal baseline roughly halves the jitter the baseline itself injects, and four
weeks beats eight and twelve on that measure while reacting fastest to a genuine change.
The "thinning" share falls by a third to a half because most of what it was catching was
Saturday. What survives is real: BABA on that Sunday still read ``thinning`` at a ratio of
0.65 with 71% of hours untraded.

The same treatment gives ``no_trade_excess_24h`` — how far the no-trade share sits above
its own same-hour norm — and the thinning test reads the excess rather than the raw share,
so a name that is always quiet at 03:00 UTC is not condemned for being quiet at 03:00 UTC.
With no same-hour history the norm is zero and the test is exactly its original self.

A second measurement bug rode along with the first. Realised volatility was a rolling
window over calendar hours with no-trade hours blanked, so after roughly twelve dead hours
it went NaN, the volatility state became ``unknown``, the regime label followed, and the
gate refused to take a position on the market at all. Volatility is now measured over the
last N *traded* hours and carried forward: over a weekend, the honest answer to "how
volatile is this token" is "as volatile as it was on Friday", not "unknown".

## 12. A sixth source: SEC filings, timed to the second (2026-09-14)

An 8-K is how a US company tells the market something material, and most are accepted
after 16:00 Eastern — when the stock cannot trade and the token can. That is precisely the
gap this desk exists to price, so the filings belong in it. EDGAR's submissions endpoint
gives every recent filing for an issuer with an acceptance timestamp to the second, which
makes "was there a filing in the last three days" answerable point-in-time for any hour in
the searched history, not only for now.

3,016 filings across 21 of the 24 core tickers (QQQ, SQQQ and TQQQ are not SEC registrants
under those symbols). For TSLA, 43 news-bearing filings since January 2024, **100% of them
accepted outside US regular trading hours**.

Two columns are carried on every snapshot — ``hours_since_filing``, capped at 720 so it
cannot dominate a distance metric, and ``filings_72h``. They are shown on the report and
available to the narration, but they are *not* in the search vector: like the macro
columns before them, they enter the distance metric only if a paired A/B says they earn
it. That experiment has not been run yet, so the claim here is about coverage, not skill.

Operationally: EDGAR requires a `Name contact@address` user agent and returns a 403 HTML
page otherwise — including, specifically, for any contact string mentioning github. The
recorder re-syncs every four hours.

Reproduce: `nightwatch filings --core`, then `GET /sources`.

## 10. Things that did not work, and what was done instead

* Bitget's free research data hub (`bitget-signal`) answers the MCP handshake but every
  tool returns empty results; verified the fault is server-side. Not used.
* Yahoo's earnings endpoints are gated by a crumb; Nasdaq's public calendar is used.
* FRED's CSV export hangs on a custom User-Agent; the default client UA works.
* Feed timestamps parsed with `mktime` were 5.5h off on this machine (local-time
  conversion of a UTC struct); fixed with `timegm` and pinned by a test.
* pandas 3 stores microseconds by default; integer-time code must not assume
  nanoseconds. One helper now owns the conversion.
