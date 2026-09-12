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

## 4. What the analog engine predicts, and how well (first calibration run)

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

## 6. Things that did not work, and what was done instead

* Bitget's free research data hub (`bitget-signal`) answers the MCP handshake but every
  tool returns empty results; verified the fault is server-side. Not used.
* Yahoo's earnings endpoints are gated by a crumb; Nasdaq's public calendar is used.
* FRED's CSV export hangs on a custom User-Agent; the default client UA works.
* Feed timestamps parsed with `mktime` were 5.5h off on this machine (local-time
  conversion of a UTC struct); fixed with `timegm` and pinned by a test.
* pandas 3 stores microseconds by default; integer-time code must not assume
  nanoseconds. One helper now owns the conversion.
