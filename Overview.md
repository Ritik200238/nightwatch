# Nightwatch: product overview

*Written from the code as it is on 4 Oct 2026. Anything not built is marked as not built.*

---

## 1. Vision and purpose

**"Stress-test the trade before you place it."**

Nightwatch is a pre-trade desk for **tokenized US stocks (rTokens) on Bitget**. Before you
open a position, it tells you three things:
- what happened after past moments like this one,
- how this trade could lose money,
- whether you can get out at a fair price.

Then it gives a **sized verdict**: how much, if anything, to put on.

It never places orders. The human decides.

**Why it exists:** US stocks trade 6.5 hours a day, but their tokens on Bitget trade 24/7.
The risky window is when **only the token can move**: nights, weekends and holidays.
- News can land while the real market is shut.
- The token reprices on a thin order book.
- Then the stock gaps at the next open.

A normal stock tool doesn't model that window. Nightwatch is built around it.

---

## 2. The problem, and for whom

**Problem:** a trader about to hold an rToken overnight or over a weekend has no quick,
honest answer to these questions:
1. *What usually happens from a moment like this?*
2. *What's the realistic bad case, and how does this trade lose money?*
3. *Can I actually exit this size on this book at 3 a.m.?*
4. *So how big should I go?*

Today they guess, look at a chart, or ask an AI chatbot that will happily invent numbers.

**Who it's for:** retail and semi-pro traders on Bitget who hold tokenized US stocks
(TSLA, NVDA, AAPL, SPY, QQQ and others, 24 tokens in all) through closed-market hours,
including leveraged traders on Bitget's perpetual futures for the same stocks.

---

## 3. Target user

**Primary:** a Bitget user who is about to open (or already holds) an rToken position over a
night or weekend. They think in sentences like *"long 20k NVDA over the weekend"* or
*"周末做多特斯拉 2万U"*, not in risk models.

**Secondary (built for, lighter use):**
- **AI agents and developers**, through an MCP server and a Bitget Agent Hub skill file.
- **People who want proof before trusting a tool.** The public track record, receipts and
  "what we got wrong" pages are for them.

**Honest status:** no real outside users have been measured yet. Usage is counted at
`/usage`, and nearly all of it is internal testing so far.

---

## 4. The user journey, end to end

1. **Land on the site** (nightwatch-gules.vercel.app).
   - One input box, a 4-step "how it works" strip, and an example verdict already on screen.
   - One-click demo trades: "NVDA weekend 15k", "5x TSLA overnight", "周末做多特斯拉".
2. **Describe the trade.** Do it in plain English or Chinese, e.g. *"Long 15k TSLA over the
   weekend because deliveries beat, wrong if it closes below 400"*, or use the Ticket form.
   - If something is missing (token, side, size), the chat asks for it.
   - If no size is given but an account size is, it uses the largest size the rules allow.
3. **The desk runs the analysis** (about 1–6 s once warm). A "How this answer was built" panel
   shows each step and its timing.
4. **Read the verdict:**
   - The verdict is **GO**, **REDUCE TO** (a smaller size), **HEDGE** (with the Bitget
     perp), **REVIEW** (the desk needs something from you, e.g. account size or a stop) or
     **NO GO**.
   - Key numbers sit under it: the one-in-twenty loss, the worst stress scenario, the exit
     cost, and any size cut.
   - Every number carries a source tag: Live, History, Assumed or AI.
5. **Dig into why** (grouped sections):
   - **Evidence:** the past moments, the stress tests, assumptions, size caps and the best
     case against it.
   - **Your book:** your other positions and your record.
   - **Alerts & plan:** tripwires, a pre-commit plan and watching the verdict.
   - **Research:** street views, the Bitget signal and a book comparison.
6. **Ask follow-ups in chat:**
   - "what if it gaps down 10%?", "halve it", "what about 5x?", "short it instead"
   - "compare with SPY", "why?", "is my reason right?", "should I buy?"
   - Each is answered from the report, or the trade is re-run with the change.
7. **Let the AI dig deeper (optional).** The stress-test agent runs a few more checks on the
   engine and writes a cited conclusion.
8. **Act or protect** (still no orders placed):
   - Open the token on Bitget, copy the sized ticket, or copy a dry-run prompt for Bitget
     Agent Hub.
   - Arm a **price tripwire**, save a **plan** ("if X happens, I will cut half"), or
     **watch** the verdict, which is re-checked at the next US close.
   - Mark **"I took this trade"**, so your own loss limits apply next time.
9. **Come back later:**
   - Every live verdict is journaled with a tamper-evident receipt, scored when its hold
     ends, and shown on the public track record.
   - A permanent link `/r/<id>` lets you share it.

---

## 5. Core features, and what each one does

### A. The core stress test (the main product)
| Feature | What it does |
|---|---|
| **Similar past moments** | Finds past hours that looked like now, on volatility, token-vs-fair-value gap, liquidity, regime, and distance to earnings and the Fed. Shows what followed over the same hold, with sample sizes and confidence ranges. Each match says what it shares with now and how it differs. Pools across tokens when one token has too little history. |
| **Distribution of outcomes** | The middle outcome and the one-in-twenty bad case for *your side*, adjusted by how past forecasts actually came out. |
| **Preset stress tests** | About 15 scenarios fitted from the token's own history: weekend gap, earnings gap, volatility spike, the token drifting from fair value, a thin book, and being stuck unable to exit. Each is taken from the tail that hurts your side (falls for a long, squeezes for a short). |
| **Crash replays** | What this stock really did in the COVID crash, the 2022 inflation shock, the March 2023 bank failures, the August 2024 carry-trade unwind and the April 2025 tariff shock. |
| **How this trade loses money** | A ranked list, biggest loss first: what triggers each loss, why it costs that much, how often it happened. Written by rules, not AI. |
| **Exit cost on the live book** | Walks Bitget's live order book for your size and prices the exit. Also gives an entry plan, sliced to stay inside a cost budget. |
| **Sized verdict** | A rule gate covering concentration, risk budget, liquidation, a written plan and your own loss limits. It sets the size and the verdict. |
| **What would change it** | Re-runs the same gate at other sizes and stops: how big you could go, and where your stop could sit. |
| **Case against** | The strongest argument against the verdict, built from the report's own numbers. |
| **Leverage** | For perp positions: the liquidation price from Bitget's margin tiers, and how often similar past moments got there. |

### B. Personalisation
| Feature | What it does |
|---|---|
| **Your book** | "I also hold 60k TSLA and 40k NVDA" measures the whole book's bad case before and after the trade, and can cut the size. If the book is over its limit, it suggests 2–3 fixes and runs a reverse stress test. |
| **Your plan is tested** | "Wrong if it closes below 360" is checked against how often past moments crossed that line. It flags a stop placed beyond your own "wrong if" level, and a reason whose direction doesn't match the trade's. |
| **Your reason vs the calendar** | An "earnings" or "Fed" reason with no such event near the hold is flagged. |
| **Your reason vs the news** *(new)* | Splits your written reason into claims and checks each one against the news headlines and SEC filings stored in the 14 days before the report. The result is "in the news", "the news says otherwise" or "not in our feeds", with the real headline linked. The AI only picks which stored item matches; it never writes a quote. |
| **Circuit breaker** | Trades you mark as taken count toward daily, weekly and monthly loss limits. Once past them, the next ticket is refused. |
| **Lessons** | Every finished forecast gets a plain sentence, shown again when conditions look similar. |

### C. Conversation and AI (the AI never changes a number)
| Feature | What it does |
|---|---|
| **Chat** | Plain-language trade intake in English or Chinese (e.g. "2万U"), follow-ups, what-ifs and plain answers to "should I buy?". Rules handle it if the AI is down. |
| **AI analyst** | Qwen 3.8 Max reads the finished report and says what matters most and what would change its mind. A guard removes any sentence that quotes a number not in the report. |
| **Stress-test agent** | The AI plans a few tool calls (what-if, base rate, safest ways to hold, follow-ups) on the desk's own engine, then writes a conclusion where every number is cited. |
| **Base-rate questions** | "How often does TSLA fall 5% over a weekend?" is answered straight from history. |
| **Safest way to hold it** | The same idea run several ways side by side: as asked, half the size, a shorter hold, half hedged on the perp, and no leverage (for a leveraged trade). It picks the GO version with the smallest bad-case loss. |

### D. Watching after the decision
| Feature | What it does |
|---|---|
| **Tripwires** | One click arms "tell me if TSLA trades through X", prefilled from your stop, invalidation, liquidation or 1-in-20 price. The recorder checks Bitget every minute, fires once, re-runs the desk and can call your webhook. |
| **Pre-commit plan** | For each price where the trade can go wrong, you choose hold, cut half, exit or hedge in advance. The alert reminds you what you decided. |
| **Watch** | Re-checks a verdict at the next US close (`/watch/<id>`). Email is not built; an https webhook is optional. |
| **Tonight** (`/tonight`) | For positions you already hold: which one is the problem tonight, ranked by money. |

### E. Trust and proof
| Feature | What it does |
|---|---|
| **Track record** (`/calibration`) | Every live verdict is scored when its hold ends. The page shows whether the one-in-twenty line really breaks about 5% of the time. |
| **What we got wrong** (`/wrong`) | Every live verdict that went past its line, plus mistakes found in the desk itself. |
| **Receipts** (`/verify`, `/anchors`) | Each verdict is hash-chained to the one before it, and the chain is anchored to Bitcoin daily via OpenTimestamps. Anyone can recompute it. |
| **Studies** (`/studies`) | 11 studies of the method, corrected for multiple testing. Includes the measured finding that the desk has no directional edge. |
| **Sources and status** | `/sources` shows what each data feed last delivered; `/status` shows health. |

### F. Data and integrations
- **Bitget:**
  - candles, order books recorded every minute, funding and perp margin tiers
  - Bitget's US-stock data service (via its MCP server)
  - the Bitget signal skill
  - links out to Bitget and a dry-run prompt for Agent Hub
- **Other feeds:** Yahoo, Nasdaq (earnings), FRED (macro), RSS news, and SEC EDGAR filings,
  which the AI reads and labels.
- **For agents:** an MCP server (`stress_test`, `list_conditions`, `list_tokens`) and a Bitget
  Agent Hub skill file.
- **Telegram bot:** built and tested, but **off**. It needs a bot token that hasn't been set.

---

## 6. How the features serve the vision

Everything answers one question: **"should I hold this trade through the window when only
the token can move, and how big?"**

- **Similar moments → distribution → stress tests → sized verdict** is the core answer,
  and it is exactly the sub-theme's pipeline.
- **Exit cost and leverage** cover the two ways the closed-market window hurts beyond
  price: a thin book, and liquidation.
- **Your book, your plan, your reason and the circuit breaker** turn a generic answer into
  one about *your* trade.
- **Chat, the AI analyst and the agent** make it usable without knowing risk jargon, while
  rules and checks keep the numbers honest.
- **Tripwires, plans, watch and Tonight** carry the decision through the night you are
  holding.
- **The track record, receipts and published misses** are why anyone should believe the
  numbers.

---

## 7. What makes it different

1. **Built for the 24/7 token vs the 6.5-hour stock.** It models closed-market gaps, the
   token drifting from fair value, and order-book depth at night. Generic stock tools and
   chatbots don't.
2. **The full chain from one sentence:** past moments → distribution → stress tests →
   exit cost → a *sized* verdict, plus follow-ups and what-ifs. In our head-to-head checks
   of the rival entries, none did the whole chain from free text.
3. **The AI can't invent numbers.** Engines compute; the AI explains and picks. A guard
   removes unsupported figures, and quotes come only from stored data.
4. **Proof in public.** Every verdict is scored, receipted and anchored, and the misses
   are published. Few tools publish when they are wrong.
5. **Real Bitget depth:** live books, perp margin tiers, the US-stock MCP and the signal
   skill, with every source shown.

---

## 8. MVP vs future

### What exists today (the shipped product)
Everything in section 5 is built, deployed and tested (about 1,500 automated tests), except
Telegram, which is built but switched off. It runs on:
- **website:** Vercel
- **API and recorder:** a small AWS Lightsail server (1 GB)

**The MVP core** is: chat or form → similar moments → distribution → stress tests → exit
cost → sized verdict → follow-ups.

### Not built, or known gaps (no roadmap file exists in the repo; this list comes from the code and docs)
- **No real users yet.** Adoption isn't verified. This is the biggest gap.
- **No directional edge**, and it is published as such. The product sizes risk; it doesn't
  predict direction.
- **Email alerts are not built.** Alerts go to a webhook, or to Telegram once that's on.
- **No order placement**, by design. It stops at a ticket and a dry-run prompt for Agent Hub.
- **Telegram is off** until a bot token is set.
- **The server is small (1 GB):** the first request after a quiet spell can take 2–6 s,
  and a few seconds more right after a restart.
- **Coverage is 24 tokenized US stocks and ETFs.**

### Natural next steps (suggestions, not built)
1. Get real traders using it and collect feedback.
2. Turn on Telegram so alerts reach people where they are.
3. A bigger server, so it's never slow.
4. More tokens as Bitget lists them.
5. With the user's permission, read their real Bitget positions instead of typed holdings.

---

## 9. In one paragraph

Nightwatch is a pre-trade stress tester for Bitget's tokenized US stocks.
- **The flow:** you describe a trade in a sentence. It finds past moments like now, shows
  what followed, runs fitted stress tests and real crash replays, prices your exit on
  Bitget's live order book, and gives a sized verdict.
- **Personalised:** it checks the verdict against your other positions, your plan, your
  stated reason and your own loss record.
- **The AI's role:** it explains and answers follow-ups but can never change a number.
- **After the decision:** tripwires, plans and next-close re-checks.
- **Proof:** every verdict is scored, receipted and published, misses included.
- **Its purpose:** to stop traders from being surprised by the hours when only the token
  can move.
