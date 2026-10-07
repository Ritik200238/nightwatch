# Nightwatch — Final QA Report

## 1. Summary and readiness
- The pipeline from question to verdict, the journal, the public pages and the chat all work on the live site.
- CI on main passed on d686070.
- The last live check was "long 10k TSLA tonight 500x". It returned NO GO and capped leverage at 75x. It also said "Next: lower the leverage, the liquidation price is too close at this size". That wording is the fix from PR #7.
- Method freeze 3 is tagged. Nothing in the frozen code has changed since the tag.
- Readiness: ready to judge on what is built. The weak spots are listed in parts 6 and 7.

## 2. Features
- **Stress test and verdict:** works. Retested after each fix.
- **Wording and display:** rewording the plain-language explanations and ordering the NO GO reasons first are fixed and retested. The liquidation next-step is fixed and checked live.
- **Chat (including streaming):** works. Long histories are trimmed, and absurdly long ones are rejected with a plain message. Retested.
- **Chinese view:** works. Some server messages still show in English (see part 6).
- **Journal, receipts, Bitcoin anchors, calibration, misses, studies:** work. Page figures match the live API.
- **Status page:** fixed so it shows the newest anchor, and it matches the API. Retested.
- **Phone layout:** tap targets reach 40 px. The small provenance chips pass because their hit area is expanded.
- **Site proxy:** only real outages (502, 503, 504) fall back to the saved snapshot now. Other server errors show up as they are.
- **MCP server and the Agent Hub skill file:** work.
- **Bitget US-stock data:** wired, but the service returns nothing. This is an outside problem.

## 3. User flows
- Ask a trade, get a verdict, ask "why?", try a what-if.
- Missing account size: it asks for it.
- Absurd leverage: it caps at 75x and says so.
- Dividend question: answers in 0.4 s.
- Refresh and back navigation: fixed race condition where static example report flashed beside a restored chat.
- Phone width: verified on 390x844 without horizontal overflow.
- Chinese view: UI labels translated, no mid-word line breaking.
- Public pages and the Bitcoin proof: all verified.
- All of these work. The AWS Lightsail box is slow on first answers (12–40 s) when cold until process memory and caches warm up.

## 4. Bugs
- No exact tally was kept of every bug across the whole pass, so the totals in part 8 are estimates.
- The fixes in this stretch:
  - The status page showed the oldest anchor instead of the newest.
  - Hold lengths were measured wrongly in places. Weekends were counted from now instead of Friday's close, Sunday evening read the weekday in UTC, and horizons rounded half to even.
  - The site proxy hid real server errors behind the saved snapshot.
  - Phone tap targets were too small.
  - The README and proof figures overclaimed (studies, token count).
  - NO GO reasons were in the wrong order.
  - Huge ids and closed-hours requests gave bad errors.
  - A NO GO from liquidation risk told the user to "write a plan" instead of lowering the leverage.
  - Reloading with a stored chat briefly or permanently showed the TSLA example report next to the restored chat. Fixed with `restoring` skeleton and `!heroUsed` guard.
  - On `/journal`, the 60 newest rows are in-flight awaiting horizon maturity, which previously read as "0 scored" / "none has landed". Fixed by clarifying in-flight status and cross-linking to the 1,274+ scored historical record on `/calibration` and `/wrong`.
  - The report receipt line was a dense single wrapped paragraph with sub-40px touch targets. Fixed with a structured hairline layout and 40px link.
- Each was fixed at the source and retested. Regression tests were added for the logic fixes.

## 5. Regression testing
- Full CI on every pull request and on main: lint, about 1,500 tests, and the web build. All green.
- Live spot checks after each deploy.
- The proof-sync tool checks README and submission figures against the live API.
- Automated Playwright smoke tests (`web/e2e/smoke.mjs`) verify 14 core flows against production.

## 6. Remaining issues and limits
- **Calibration and study refit:** NOT DONE. It needs a bigger server, which the user is upgrading. Until then the tail factors were fitted on replays made with the earlier search. The freeze file says this openly.
- **Backfill:** the universe is 24 live tokens. Backfilling the other 88 was not run.
- **Studies:** the 12th study is built but not run on production.
- **Bitget US-stock data:** empty or 503 from the service itself.
- **GetAgent playbook:** not built. It needs the user's Bitget API key.
- **Minor items, not fixed:**
  - The `/tonight` rejection message is silent.
  - The not-found `/r/` page says "Try again".
  - A "wrong if" on the wrong side of a short is accepted silently.
  - `HEAD /api/health` returns 405.
  - The stress presets jump at a 40 h hold (frozen area).
  - Some server strings still show in English in the Chinese view.
- **Real users:** zero so far.

## 7. Risks with judges
- An idle Lightsail server makes the first answer slow, so warm the site once before judging.
- The history headline numbers are optimistic. Only forecasts made after 7 Oct 00:00 UTC are truly out of sample, and there will be very few by Oct 8. The freeze file says this.
- Rivals may add features before the deadline.
- The Bitget stock data gap could show up if a judge tries equities.
- NOT VERIFIED: that a judge will rate us best in the sub-theme. That is an opinion, with no proof either way.

## 8. Counts (approximate)
- **Features tested:** about 15 areas.
- **Flows tested:** about 10.
- **Bugs:** a few dozen found and fixed. About 6 minor ones remain, plus the outside and server-upgrade items in part 6.
- **Automated checks:** about 1,500 tests, ruff, web build and Vercel preview. All pass on main.
- **Overall:** judge-ready, with the limits above stated openly.
