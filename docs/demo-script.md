# Demo recording script

Target length 3:00, hard ceiling 4:00. Screen recording with voice-over, 1440×900 or
1920×1080, browser zoom 100%, dark theme. Record the whole thing in one take if possible;
the desk answers in about 3 seconds, so there is no dead air to cut.

Before recording:

* Recorder running for at least an hour so the order book is fresh and `/health` is green.
* Run a replay first (`nightwatch replay --tickers TSLA NVDA AAPL MSFT AMZN GOOGL --max-points 100`)
  so the calibration and journal pages have scored forecasts.
* Close other tabs, hide bookmarks, set the window to the recording size.
* Have the ticket fields ready to type: TSLA, long, 20000, equity 200000, stop 350.

---

## 0:00–0:20 The problem

**Screen:** the desk, empty form.

> Tokenized US stocks trade around the clock. The stocks behind them trade six and a half
> hours a day. So for most of every week, this token can move while the market that prices
> it is shut: overnight, weekends, earnings after the close. That gap is where positions
> get hurt, and it is the one thing a backtest never shows you.

## 0:20–0:45 The ask

**Screen:** type the ticket. TSLA, long, 20,000 USDT, equity 200,000, hold until the next
US open, stop 350. Type a real thesis and invalidation. Click "Stress-test this trade".

> This is a trade I am about to place. Twenty thousand dollars of tokenized Tesla, held
> over the weekend, stop at 350. Before I place it I want to know three things: what has
> happened after moments like this one, what could go wrong, and whether I can get out.

## 0:45–1:20 What history says

**Screen:** the verdict banner, then scroll to "What history says". Point at the sample
size, the distribution, the p5, and the "vs random hours" column.

> It found forty distinct past moments that looked like now: same volatility percentile,
> same gap between the token and its fair value, same time of week, same distance to
> earnings. Not forty similar hours, forty separate episodes, because forty consecutive
> hours of the same night would be one event counted forty times.
>
> Here is what followed each one over the same holding period. The median, the win rate,
> and the fifth percentile, which is the number I actually care about. Each one carries a
> confidence interval and a comparison against random hours from the same time of week, so
> I can see when the resemblance is doing nothing.
>
> If it cannot find enough distinct matches it refuses to answer. That happens, and it
> should.

## 1:20–1:55 What could go wrong

**Screen:** scroll to "What could go wrong". Hover a couple of rows.

> These are not invented scenarios. Every one is calibrated from this token's own history.
> The fifth-percentile weekend gap is the fifth percentile of four hundred and twenty-three
> actual closed windows. The earnings gap is the worst of its own past earnings reactions.
> The liquidity drought is today's book divided by five. Each row shows the loss on my
> position, including what it costs to get out.
>
> Underneath, five thousand Monte Carlo paths built by resampling blocks of this token's
> real closed-market hours, so weekend behaviour stays weekend behaviour. And a reverse
> stress: the move that costs me five per cent after exit costs.

## 1:55–2:20 Can I get out

**Screen:** "Getting out" section and the cost curve.

> This is the live order book, walked for my size. Twenty thousand dollars exits at
> twenty-five basis points. The curve shows where it gets expensive. The largest size that
> still exits inside my budget is about sixteen thousand seven hundred. That number comes
> from book snapshots recorded every minute, because nobody publishes the history of how
> deep the book is at three in the morning on a Sunday.

## 2:20–2:45 The verdict, and what would change it

**Screen:** the gate, the caps, then "What would change it".

> Eight discipline checks, five independent size caps, and the smallest one binds. Here it
> is exit liquidity, so the answer is: reduce to sixteen thousand seven hundred and fifty.
>
> And this is the part I use most. The same gate, the same caps, the same verdict, re-run
> at other sizes. It is a go up to seventeen thousand six hundred. Above fifty-one thousand
> the book cannot absorb it at all. The stop column tells me how far my stop can sit before
> the risk budget stops me.

## 2:45–3:00 Does it tell the truth

**Screen:** the calibration page, then the journal page.

> Every forecast is written down before the outcome exists, then scored when the horizon
> passes. A thousand of them so far. The tails were too narrow, so the system widens them
> using factors fitted only on forecasts that had already matured, and this table shows the
> before and after, out of sample.
>
> And here is the journal. Every call, the inputs it was based on, and what actually
> happened. The human still makes the decision. Nightwatch never places an order.

---

## Recording notes

* Do not read the numbers off the screen; say what they mean. The viewer can read.
* When the verdict appears, pause for a beat so the viewer can take in the banner.
* If the analysis takes longer than five seconds, cut the wait in the edit.
* End on the journal page, not on a slide.
