# buildathon.md — Bitget AI Base Camp Hackathon S2 (Master Reference)

> Single source of truth for this repo. Everything below is extracted from the official
> S2 handbook + landing page. **Contradictions in the official text are flagged in
> Section 12 — do not treat this doc as internally consistent where the source isn't.**
>
> Written: 2026-09-10. Deadline: 2026-09-21 (UTC+8). **11 days left.**

---

## 0. TL;DR — what actually matters

| Thing | Answer |
|---|---|
| Theme | **AI × US stock trading**, especially **tokenized US stocks (rToken)** trading 24/7 |
| Core insight the organizers care about | US markets close, but rToken keeps trading. Macro news breaks on weekends. Humans sleep, Agents don't. |
| Deadline | **2026-09-21, UTC+8** — one Google Form submission |
| Registration | **None.** Submitting the form = registering. |
| Prize pool | 50,000 USDT total (see Section 12 for the math gap) |
| Tracks | 3 (Alpha Factory / Agentic Trading / AI Trading Desk) |
| Max entries per team | **2**, must be different themes, different projects, separate form submissions |
| Hard-fail conditions | Missing X post, missing project description, or inaccessible materials → **invalid, not judged** |
| Best odds | Named sub-theme = **1 winner out of everyone who picked it**. Pick a thin sub-theme. |
| Free stacking wins | University Special Prize + Fan Favorite + Demo Day all stack differently — see Section 4 |

**Realistic time math (today is 9/10):** Agentic Trading wants a paper-trading log
"recommended ≥2 weeks". If you start the log today you get **11 days**, not 14. The
handbook says "starting 9/3 meets minimum duration" — that window has passed. Either
start logging **today** and label it honestly (11 days), or pick a track that doesn't
need a live log (Alpha Factory backtests, or AI Trading Desk).

---

## 1. Event facts

| Item | Detail |
|---|---|
| Name | Bitget AI Base Camp Hackathon S2 ("Genesis Season 2" / "Builder OS") |
| Period | 2026-09-03 → 2026-09-21 (submission deadline, UTC+8) |
| Format | Global, fully online |
| Total pool | **50,000 USDT** |
| Organizer | Bitget |
| Token sponsor | Alibaba Cloud Qwen |
| Partners | Bitget Wallet, Foresight, Arbitrum, Solana, Tether Foundation, Kaito AI, Cysic, Wave, 706, 7 university blockchain associations (30+ ecosystem partners total) |
| Judges | 30+ industry figures (Gracy, Filippo Dune, Henry Kite, Vlad Evedex, +26); full list TBA |
| S1 scale | 700+ AI Agents submitted — expect heavy competition |
| Hashtags | `#AgenticTrading` `#BuilderOS` `#BitgetHackathon` |

---

## 2. Timeline (UTC+8)

| Date | What happens |
|---|---|
| **9/3** | Opens. Submissions + Qwen credit applications open. Can submit day one. |
| **9/3 – 9/21** | Build period. Post progress on X throughout (feeds the Best Spread Award). |
| **9/21** | **SUBMISSION DEADLINE.** After it, Bitget publishes all valid project IDs at once and opens public voting on X. |
| **9/22 – 9/28** | Public voting on X (comment your project ID). *Handbook also says 9/22–10/7 elsewhere — see §12.* |
| **9/22 – 10/7** | Judge review, runs **in parallel** with voting. Neither replaces the other. |
| **10/8** | Winners announced, including Fan Favorite + audience-linked awards. |
| **From 10/9** | Demo Day, Spotlight content, prize payouts. |

---

## 3. The three tracks

### 🟦 Track 1 — Alpha Factory (Quantitative Strategies)

**Positioning:** Use AI as a *tool* to build runnable US-stock quant/algo strategies.
AI writes the code, tunes parameters, generates signals. **The judged thing is strategy
effectiveness and verifiability — not the AI.**

**Scoring mechanism: 100% quantitative.** No subjective judge points. Your numbers win
or lose it. This is the most objective track and the least gameable by pitch quality.

**Named sub-themes (5):**

1. **Arbitrage** — instantaneous spreads between rToken and native stock, cross-platform
   spreads, NAV premium/discount arbitrage under mint/redeem mechanics.
   *Examples:* sell when rToken price > NAV via mint; cross-platform spread; same
   underlying from different issuers (Ondo vs xStocks).
2. **After-Hours Information Pricing** — macro events keep happening while US markets are
   shut; rToken trades 24/7 and prices that information early.
   *Examples:* build rToken positions on weekend geopolitical/policy events; hedge after
   overnight macro decisions; close before Monday open.
3. **Cross-Market Correlation Strategies** — correlation shifts between rToken and native
   stock across sessions; rToken ↔ crypto cross-asset correlation.
   *Examples:* pre/post-market pairs trading; mean-reversion when rToken overreacts to a
   macro shock that the native stock hasn't priced yet.
4. **rToken Factor Strategies** — classic factors behave differently under rToken's
   low-liquidity, retail-dominated microstructure.
   *Examples:* rToken momentum vs native-stock momentum; mean reversion inside
   closed-market windows; factor-divergence arbitrage.
5. **Cross-Asset Allocation / Rotation** — macro-driven switching, capital flows, risk
   appetite. *Examples:* risk-on/off rotation (US stocks ↔ crypto ↔ commodities);
   sector rotation; weekend hedging.

**Open Theme (2 slots, top 1 each):** anything else centered on US-stock AI quant.
Officially suggested directions (examples, *not* extra named themes):
- **Execution-aware alpha** — alpha that accounts for fees, slippage, funding, market
  impact, and strategy capacity.
- **Market regime / adaptive portfolio** — signals, positions and risk budgets that shift
  across market regimes.

**Required materials:**

| Material | Where | Requirement |
|---|---|---|
| Alpha source description (signal / spread logic) | Project Description field | Required |
| Strategy code | Submission Materials Link | Required (GitHub etc.) |
| Backtest record | Materials link (summary metrics may go in the description) | **Total period ≥ 60 days, out-of-sample ≥ 30 days.** Market-making strategies may substitute continuous high/low-volatility environment records. |
| Compliant X post | X Post field | Required |

**Judging focus:** Sharpe, Sortino, max drawdown, turnover; **out-of-sample Sharpe decay
(alert threshold: OS Sharpe < 0.5 × IS Sharpe)**; rolling 30-day Sharpe stability.

> Read that alert threshold literally: an overfit strategy whose out-of-sample Sharpe
> collapses below half the in-sample Sharpe is explicitly flagged. A modest, stable
> Sharpe beats a spectacular in-sample one that decays.

---

### 🟩 Track 2 — Agentic Trading (Agent Trading)

**Positioning:** The **LLM is the primary decision-maker**, not an assistant. The Agent
must sense the environment, judge independently, and place orders autonomously with risk
controls. If a human approves each trade, it belongs in Track 3, not here.

**Scoring mechanism: 50% quantitative + 50% judge subjective.**

**Named sub-themes (5):**

1. **Event-Driven Agent** — news / announcements / macro events drive autonomous trading.
   *Examples:* policy speech → LLM interpretation → rebalance; earnings beat → add;
   rate decision → hedge rotation.
2. **Market Sentiment Agent** — real-time social / forum / X sentiment → position signals.
   *Examples:* FOMO detection → contrarian hedge; sentiment-top detection; cut before
   overheating.
3. **Earnings-Driven Trading Agent** — Agent reads earnings reports / conference calls and
   executes. *Examples:* EPS beat → add; guidance cut → reduce; post-earnings drift.
4. **Cross-Asset Execution Agent** — Agent runs rToken and crypto positions at the same
   time. *Examples:* hedge crypto when rToken shows anomalies; dynamic cross-market
   allocation after a macro shock.
5. **Factor Discovery Agent** — Agent autonomously proposes hypotheses, mines alpha
   factors, backtests iteratively, then trades on what validates.

**Open Theme (2 slots, top 1 each):** any LLM-autonomous decision system with trading
output. Officially suggested direction (an example, not an extra named theme):
- **Agent evaluation / benchmarks** — measuring decision consistency, risk-violation rate,
  max drawdown, behavior under stress, human-takeover rate, and **incremental value over
  a fixed-rule baseline or a Human+AI baseline**.

> Note the landing page lists only 5 sub-themes for this track and omits "Open theme × 2",
> while Chapter IV includes it. Chapter IV governs. See §12.

**Required materials:**

| Material | Requirement |
|---|---|
| Runnable Demo | Required |
| Event → decision → execution flow demonstration | Required (described in Project Description; video/demo link optional but strongly advised) |
| **Paper trading log** | **Required** — must be actually run during the competition period, ≥2 weeks recommended |
| Compliant X post | Required |

**Judging focus:** paper-trading Sharpe, max drawdown, win rate; **decision
explainability**; Agent architecture quality; **risk control layer effectiveness**.

> Half the score is subjective. That half is bought with: a legible architecture, a real
> risk layer that visibly blocks bad trades, and decision logs a judge can read and
> follow. S1 winners leaned exactly this way — see §9.

---

### 🟧 Track 3 — AI Trading Desk (AI Research Workbench)

**Positioning:** Natural-language-driven research workbench. AI processes information,
calls tools, presents analysis. **The human trader makes the final call.**

**Scoring mechanism: 100% judge subjective.** Highest ceiling for a great demo, highest
risk if your product doesn't land visually.

**Named sub-themes (5):**

1. **Information Extraction & Signal Generation** — AI processes unstructured earnings /
   macro / news. *Examples:* conference-call summary + expectation-gap detection;
   rate / inflation / geopolitical transmission chains.
2. **Review & Self-Evolution** — post-trade, AI helps the trader review and iterate their
   research framework. *Examples:* auto-generated review reports; identifying bad decision
   patterns; reusable checklists.
3. **Decision Stress Testing** — before opening a position, AI retrieves historically
   similar scenarios. *Examples:* input trade idea → retrieve historical distribution;
   preset stress tests.
4. **Personalized Research Workbench** — a customized workbench with a clear thesis.
   *Examples:* tech-stock event-driven workflow; macro quant toolset.
5. **Execution Assistance** — after the decision, AI handles order splitting and slippage.
   *Examples:* large-order splitting; order-book depth analysis; slippage-pattern
   adjustment.

**Open Theme (2 slots, top 1 each):** AI-assisted tools / workbench / LUI for human
traders. Officially suggested direction (an example, not an extra named theme):
- **Portfolio-aware AI PM / Portfolio Copilot** — evaluates how a *proposed* trade changes
  beta, sector and factor exposures, correlation, and concentration across an *existing*
  portfolio, with stress tests or hedge suggestions.

**Required materials:**

| Material | Requirement |
|---|---|
| Accessible Demo | Required |
| One complete research task demo (question → actionable insight, full flow) | Required |
| Compliant X post | Required |

**Judging focus:** feature depth (**number and effectiveness of data sources / Skill
integrations**), research quality, **LUI fluency**, personalized thesis.

> "LUI" = Language User Interface. Fluency of the conversational experience is explicitly
> scored. So is *how many* data sources / Skills you wired in and whether they actually
> work. A shallow one-source chatbot scores badly here by definition.

---

## 4. Prizes — full breakdown

### 4.1 Judge's Main Prizes (work quality; reviewed 9/22 – 10/7)

| Award | Slots | Per winner | Notes |
|---|---|---|---|
| **Grand Prize** | 1 | **3,000 USDT** | Best overall, across the whole hackathon |
| **Theme Prize** (named sub-themes) | 15 | 500 USDT | 5 sub-themes × 3 tracks, **1 winner per sub-theme** |
| **Open Theme Prize** | 6 | 500 USDT | 2 open slots per track, **top 1 each**; no 1st/2nd/3rd tiering |

**Sub-theme mechanics — this is the single most strategic choice you make:**

| What you pick in the form | Award you compete for | Slots |
|---|---|---|
| A named sub-theme (e.g. "Arbitrage") | Theme Prize | **1 winner** for that sub-theme |
| Open Theme | Open Theme Prize | 2 winners per track (1 per open slot) |

Picking a sub-theme is **optional but decisive**: you're competing only against the other
entries that chose the same box. A crowded box ("Event-Driven Agent" is the obvious
default) is a worse bet than a thin one, even if your project is objectively better.

### 4.2 University Special Prize

| Item | Detail |
|---|---|
| Slots / prize | **10 × 500 USDT** |
| How to enter | Submit normally to any main track **and fill the "University Name" field with your full school name** |
| Judging | Separate pool, judged only among entries with a university name filled in |
| **Exclusivity** | **If your entry already won a main-track prize (Grand / Theme / Open), it is NOT eligible for this.** It's a consolation pool, not a bonus. |
| Blank field | Leave it blank → you are not evaluated for it at all |

It is **not** a fourth track — it's an extra review layer on top of a normal submission.
It **is** stackable with a Demo Day invitation.

### 4.3 Best Spread Award (X reach)

| Item | Detail |
|---|---|
| Slots / prize | **3 × 300 USDT** (1 per track) |
| How | Post progress on X while building; attach a compliant X post link at submission |
| Judged on | **Your own / your team's** reach data |
| Not counted | KOL / KOC ghost-posted numbers |
| **Exclusivity** | Already won Grand / Theme / Open → **not eligible** |

### 4.4 Fan Favorite Prize (public vote, paid to the project)

| Item | Detail |
|---|---|
| Slots / prize | **3 × 300 USDT** — highest-voted project per track |
| How | Valid submission by 9/21 + compliant X post; then public voting |
| **Stacking** | **Stacks with everything** — all judge main prizes AND University Special Prize |

This is the only cash award with no exclusivity clause. Free money on top of anything else.

### 4.5 Exclusivity & stacking rules (memorize this)

| Rule | Detail |
|---|---|
| Judge side, same entry | Only the **highest tier** counts: **Grand > Theme / Open > Best Spread** |
| University Special Prize | **Mutually exclusive** with main-track prizes; **not** exclusive with Demo Day |
| Fan Favorite | Stacks with **all** judge prizes and the University Special Prize |
| Multiple entries | Different themed entries from the same team are judged and awarded **separately** |

**Maximum theoretical haul for one entry:** Grand Prize (3,000) + Fan Favorite (300) = 3,300 USDT.
**With two entries:** entry A Grand + Fan Favorite, entry B Theme + Fan Favorite = 4,300 USDT.

### 4.6 Non-cash upside

| Benefit | Detail |
|---|---|
| **Official Spotlight** | From 10/9: interviews, long-form articles, themed tweet series for winners; high-quality non-winners may still get short-form exposure |
| **Demo Day** (post-event) | Open to all submitting teams; **priority invites** to winners / high scorers. Connects to **internships, product beta access, investor networks** |
| How to apply for Demo Day | Tick **"Apply for Demo Day"** in the form (Yes/No; blank = No). **All teams may tick it.** Final list chosen by ops / judges |
| Ecosystem exposure | Official retweets, posting calendar, partner/KOL amplification. Teams who "Build in Public" well are more likely to be picked up |
| Builders Community | Official Telegram — stay connected with S1 alumni + Bitget AI team |
| **Playbook productization** | High-quality entries suited to productization may be invited into **Bitget Playbook's product review and listing process**. If listed and distributed to users, the team **may get to discuss a commercial / revenue-share arrangement.** Not guaranteed by winning. |
| Qwen Build Credits | Separate Google Form. Bitget reviews KYC every 24h. First **300 teams** that apply + pass Bitget KYC get **30U-equivalent** Qwen token credits via the official Telegram |
| K3 Post-Event Subsidy | Tick **"Apply for K3 Token Subsidy"** in the *project submission* form. Opt-in + valid entry → **30U-equivalent** K3 credits. Both programs = up to **60U** total |

---

## 5. Audience side (you can also play this as a voter)

**Voting:**

| Item | Detail |
|---|---|
| Period | 9/22 – 10/7 (UTC+8) *(handbook also states 9/22–9/28 and 9/24–9/29 elsewhere — §12)* |
| Prerequisite | After the 9/21 deadline, Bitget publishes the **full list of valid project IDs at once** |
| Method | **Comment the project ID** in the official voting post = 1 vote |
| Limits | **1 vote counted per account.** Full list published once, no daily updates |
| Who can vote | Anyone. You do not need to be a participant. Participants may rally votes for themselves |

**Audience cash prizes:**

| Award | Trigger | Prize | Announced |
|---|---|---|---|
| **Lucky Draw** | The project you voted for becomes a **Fan Favorite** (any track) | 1,000 USDT pool, **50 random winners × 20 USDT** | From 10/9 |
| **Prediction Prize** | The project you voted for becomes the **Grand Prize** winner | 1,000 USDT split among the **earliest 50 voters** | From 10/9 |

> Prediction Prize rewards the **earliest 50** voters on the eventual Grand Prize winner.
> If you vote (for someone else's project), vote early on 9/22 and pick the strongest.
> You can be participant *and* voter simultaneously.

---

## 6. Submission — exact form fields

**Portal:** Google Form — `https://forms.gle/GyWZCMCPocgJdJon6` (Chinese and English
versions, identical fields). Window 9/3 → 9/21 UTC+8. **Submitting = registering.**

| Field | Req | How to fill |
|---|---|---|
| **Project Description** | ✅ | One long-form answer, six parts (§7). **GitHub README / X thread cannot substitute.** |
| **Role of the LLM in Your Project** | ✅ | Standalone field. What the model actually does (coding, extraction, signal reasoning, agent decisions) + which models. If you got Qwen credits, add where you used Qwen and whether it met your needs. Skip that part if you didn't. |
| **Submission Materials Link** | ✅ | One field for everything: Demo, code, video, docs, logs. |
| **X Promotional Post Link** | ✅ | Must contain `#BitgetHackathon` + `@Bitget_AI`, and be an *interactive promotional post* introducing your product/Agent/strategy. |
| **Track → Sub-theme** | ✅ | Pick track first, then sub-theme. |
| **University Name** | ⚪ | Full school name → enters the university pool. |
| **Apply for Demo Day** | ⚪ | Any team may tick. |
| **Apply for K3 Token Subsidy** | ⚪ | Ticking here is for K3 only; Qwen uses a separate form. |
| **S1 participant? + "Substantive New Additions"** | conditional | If you were in S1, answer Yes and describe what is genuinely new. |

**Two entries = two full separate form submissions.** Different project name, different
materials, re-select track + sub-theme. **Team info / Bitget UID may stay the same.**

### ⛔ Invalid submission (not eligible for review at all)

- Missing a **compliant X post**, or
- Missing the **Project Description**, or
- **Inaccessible** submission materials.

Weak productization / validation answers do **not** invalidate you — they just lower
your score noticeably.

---

## 7. How to write the Project Description (six parts)

Judges weigh **parts 1–3 the most**.

| Part | What a good answer looks like |
|---|---|
| **1 · Thesis** *(highest weight)* | Why you built it and the core hypothesis. **Strategy entries:** signal sources, decision logic, risk controls. **Tool entries:** the pain point you found and why existing solutions fall short. |
| **2 · Target user & product value** | A concrete segment: Retail / VIP / Pro **+ risk appetite, capital size, trading frequency, primary market, use case**. **"All traders" is explicitly not accepted.** Then why that segment needs it. |
| **3 · Validation data & key metrics** | **Strategy/Agent:** test period, returns, Sharpe / Sortino, max drawdown, win rate, turnover, **plus fee and slippage costs**. **Tools:** test users, task completion rate, usage data. **Label every figure as observed / estimated / targeted.** No data yet → describe your validation plan. Then explain how you'll prove effective usage or distribution (users onboarded, volume, AUM, retention). |
| **4 · Progress** | What's built, what isn't, problems hit and how you fixed them, next steps; frameworks / models / APIs used. |
| **5 · Deliverables** | List exactly what's behind the "Submission Materials Link" so judges can find each item. |
| **6 · Your take on AI Trading** *(optional)* | Experience using Bitget AI tools, or your view on Agentic Trading. |

**Two lines that will sink you if you get them wrong:**
- "All traders" in part 2 → explicit rejection of that answer.
- Unlabeled numbers in part 3 → targets presented as results reads as dishonest. Label
  them `observed` / `estimated` / `targeted`. Targets are explicitly allowed
  ("aiming for 50 users in month one") *as long as you label them.*

---

## 8. Materials ↔ form field mapping (all tracks)

| Track | Material | Goes in Project Description | Goes in Materials Link |
|---|---|---|---|
| 🟦 Alpha Factory | Alpha source (signal / spread logic) | ✅ | — |
| | Strategy code | — | ✅ GitHub |
| | Backtest record (≥60d total, ≥30d OOS) | summary metrics OK | ✅ data / report links |
| 🟩 Agentic Trading | Event → decision → execution flow | ✅ | optional video / demo |
| | Runnable Demo | — | ✅ |
| | Paper trading log (run during comp, ≥2wk rec.) | — | ✅ logs / GitHub |
| 🟧 AI Trading Desk | Complete research task (question → insight) | ✅ scenario + conclusions | ✅ demo + optional screen recording |
| | Accessible Demo | — | ✅ |
| **All** | Target user & product value, validation data & metrics | ✅ parts 2–3 | ✅ full data/report if you have it |
| **All** | Role of the LLM (incl. Qwen usage) | ✅ separate field | — |
| **All** | Compliant X post | — | ✅ separate X field |

**Open Theme:** just select "Open Theme" for your track and clearly describe your custom
direction and validation approach in the Project Description. No extra fields.

---

## 9. What S1 winners actually looked like (signal for what judges reward)

S1 had **700+ AI Agents** submitted. Featured entries:

**Nocturne** — tokenized-stock trading continues after US close; generates portfolio
adjustment signals overnight.
- Continuously tracks **7 tokenized US stocks** after market close using Bitget's public
  market data.
- **Publicly reported a negative result:** "backtesting shows that overnight spread
  arbitrage is not necessarily profitable."
- Shipped: online demo + GitHub + X.

**NightDesk** — real-time price verification before every order; trade cancels
immediately if any anomaly is detected.
- **15 strict rules** govern the process: **AI provides analysis only and cannot place
  orders on its own.**
- Playbook backtests strategies, Agent Hub integrates agents, every order goes through a
  security review before execution.
- Shipped: GitHub + X.

**Four themes Bitget itself highlighted from S1:**
1. Tokenized US stocks with 24h trading — Playbooks monitoring markets around the clock.
2. **"The safety belt for trading security"** — risk control and security validation via
   Agent Hub *before* authorizing agents for live trading.
3. **"LLMs are not fortune-tellers, but analysts"** — capable of reading financial reports
   and reviewing strategies trade by trade.
4. **"A strong multi-agent architecture is defined by clear division of responsibilities,
   not packaging concepts."**

**Read-through — what this tells you judges reward:**
- **Honest negative results are publishable and were featured.** Nocturne got spotlighted
  for showing an arb *doesn't* work. Do not fake a profitable backtest.
- **Explicit, enumerable risk rules** ("15 strict rules") read as rigor.
- **Anti-hype framing wins.** "LLM as analyst, not oracle." "Division of responsibility,
  not packaged concepts." Do not pitch a magic money agent.
- **Ship a live demo + public GitHub + X thread.** All featured entries had all three.

---

## 10. Developer toolkit

> ⚠️ **All six repos are cloned into `tools/` and were tested on 2026-09-10. Read
> `tools/README.md` before trusting this section — two claims below did not survive
> verification:**
>
> 1. **No US-stock / rToken support exists in the SDK.** The instrument `category` field is
>    a closed enum of `SPOT, MARGIN, USDT-FUTURES, COIN-FUTURES, USDC-FUTURES`. "Tokenized
>    US stock" appears only in marketing copy. Confirm US-stock symbols are actually listed
>    on Bitget **before** committing to a track.
> 2. **The free `bitget-signal` data backend returns no data.** The MCP server at
>    `datahub.noxiaohao.com` is up and its 19 tool schemas are valid, but every tool returns
>    empty results with empty error strings. Fault isolated to their server (the upstream
>    URLs it names return HTTP 200 from here). `api.bitget.com` itself is fine.
>
> Also: the real code is **not** in `BitgetLimited/agent_hub` (a 114 KB installer shell) —
> it is in five repos under the **`Bitget-AI`** org.

### 10.1 Bitget Agent Hub — `github.com/BitgetLimited/agent_hub`

Trading tools platform: operate a Bitget account from inside Claude / Cursor / Codex.

| Module | Contents | Why it matters |
|---|---|---|
| **MCP Server** | One-line config for Claude Desktop / Cursor / Windsurf / ChatGPT Desktop | Call Bitget trading from your existing AI tool |
| **CLI** | `bgc` terminal tool for Claude Code / Codex CLI / OpenClaw | Terminal AI runs trading commands directly |
| **Tools** | **89 UTA v3 operations** (market data, spot, futures, account & funds, sub-accounts, loans, tax) condensed into **14 intent verbs** | Full capability without context bloat; agents follow discover → drill down → execute |
| **Skills** | Trading Skills (when to call a tool, whether to confirm before ordering) + `bitget-signal`'s 5 research Skills — **no account or API key needed** | Pre-packaged research + execution discipline |
| **Agentic Account** | Dedicated Agent sub-account: **fund isolation, quota control, no withdrawals**; OAuth, no manual API key | Give the Agent its own pot of capital. Purpose-built for the Agentic Trading track |
| **Market & Account Data** | Real-time market/account/trade data across crypto and US stocks (**US stock futures live, spot on the roadmap**) | Feed backtests, paper trading, demos from one source |

**Auto-install prompt (paste into your agent):**

```
Please read https://www.bitget.careers/support/articles/12560603894122
and help me complete the Bitget Agentic account authorization process.
```

**Safe modes — strongly recommended during the hackathon:**
- `--read-only` → fully read-only session.
- `--paper-trading` → routes to Bitget's Demo environment (**needs a separate Demo API
  Key**). **This both validates your pipeline and produces exactly the paper-trading log
  the Agentic Trading track requires.**
- High-risk ops (`cancelAll`, withdrawals) require explicit confirmation by default.
- Any write can be previewed with `dryRun`.

**`bitget-signal` research Skills — 5, zero API key required:**

| Skill | Capability |
|---|---|
| `macro-analyst` | Macro & cross-asset: Fed policy, BTC vs DXY / Nasdaq / Gold |
| `market-intel` | On-chain & institutional: ETF flows, whale activity, DeFi TVL |
| `news-briefing` | News aggregation & narrative synthesis: morning briefings, keyword search |
| `sentiment-analyst` | Sentiment & positioning: Fear & Greed, long/short ratio, funding rates |
| `technical-analysis` | **23 indicators across 6 categories** |

**Official S2 tip on tool-to-track fit:**
- Alpha Factory → use **Playbook** for backtesting.
- Agentic Trading → run on an **Agentic account** (isolated funds, ready right after
  authorization), flow built on **Agent Hub Tools + MCP**.
- AI Trading Desk → combine **`bitget-signal` research Skills as the perception layer**.

### 10.2 Bitget Playbook

AI-driven quant strategy platform. Describe an idea in natural language → AI generates an
executable strategy → backtests on real historical data → shows PnL, max drawdown, Sharpe
→ one-click deploy for automated execution.

Access: log in with your Bitget account. Alpha Factory can use it directly for backtesting
and validation. **Also the pipeline into the Playbook productization / revenue-share
opportunity in §4.6.**

### 10.3 Qwen token subsidy

First **300 teams** that apply and pass **Bitget KYC** get **$30 USD equivalent** in
Alibaba Cloud Qwen credits, keyed to the **team captain's UID**.

| Item | Detail |
|---|---|
| How | Separate Qwen application form (`https://forms.gle/2QeJpvGB5VpipqQ68`), **not** the project form. KYC checked every 24h. Then claim from a Telegram admin. |
| Eligible tools | Cursor, Codex, and similar coding agents. **Claude Code is NOT supported.** |
| Notes | Applying is **not** registration — you still submit the project form. Not applying doesn't affect participation. |

**Config:**

| Setting | Value |
|---|---|
| Base URL | `https://hackathon.bitgetops.com/v1` |
| Model | `qwen3.8-max` |

**Codex setup:** Settings → Config → open `config.toml`, add at top:

```toml
model = "qwen3.8-max"
model_provider = "bitget-qwen"

[model_providers.bitget-qwen]
name = "Bitget Qwen"
base_url = "https://hackathon.bitgetops.com/v1"
env_key = "BITGET_QWEN_API_KEY"
wire_api = "responses"
```

Set the key **outside** `config.toml`: `launchctl setenv BITGET_QWEN_API_KEY 'your key'`
(macOS), verify with `launchctl getenv`. Then **fully quit** Codex (Cmd+Q) and reopen.
Confirm: bottom-right shows `Bitget Qwen`; `codex doctor | grep model` shows `qwen3.8-max`.

**Cursor setup:** Settings → Models (`Ctrl+Shift+J` on Windows). Paste the key into the
OpenAI API Key field → Verify. Enable **Override OpenAI Base URL** →
`https://hackathon.bitgetops.com/v1` (**the `/v1` suffix is required**). `+ Add model` →
`qwen3.8-max` → enable. Select it in Chat/Agent and test.

---

## 11. Rules that will disqualify or downgrade you

1. **No simple reuse of S1 work.** Directly porting an S1 entry, or renaming / minor edits,
   is **not a valid submission**. Continuing an S1 direction is allowed *only* if you
   describe **substantive new additions** in the form — judging evaluates the new content
   only. If you were in S1, tick Yes and fill "Substantive New Additions".
2. **Max 2 themes per team**, each an independent project, each via a **separate form
   submission**. One project + one set of materials per submission.
3. **X post is mandatory and must be substantive.** Pure retweets, or posts with no real
   introduction of your project, = incomplete submission. Must include `#BitgetHackathon`
   and `@Bitget_AI`. You must also retweet the official post.
4. **The Project Description must live in the form.** A GitHub README or X long-form post
   does not substitute.
5. **Materials must be accessible.** A private repo or a dead demo link = invalid.
6. **Best Spread Award excludes KOL/KOC ghost-posted numbers.** Buying reach doesn't count.
7. Backtest minimums are hard for Alpha Factory: **≥60 days total, ≥30 days out-of-sample.**
8. **No trading experience needed.** All tracks accept backtest / simulated / paper trading
   as validation.
9. **Solo is fine.** Enter "Individual" in the Team Members field. Equal opportunity.

---

## 12. ⚠️ Contradictions and gaps in the official material

These are real inconsistencies in the source text. Confirm in the official Telegram before
relying on any of them.

| # | Conflict | Where |
|---|---|---|
| 1 | **Voting window:** "9/22 – 10/7" (Ch. II) vs "9/22 – 9/28" (Ch. III timeline + landing page) vs "9/24 – 9/29" (Ch. VI FAQ) | Three different windows stated |
| 2 | **Judge review window:** "9/22 – 10/7" (Ch. II) vs "9/22 – 9/28" (Ch. III timeline) | Two different windows |
| 3 | **Best Spread submission date:** "attach a compliant X post link at submission on **9/21**" (Ch. II) vs "attach compliant X post at submission on **9/23**" (Ch. VI FAQ) | Deadline is 9/21; treat 9/23 as an error |
| 4 | **Sub-theme count:** form field says "**18 named topics + 3 Open Themes**" (= 21) but the tracks list 5 named + 1 open per track (= 15 named + 3 open = 18 total options) | Ch. IV general requirements table |
| 5 | **Agentic Trading open theme missing on landing page** — landing page lists 5 sub-themes with no "Open theme × 2"; Chapter IV includes it. AI Trading Desk landing list also omits it | Landing page vs Ch. IV |
| 6 | **Prize math doesn't reach 50,000 USDT.** Accounted: 3,000 + (15×500) + (6×500) + (3×300) + (3×300) + (10×500) = **20,300**, plus audience 1,000 + 1,000 = **22,300**. **~27,700 USDT unaccounted for.** | Ch. II vs stated total |
| 7 | **"Fan Favorite announced the same day"** (landing page, 9/22–9/28 row) vs winners announced 10/8 (Ch. III) | Landing page vs handbook |
| 8 | **Several TBD placeholders**: official retweet post link, public voting post link, judge list | Ch. III / Ch. V |
| 9 | **Qwen application link** appears once as `forms.gle/2QeJpvGB5VpipqQ68` and once as "[TBD]", and the Ch. III step text mistakenly points the Qwen form at the *project* form URL | Ch. II vs Ch. III vs Ch. VI |
| 10 | **Paper-trading duration is not achievable from today.** "≥2 weeks recommended, starting 9/3 meets minimum" — starting 9/10 yields 11 days max | Ch. IV |

---

## 13. Strategy notes for this repo

**Track selection, by what you're strongest at:**

| If your edge is… | Go | Why |
|---|---|---|
| Real quant / stats, honest backtesting | 🟦 Alpha Factory | 100% quantitative scoring — no pitch skill needed, numbers decide |
| Systems architecture + risk engineering | 🟩 Agentic Trading | 50/50 split rewards a legible architecture and a working risk layer |
| Product design + demo craft | 🟧 AI Trading Desk | 100% subjective — a deep, beautiful, multi-source workbench can win outright |

**Odds arithmetic:** a named sub-theme has exactly **1 winner**. With 700+ S1 entries as
the base rate, expect the obvious boxes (Event-Driven Agent, Arbitrage, Information
Extraction) to be heavily crowded and the awkward ones (rToken Factor Strategies, Review &
Self-Evolution, Execution Assistance, Decision Stress Testing, Factor Discovery Agent) to
be thin. **Pick a thin box.** Open Theme has 2 winners per track but attracts everyone who
couldn't fit a box.

**Free-money checklist — costs nothing, ticked at submission:**
- [ ] Tick **Apply for Demo Day** (any team may; stacks with everything)
- [ ] Tick **Apply for K3 Token Subsidy** (30U, opt-in only)
- [ ] Fill **University Name** *if applicable* — **but note it's mutually exclusive with
      main-track prizes**, so it only helps if you don't expect to win a main prize
- [ ] Apply for **Qwen credits** on the separate form (30U; not usable with Claude Code)
- [ ] Post on X *throughout* the build, not just once — Best Spread is judged on reach
- [ ] Retweet the official post (required, separate from your own post)

**Deliverable minimum bar (any track):** live accessible demo + public GitHub + X thread
with `#BitgetHackathon` `@Bitget_AI` + a Project Description that answers all six parts
with labeled numbers.

**Honesty is scored, not punished.** S1 spotlighted a project whose headline finding was
"this arb doesn't actually work." Label numbers `observed` / `estimated` / `targeted`.
Report costs (fees, slippage, funding). Show out-of-sample decay rather than hiding it.

---

## 14. Links

| Resource | URL |
|---|---|
| Submission form | https://forms.gle/GyWZCMCPocgJdJon6 |
| Qwen credits form | https://forms.gle/2QeJpvGB5VpipqQ68 |
| Official Telegram | https://t.me/+o1tYqQ_lXxllYjgy |
| Event landing page | https://www.bitget.com/activity-hub/hackathon |
| S2 Handbook | https://bitget-ai.gitbook.io/bitgetai_hackathons2/ |
| Agent Hub GitHub | https://github.com/BitgetLimited/agent_hub |
| Bitget Playbook | https://www.bitget.com/zh-CN/activity/ai-get-agent/playbook?tab=explore |
| Official X | https://x.com/Bitget_AI |
| Agentic account authorization doc | https://www.bitget.careers/support/articles/12560603894122 |
| Public voting post | TBD — published from 9/22 |
| Official post to retweet | TBD |

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **rToken** | Tokenized US stock. Trades 24/7 on-chain, unlike the underlying equity. The central object of this hackathon. |
| **NAV premium/discount** | Gap between an rToken's market price and the net asset value of the underlying stock it represents. Arbitrage target via mint/redeem. |
| **Mint / redeem** | Creating or destroying rTokens against the underlying — the mechanism that closes a NAV gap. |
| **Issuers** | Ondo, xStocks, and others — the same underlying stock can exist as rTokens from different issuers, creating cross-issuer spreads. |
| **OS / IS Sharpe** | Out-of-sample vs in-sample Sharpe. Alert threshold: OS < 0.5 × IS. |
| **LUI** | Language User Interface — the conversational UX layer. Explicitly scored in Track 3. |
| **UTA v3** | Bitget's unified trading account API version behind Agent Hub's 89 operations. |
| **Paper trading** | Simulated execution against real market data. Bitget's Demo environment via `--paper-trading` produces the required logs. |
| **KOL / KOC** | Key Opinion Leader / Consumer. Their ghost-posted reach is excluded from Best Spread. |
| **Build in Public** | Posting progress openly during the build. Explicitly increases odds of official amplification. |
