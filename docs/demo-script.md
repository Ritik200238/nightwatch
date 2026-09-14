# Demo recording script

Target length 3:00, hard ceiling 4:00. Screen recording with voice-over, 1440×900 or
1920×1080, browser zoom 100%, dark theme. Record in one take if you can; the desk answers
in about three seconds, so there is no dead air to cut.

**Say what the numbers mean, not what they are.** Every figure on the screen is live and
will differ from the ones written here, so the script quotes almost none of them. The one
rule that matters: never read a number out loud that the viewer can see is different.

Before recording:

* The demo is already live at <https://nightwatch-gules.vercel.app>; record against it
  rather than a local build, so what the judge sees is what you showed.
* Check the header pill says a token count and a recent book time, and open the
  **Data sources** panel once beforehand to confirm all six feeds are green.
* Close other tabs, hide bookmarks, set the window to the recording size.
* Have the ticket ready to type: TSLA, long, 20000, equity 200000, hold until the next US
  open, stop 350, and a real thesis and invalidation in your own words.

---

## 0:00–0:20 The problem

**Screen:** the desk, empty form.

> Tokenized US stocks trade around the clock. The stocks behind them trade six and a half
> hours a day. So for most of every week, this token can move while the market that prices
> it is shut: overnight, weekends, earnings after the close. That gap is where positions
> get hurt, and it is the one thing a backtest never shows you.

## 0:20–0:40 The ask

**Screen:** type the ticket, then click "Stress-test this trade".

> This is a trade I am about to place. Twenty thousand dollars of tokenized Tesla, held
> over the weekend, stop at 350. Before I place it I want three things: what happened after
> moments like this one, what could go wrong, and whether I can get out.

## 0:40–1:10 What history says

**Screen:** the verdict banner, then scroll to "What history says". Point at the sample
size, the fifth percentile, and the "vs random hours" column.

> It found forty distinct past moments that looked like now: same volatility percentile,
> same gap between the token and its fair value, same time of week, same distance to
> earnings. Forty separate episodes, not forty consecutive hours of one night counted forty
> times.
>
> Here is what followed each one over my holding period. The number I care about is the
> fifth percentile — the bad case I am sizing against. Next to it is a comparison against
> random hours of the same kind, so I can see when the resemblance is doing nothing. On
> this one it mostly is, and the desk says so rather than hiding it.
>
> If it cannot find enough distinct matches it refuses to answer. That happens, and it
> should.

## 1:10–1:40 What could go wrong

**Screen:** scroll to "What could go wrong". Hover a couple of rows.

> These are not invented scenarios. Every one is calibrated from this token's own history.
> The fifth-percentile weekend gap is the fifth percentile of its actual closed windows.
> The earnings gap is the worst of its own past earnings reactions. The liquidity drought
> is today's book divided by five. Each row shows the loss on my position, including what
> it costs to get out of it.
>
> Underneath, five thousand Monte Carlo paths built by resampling blocks of this token's
> real closed-market hours, so weekend behaviour stays weekend behaviour. And a reverse
> stress: the move that costs me five per cent after exit costs.

## 1:40–2:00 Can I get out

**Screen:** "Getting out", the cost curve, then the by-time-of-week table under it.

> This is the live order book, walked for my size, and the largest size that still exits
> inside my budget. Then the same book read by time of week, from snapshots recorded every
> minute — because nobody publishes the history of how deep the book is at three in the
> morning on a Sunday. On a weeknight this size always fits. At the weekend, often it does
> not.

## 2:00–2:25 The verdict, and what would change it

**Screen:** the gate, the caps, then "What would change it".

> Nine discipline checks, five independent size caps, and the smallest one binds. The gate
> is built to decide, not to abstain: if I had left the stop out, it would not refuse — it
> would tell me it is sizing against the calibrated fifth percentile instead.
>
> And this is the part I use most. The same gate, the same caps, the same verdict, re-run
> at every other size and stop distance. Not an estimate of the verdict — the verdict.

## 2:25–2:40 The case against

**Screen:** "The case against this".

> Whatever it decides, it then argues the other side, using only numbers from this report,
> ranked by what they are worth in money. When it says go, this is the strongest reason not
> to. I have never seen a tool do this to its own answer.

*After the take:* the report footer has **copy link**. Paste that link into the
submission form as the worked example — it reopens this exact verdict for anyone.

## 2:40–3:00 Does it tell the truth

**Screen:** the calibration page, then the journal.

> Every forecast is written down before the outcome exists, then scored when the horizon
> passes. Two and a half thousand of them so far. The raw tails were too narrow — that
> light is red and it stays red — so the system widens them using factors fitted only on
> forecasts that had already matured, and this shows the before and after, out of sample.
> It also shows that the retrieval barely beats picking random hours, which is not
> flattering and is the point.
>
> The journal is every call it has made, the hash of the inputs it used, and what actually
> happened. The human still decides. Nightwatch never places an order.

---

## If you have thirty seconds more

Open the **Chat** tab and type "hold 20k of TSLA through the weekend, stop at 350".

> Plain language in, the same numbers out. If there is no model key on the server, a parser
> reads the sentence instead and the briefing is assembled from the report's own fields, so
> the desk cannot go quiet and cannot make a number up.

Or open the **Data sources** panel.

> Six live feeds, when each was last pulled, and the newest thing in each. Including SEC
> filings timed to the second they were accepted, because most 8-Ks land after the US close
> — when the stock cannot react and the token can.

---

## Recording notes

* Do not read the numbers off the screen; say what they mean. The viewer can read.
* When the verdict appears, pause for a beat so the viewer can take in the banner.
* If the analysis takes longer than five seconds, cut the wait in the edit.
* End on the journal page, not on a slide.
