# Nightwatch — the whole product, explained simply

> Numbers in this file were checked against the code and the live site on 25 Sep 2026.
> Anything not proven is marked **NOT VERIFIED**.

---

## 1. What we are, in one line

**Nightwatch tests your trade before you place it.**
You type a trade idea. It tells you how bad things could get, what it costs to get out,
and whether to go ahead, go smaller, hedge, or skip. **You decide. It never places orders.**

- Live site: https://nightwatch-gules.vercel.app
- Code: https://github.com/Ritik200238/nightwatch
- Hackathon: Bitget AI Base Camp S2 → **Track 3 (AI Trading Desk)** → sub-theme **Decision Stress Testing**

---

## 2. The problem we solve

- Bitget sells **tokenized US stocks** (e.g. a Tesla token, `RTSLAUSDT`). They trade **24/7**.
- The **real** US stock market is open only 6.5 hours a day, 5 days a week.
- So at night and on weekends **only the token moves**. If big news lands, the real stock
  can **jump** when the market reopens, and your token follows.
- At night the **order book is thin**: selling can cost much more than you think.
- The token can also drift away from the real stock's price.

Most traders can't see these risks. Nightwatch measures them **before** you commit money.

---

## 3. Why it fits our sub-theme

Bitget's own words for Decision Stress Testing:
*"Before opening a position, how does AI retrieve historically similar scenarios?
Input trade idea → retrieve historical distribution; preset stress tests."*

| What the sub-theme asks | What Nightwatch does |
|---|---|
| Input a trade idea | Type it in plain English or Chinese, or use a form |
| Retrieve similar past scenarios | Finds the 40 past moments most like right now |
| Show the historical distribution | Shows what happened after them: middle result, bad case (1 in 20), win rate |
| Preset stress tests | 8 kinds of stress test, measured from real token data |
| Before opening a position | Gives a verdict and a size **before** you trade; the human decides |

---

## 4. How someone uses it (user flow)

1. **Open the site.**
2. **Type the trade**, e.g. `long 20000 USDT TSLA over the weekend, stop 350`,
   or in Chinese: `周末做多特斯拉 2万U，止损350`.
   If something is missing (long or short? how much?), it asks you.
3. **Wait about 2–5 seconds.** The full report comes back.
4. **Read the verdict:** GO / REDUCE / HEDGE / REVIEW / NO GO, plus a suggested size.
5. **Look at the details**: history, your stop, stress tests, exit cost, hedge, live price,
   your own plan, the entry plan and the AI analyst's view.
6. **Ask follow-ups** in the chat:
   - "what if I only hold 12 hours?" → it re-runs and shows the difference
   - "what's my worst case?", "how much to hedge?", "can I get out?"
   - "only compare with earnings weeks" → narrows the history search
7. **Share it**: every report has its own link (`/r/<id>`) that reopens exactly the same result.
8. **Mark it as taken** if you actually place the trade. It then feeds your loss limits and
   your trade journal.

---

## 5. What you get in a report (all features)

### A. The verdict
- **GO** (fine), **REDUCE** (trade smaller), **HEDGE** (protect it with a perp),
  **REVIEW** (something needs checking), **NO GO** (don't).
- A **recommended size** in USDT, and which limit decided it.

### B. History: "what happened before?"
- Finds the **40 past moments most like now**, across all 24 stock tokens.
- "Like now" means similar across **21 measurements**: volatility, token vs real price gap,
  trend, liquidity, hours to earnings, hours to the Fed meeting, news count, VIX, the
  dollar, US bond yields, and more.
- Shows the **middle result**, the **1-in-20 bad case**, the win rate, the worst dip on the
  way, and confidence ranges.
- Past moments are spread out (at least 36 hours apart), so one event isn't counted 40 times.
- If there isn't enough history, it **refuses to guess** and says so.

### C. Your stop and your plan
- How far away your stop is, and how many of the 40 past moments would have hit it.
- **Your own "I'm wrong if…" is tested**: "wrong if it closes below 360" → how many past
  moments crossed 360 during the same hold.
- Warnings for a stop on the wrong side, too tight, too wide, or so far away it looks like
  another stock's price.

### D. Stress tests: "what could go wrong?"
Eight kinds, with numbers **measured from our data**, not invented:
1. Closed-market gap (the jump when the market reopens)
2. Earnings gap: worst seen and typical
3. Volatility spike ×2 / ×3
4. Token vs real price blowout
5. Liquidity drought (order book 5× thinner)
6. Can't exit for 24 hours during a bad move
7. Funding spike on the hedge
8. Monte Carlo: thousands of simulated paths, plus "what move would lose 5%?"

Each shows the loss in % and in USDT.

### E. Getting out and getting in
- **Exit cost:** walks the **live Bitget order book** for your exact size and gives the
  real cost (spread + fees).
- "Largest size you can exit within the cost budget."
- **Order book by hour of the week:** we record every book **every minute**, so we know
  how thin it gets at 3 a.m. on a Sunday.
- **Entry plan:** all at once or in slices, at what limit price, plus a ready-made prompt
  for a practice run in **Bitget Agent Hub**.

### F. Hedge
- The cost to protect the position with a **Bitget perp**: fees + funding for your hold,
  and the risk that's left over.

### G. The real stock right now
- The real stock's **live price** even when the US market is closed, via **Bitget's MCP**.
- Whether the token is above or below it, in bps.
- Analyst ratings and price targets, insider trades, market fear & greed.

### H. The rules (the "gate")
The desk refuses or warns when:
- the stop is wrong, too tight or too wide;
- the position is too big for your account;
- you just lost money and are trying to win it back straight away (revenge-trade cooldown);
- you have no written plan (why you're in, and when you're wrong);
- the order book can't absorb your size;
- the data is bad or stale;
- you've hit your **daily / weekly / monthly loss limit** (circuit breaker).

### I. Sizing: 5 limits, the smallest one wins
1. Risk budget (how much you lose if the stop is hit)
2. Concentration (not too much of your account in one trade)
3. Exit liquidity (can you get out?)
4. Market state (calm vs rough market)
5. Stress (worst stress test stays inside your limit)

### J. What would change the answer
- "You could go up to X and still get GO."
- "Your stop could sit up to Y% away."
- **The case against**: it argues against its own verdict using the same numbers.

### K. AI analyst's view
- **Qwen 3.8 Max** (through Bitget's hackathon gateway) reads the finished report and writes
  a short take: what matters most tonight, and what would change its mind.
- **It can't change or invent numbers.** Every number is checked against the report, and a
  sentence with a made-up number is deleted before you see it.
- Hard comparisons (e.g. "7 crossed your line, 4 of those hit the stop") are worked out by
  code and handed to it, so it can't get them backwards.
- Arrives about 8 seconds after the report; you never wait for it.

### L. English and Chinese
- Type in either language; you get the whole answer, follow-ups included, in the same language.

---

## 6. The other pages

| Page | What it shows |
|---|---|
| `/` (home) | The chat and form, an example button, and the report |
| `/tonight` | **Your whole portfolio at once**: which position carries the most risk tonight, using real correlations |
| `/calibration` | **Proof**: every past forecast vs what really happened |
| `/journal` | Every call the desk made and how it turned out, with lessons |
| `/studies` | Tests of our own method, including the ones that came back "no" |
| `/r/<id>` | A saved report, exactly as it was |

---

## 7. How it works inside (simple version)

```
You type a trade
      │
      ▼
1. READ      rules read it in milliseconds (English + Chinese);
             Qwen is asked only if the rules can't finish
      │
      ▼
2. NOW       measure "now" on 21 things (vol, gap, liquidity, earnings, Fed, macro...)
             using only data available at this moment: no peeking at the future
      │
      ▼
3. HISTORY   find the 40 most similar past moments → what happened next
             → correct the bad-case number using how wrong it was before
      │
      ▼
4. STRESS    run 7 kinds of stress test + Monte Carlo on your size
      │
      ▼
5. BOOK      walk the live Bitget order book → exit cost, entry plan, hedge cost
      │
      ▼
6. RULES     gate + 5 sizing limits → verdict + size
      │
      ▼
7. EXPLAIN   brief in your language; AI analyst's view arrives after
      │
      ▼
8. JOURNAL   saved; scored later against what really happened
```

---

## 8. Bitget integration

| What | How we use it |
|---|---|
| Bitget spot API | Hourly prices for 24 stock tokens (history back to Jan 2025) |
| Bitget index prices | The fair-value reference for each token |
| Bitget US-stock perps + funding | Hedge cost and funding |
| Bitget order books | Live exit/entry cost; recorded every minute, 24/7 |
| **Bitget MCP** (`agent.bitget.com/mcp`) | Live real-stock price, analyst ratings, insiders, fear & greed |
| **Qwen via Bitget's gateway** | Reads unclear messages and writes the analyst's view |
| **Bitget Agent Hub** | We give a ready prompt for a practice run of the entry |
| **Our own MCP server** | Any AI tool (Claude, Cursor…) can call Nightwatch's `stress_test` |

Other data: Yahoo (real stock prices), Nasdaq (earnings dates), FRED (US macro data),
RSS (news), SEC EDGAR (company filings, timed to the second).

---

## 9. How much tech is in it

| Thing | Size |
|---|---|
| Engine (Python) | **82 files, ~17,600 lines** |
| Tests | **584 automated tests** (45 files, ~6,700 lines) |
| Website (Next.js 16 / React) | 37 files, ~6,300 lines |
| Commits | 238 |
| API endpoints | 20 |
| History-search features | 21 |
| Stress-test kinds | 7 preset kinds + Monte Carlo + reverse stress |
| Ways to narrow the history | 17 (e.g. earnings week, weekend, high volatility, Fed soon) |
| Languages | English + Chinese |
| Data feeds | 6 live sources + Bitget MCP |

**Technical pieces we built ourselves:**
- **Similar-moment search:** a Mahalanobis nearest-neighbour search (a distance that accounts
  for how the features move together) that spreads matches out in time and refuses when
  there's too little data.
- **Point-in-time snapshots:** every number uses only what was known at that hour, with a
  fingerprint (hash) of the inputs.
- **Tail calibration:** the 1-in-20 bad case is corrected using past mistakes, with an
  absolute floor under narrow forecasts, separately
  for each holding period.
- **Honesty tests:** standard statistical checks of how often the bad case was breached, and
  whether breaches bunch together (Kupiec and Christoffersen tests), with a traffic light
  on the page.
- **Order-book walker + minute-by-minute recorder.**
- **Stress engine:** measured presets, block-bootstrap Monte Carlo, reverse stress.
- **Market-state map:** our own clustering of market regimes and how they switch.
- **Portfolio risk:** correlation-based "which position carries the bad night".
- **Safe AI layer:** a rules-first parser, number-checking, and computed comparisons.
- **MCP client and MCP server.**

**Running it:**
- Backend: FastAPI in Docker on an AWS Lightsail server (Mumbai, 1 GB), SQLite database.
- Frontend: Vercel (the Mumbai region, so it's close to the backend).
- GitHub Actions runs every test on every push; the server deploys itself only if the tests
  pass, and rolls back if it breaks.
- A self-heal script restarts anything unhealthy; an uptime check runs every 15 minutes.

---

## 10. Does it actually work? (measured, including the bad parts)

- **The bad-case number is checked against reality.** On 2,345 past replays, the raw
  "1 in 20" was breached 8.5% of the time (should be 5%). After our correction: **5.1%**
  out of sample, light **green**. That took two hidden errors to find: one tail factor
  hid opposite errors by holding period, and then a multiplicative factor left narrow
  forecasts too narrow (narrowest third breached 8.2%, widest 2.7%). A floor under narrow
  forecasts fixed the second, measured before shipping (better on 20 of 24 tokens).
- **It does NOT predict up vs down.** Compared with random similar hours, it has no edge
  on direction. Its edge is the **size of the downside**: 8.4% breaches vs 10.2% for random.
  We say this openly.
- **Tests that came back "no"** are published on `/studies` (e.g. weighting close
  matches more made things worse, so we don't do it).
- **Live check (25 Sep):** 96 extreme trades across all 24 tokens → **0 errors**,
  most answered in 2–5 seconds (slowest 18 s).

---

## 11. Who it's for (product-market fit)

- **Users:** people trading Bitget stock tokens outside US hours, especially in Asia (hence Chinese).
- **Pain:** weekend gaps, thin night books and token drift cost real money, and are invisible today.
- **Why Bitget would care:** fewer blown-up accounts means more trust and more stock-token
  trading. It could become a built-in "check before you trade" button.
- **Honest gap:** **no real outside users yet.** Product-market fit is argued, **NOT VERIFIED**.

---

## 12. Compared with the repos we studied

We studied 24 open-source repos. The main two were **claude-trading-skills** and
**ai-hedge-fund**. We wrote all our own code.

- **Took the ideas and built our own versions:** pre-trade gate, revenge cooldown, sizing,
  circuit breaker, trade memory + post-mortems, "what happened after similar setups",
  point-in-time snapshots, bootstrap ranges, position limits, portfolio view.
- **We go further:** automatic similar-moment search, real Bitget data and order books,
  measured closed-market stress tests, proof of calibration, one flow from one sentence,
  Chinese, MCP.
- **They're bigger:** dozens of strategies and screeners, many users, years of work.
  We do one job, stress-testing a trade before you place it, and go deep on it.

---

## 13. Known limits (said plainly)

- No real users yet.
- It doesn't predict direction, only downside risk.
- The bad-case number is on target overall (5.1%), but the weekend band is small (about 360
  forecasts) and reads 6.3%; it refits itself as more weekends mature.
- One small server: heavy traffic from many users at once is untested (**NOT VERIFIED**).
- After each deploy the server is down for about a minute, and the first answer is slow.
  The code is now frozen, so deploys are rare.
- Only the 24 stock tokens with enough history are covered.
