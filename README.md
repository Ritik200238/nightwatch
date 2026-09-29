# Nightwatch

**Stress-test a tokenized-US-stock trade before you place it.**

US stocks trade 6.5 hours a day. Tokenized versions of them (rTokens) trade 24/7. The
dangerous window is the one where only the token can move: nights, weekends, holidays —
when news lands and the real market is shut.

Nightwatch takes a trade idea in plain language — typed as a sentence or filled into a
form — and answers four questions with data:

1. **What happened before?** It finds the past moments that looked like now — same
   volatility, same gap between token and fair value, same liquidity, same distance to
   earnings and to the Fed — and shows what followed, with sample sizes and confidence
   intervals. Each match says what it shares with now and where it differs, next to a
   "Now" row, so a reader can argue with it. (Time of week is deliberately *not* a
   condition: replayed over 610 past moments, restricting matches to the same slot of the
   week gave no truer loss tail.)
2. **What could go wrong?** Preset stress tests built from real token data — weekend gap,
   earnings gap, volatility spike, token-vs-fair-value blowout, liquidity drought, exchange
   halt — each taken from the tail that hurts *this* side (the falls for a long, the
   squeezes for a short). Plus **crash replays**: what this stock actually did on the days
   the market broke in the COVID crash, the 2022 inflation shock, the March 2023 bank
   failures, the August 2024 carry-trade unwind and the April 2025 tariff shock.
3. **Can you get out?** It walks the live order book for your size and tells you the real
   cost of exiting.
4. **How big, then?** A sized verdict — go, reduce, hedge with the perpetual, or don't —
   with every number traceable to its source.

On top of that:

* **How this trade loses money**, worst first: each way it fails, what sets it off, why it
  costs what it does and how often it happened — written by rules from the report's own
  numbers, never by a model. Beside it, **what the answer assumes**, with the assumptions
  that could make it wrong flagged, and a check of your stated reason against the
  calendar ("post-earnings drift" with no recent earnings is said).
* **Leverage, with its liquidation price.** "5x long NVDA" is held on Bitget's perpetual:
  the liquidation price comes from Bitget's own margin tiers for that size, and the desk
  counts how many past moments like this, which stress tests and what share of simulated
  paths would have reached it. A one-in-twenty chance of liquidation is a no.
* **Ask it anything a stress test should answer**: "what if it gaps down 10%?", "halve
  it", "why?", "what about 5x?", "hold it until Wednesday", "is my thesis supported?",
  "why are these moments similar?" — each answered from the report or by re-running it.
* **An AI analyst reads the finished report** (Qwen 3.8 Max, about 8 s) and says what
  matters most tonight and what would change its mind - connecting the facts rather than
  listing them. It cannot move a number: every figure it quotes is checked against the
  report, and a sentence citing one that is not there is removed before you see it.
* **Your own plan is tested.** "Wrong if it closes below 360" gets a distance and a count
  of how many past moments like this crossed it inside the same hold.
* **The stock's live price while the US market is shut**, analyst ratings and insider
  trades, from Bitget's own US-stock data service.
* **Getting in, not just getting out**: the entry cost for the size the desk recommends,
  sliced to stay inside the cost budget, with a dry-run prompt for Bitget Agent Hub.
* **English and 中文**: type the trade either way and get the answer in the same language.

Then it argues against its own answer, using the same numbers, and tells you what would
have to change for the verdict to be different: how big you could go, how far your stop
could sit, and where the answer flips.

The human makes the decision. Nightwatch never places orders.

**Live:** https://nightwatch-gules.vercel.app

![A sized verdict for a TSLA position](docs/img/desk-verdict.png)

It also keeps track of the things a single trade cannot see:

* **Your book.** Given what you already hold, it measures the correlation from the tokens'
  own history and says which position actually carries the bad case, rather than assuming
  three names are three bets.
* **Your record.** Trades you mark as taken feed daily, weekly and monthly loss limits.
  Past them, the gate refuses the next ticket whatever it looks like.
* **What happened last time.** Every matured forecast gets a plain sentence and comes back
  the next time conditions look similar.
* **What the book looks like at other hours.** The recorder snapshots every order book
  every minute, because nobody publishes how deep a tokenized stock is at 3 a.m. on a
  Sunday.
* **Where the numbers came from.** Six live feeds — Bitget, Yahoo, Nasdaq, FRED, RSS and
  SEC EDGAR — each listed on the desk with when it was last pulled and the newest thing in
  it. Filings are timed to the second EDGAR accepted them, because most 8-Ks land after
  the US close, when the stock cannot react and the token can.
* **A link you can send someone.** Every analysis keeps its full report, so `/r/<id>`
  reopens that exact verdict — same analogs, same stress table, same book, same hash of
  the inputs, nothing recomputed.

## Use it from your own AI tool

The desk is also an MCP server, so Claude, Cursor or any MCP client can call it directly:

```bash
claude mcp add nightwatch --transport http https://nightwatch-gules.vercel.app/api/mcp
```

Three read-only tools: `stress_test` (the full analysis - verdict, history, stress tests, liquidation with `leverage`,
exit cost), `list_conditions` (what the search can be narrowed to, and what each costs in
evidence) and `list_tokens`. The calling model picks the tool and fills in the trade;
every number in the reply comes from the engine. Nothing here can place an order.

It also ships as an Agent Hub-style skill, [`skills/nightwatch-stress-test`](skills/nightwatch-stress-test/SKILL.md),
in the same format as Bitget's `bitget-signal` skills: when to reach for it (English and
中文 triggers), how to call the tools, and how to present a verdict without inventing a
number. Installed next to Agent Hub, it is the step that runs before an order is drafted:

```bash
mkdir -p ~/.claude/skills/nightwatch-stress-test
curl -fsSL https://raw.githubusercontent.com/Ritik200238/nightwatch/main/skills/nightwatch-stress-test/SKILL.md \
  -o ~/.claude/skills/nightwatch-stress-test/SKILL.md
```

### Bitget integration, checked

| Bitget service | What the desk uses it for | Status |
|---|---|---|
| Spot and futures REST (`api.bitget.com`) | rToken and perp candles, order books every 30 s, funding, perp margin tiers for liquidation prices | live |
| `bitget-mcp-server` (`agent.bitget.com/mcp`) | live quote while the US market is shut, analyst ratings and targets, insider trades, fear & greed | live |
| `bitget-signal` skills' data server | probed on 29 Sep: news, earnings, sentiment, macro, rates and prices returned empty errors; only technical analysis answered, with Bollinger bands inverted (upper below lower) | not used until it answers |

The `bitget-mcp-server` feed had been silently empty in production: the server refuses
new sessions over this box's IPv4 ("Too many open sessions") and accepts them over IPv6,
and the API's container had only IPv4. It now runs on the host network; `/sources` shows
how many tokens currently have Bitget street data.

It reads the other way too: every analysis of today pulls Bitget's own US-stock data
(`bitget-mcp-server`) for the stock's live price while the US market is shut, analyst
ratings and targets, insider trades and market fear & greed.

## Does it work?

Every forecast is journaled before its outcome is known and scored when the horizon
passes, so the page below is not a claim, it is a scorecard. Three findings from it, the
uncomfortable one included:

* **The raw tails were wrong.** Across 2,345 scored replays, 8.5% of outcomes fell below
  the stated 5th percentile instead of 5%. Factors fitted only on already-matured
  forecasts brought that to 5.6% out of sample — and that number was hiding a second
  error: the narrowest third of forecasts still breached 8.2% of the time and the widest
  third 2.7%, because a multiplicative factor keeps a narrow forecast narrow. An absolute
  margin, solved so the narrow half breaches 5% too, takes the narrowest third to 5.5%,
  the whole set to 5.4% (green), and does it with a *narrower* average tail. Measured
  before it shipped: better on 20 of 24 tokens, clustered t = +3.75.
* **The analogs do not predict direction.** Scored against random hours of the same kind,
  they are indistinguishable over the distribution as a whole. Where they win is the loss
  tail: 8.4% of outcomes below their 5th percentile against 10.2% below the random one.
  That is the only claim this product makes.
* **The macro layer earned its place by measurement**, on the third and largest test of
  it: 1,605 paired forecasts, a 1.3% lower forecast loss, interval excluding zero. The two
  smaller tests before it showed nothing, and the notes say so.
* **Shorts were not being stress-tested, and now are.** Every price preset used to be a
  fall — a gain for a short — so a TSLA short's "1-in-100 gap" read as +7.4%. Presets now
  come from the tail that hurts the position's own side; the same short reads −6.8%.
* **More history is not automatically better.** Backfilling 2025 earnings dates brought
  back 15% more searchable hours and made the 5th percentile slightly *less* accurate on
  820 replayed moments (9 of 24 tokens better, t = −0.76). It was not shipped.

The full write-up is in [docs/research-notes.md](docs/research-notes.md).

### What we tested about the retrieval itself

The scorecard above measures the forecasts. The **Studies** page measures the thing that
makes them: eleven questions about the retrieval, each written so it could come back no,
each recomputed from the stored bars and the journal by `nightwatch studies`. Five came
back no, three could not be decided (numbers below are the 26 Sep run; the page recomputes
them, so a last digit can move), and the most useful are the ones that cost us something:

* **Closer analogs do not have tighter outcomes — they have wider ones.** The near half
  of a retrieval is 13% wider by standard deviation and 19% by interquartile range, and
  only 1 of 24 tokens goes the other way (clustered t = −6.2, n = 958). The distance is dominated by the volatility
  features, so a query made in a wild moment retrieves wild neighbours.
* **So weighting the close matches more makes the forecast worse.** The engine's own
  similarity weights push the 5th percentile in far enough to roughly double the rate at
  which the real outcome falls outside the band. The weighted fields the cohort computes
  stay wired to nothing, which is now a measured decision rather than an oversight.
* **One tail factor was hiding two opposite errors.** Pooled coverage read 5.3% against a
  5% target — respectable, and made of 6.2% breaches on overnight holds cancelling 1.8%
  on multi-day ones inside a band 17.6% wide. Fitting per holding period brought them to
  4.9% and 6.5%. When it shipped, a 60k TSLA weekend hold with no stop went from an
  allowed 23,880 to 42,011 USDT (checked through the gate that day).

A "we have never seen anything like this" warning looked significant at t=+3.6 and died
at t=−0.07 once tokens were clustered: it was measuring which tokens are volatile, not
which moments are strange. It is not shipped.

![Calibration page](docs/img/calibration.png)

Every call it has made, and how each one turned out:

![Journal page](docs/img/journal.png)

## Run it

Python 3.11+ and Node 22+. Everything works without any API key, including the
plain-language chat, which falls back to a rule-based parser and briefing. Set
`ANTHROPIC_API_KEY` to have Claude handle the conversation instead.

```bash
# 1. Python environment
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e ".[api,dev]"   # macOS/Linux: .venv/bin/python

# 2. Data: resolve the universe, backfill history (resumable; hours for 24 tokens), calendars, news
nightwatch universe
nightwatch sync --core
nightwatch calendars
nightwatch news

# 3. Keep it fresh: order books every minute, bars/calendars/news on their own cadence
nightwatch record

# 4. API and web desk
uvicorn nightwatch.api.app:app --port 8000
cd web && npm ci && cp .env.local.example .env.local && npm run build && npm start   # http://localhost:3000
```

Or with containers: `docker compose up -d` after seeding the database (see `docs/deploy.md`).

### From the terminal

```bash
nightwatch analyze TSLA --side long --notional 20000 --equity 100000 --stop 350
nightwatch replay --tickers TSLA --max-points 100     # score past closed-market windows
nightwatch calibration --kind replay                   # does it tell the truth?
nightwatch status
```

### Tests

```bash
.venv/Scripts/python.exe -m pytest
```

## Layout

| path | what |
|---|---|
| `nightwatch/data` | Bitget, Yahoo, Nasdaq, FRED, RSS, SEC EDGAR clients; SQLite store; sync |
| `nightwatch/features` | session calendar, basis, regime, event features, point-in-time snapshots |
| `nightwatch/analog` | analog retrieval, forward outcomes, cohort statistics, random baseline |
| `nightwatch/stress` | data-calibrated presets, block-bootstrap Monte Carlo, reverse stress |
| `nightwatch/execution` | order-book walk, exit cost curve, perp hedge economics |
| `nightwatch/decision` | trade ticket, rule gate, sizing caps, verdict |
| `nightwatch/journal` | forecast journal, calibration tests, replay, tail adjustment |
| `nightwatch/api` | FastAPI app and the language layer |
| `web` | Next.js desk |
| `docs` | research notes, deployment |
