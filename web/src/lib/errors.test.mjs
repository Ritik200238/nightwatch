// Run: node --experimental-strip-types src/lib/errors.test.mjs   (Node >= 22.6)
import assert from "node:assert/strict";
import { friendlyDetail, ticketProblems, busyMessage, stillBusyMessage } from "./errors.ts";

const huge = [{ type: "less_than_equal", loc: ["body", "notional_quote"], msg: "Input should be less than or equal to 10000000", ctx: { le: 10000000 } }];
assert.equal(friendlyDetail(huge, 422, "en"), "Size must be between 1 and 10,000,000 USDT.");
assert.equal(friendlyDetail(huge, 422, "zh"), "仓位须在 1 到 10,000,000 USDT 之间。");
// The same list arriving as a string (how an older proxy or client passed it on).
assert.equal(friendlyDetail(JSON.stringify(huge), 422, "en"), "Size must be between 1 and 10,000,000 USDT.");
assert.equal(friendlyDetail([{ type: "greater_than", loc: ["body", "notional_quote"], ctx: { gt: 0 } }], 422, "en"), "Size must be more than 0 USDT.");
assert.equal(friendlyDetail([{ type: "less_than_equal", loc: ["body", "leverage"], ctx: { le: 125 } }], 422, "en"), "Leverage can be at most 125x.");
assert.equal(friendlyDetail([{ type: "missing", loc: ["body", "ticker"] }], 422, "en"), "Token is required.");
assert.ok(!friendlyDetail([{ type: "weird", loc: ["body", "x"] }], 422, "en").includes("{"));
// Developer text never reaches the page.
assert.equal(friendlyDetail("Cannot reach the Nightwatch API from the server. Is the backend running?", 502, "en"), stillBusyMessage("en"));
assert.ok(!/backend/i.test(stillBusyMessage("en")));
assert.equal(friendlyDetail("A stop for a long must be below the current price (378.00).", 422, "en"), "A stop for a long must be below the current price (378.00).");
assert.equal(busyMessage("en"), "The desk is busy, retrying…");

const ok = { ticker: "TSLA", side: "long", notional: 20000, equity: 200000, stop: null, hours: null, hoursNeeded: false, leverage: null };
assert.deepEqual(ticketProblems(ok, 378, "en"), {});
assert.equal(ticketProblems({ ...ok, notional: -500 }, null, "en").notional, "Enter a size above 0 USDT.");
assert.equal(ticketProblems({ ...ok, notional: 0 }, null, "en").notional, "Enter a size above 0 USDT.");
assert.equal(ticketProblems({ ...ok, notional: 99999999999 }, null, "en").notional, "Size must be between 1 and 10,000,000 USDT.");
assert.equal(ticketProblems({ ...ok, stop: 450 }, 378, "en").stop, "A stop for a long must be below the current price (378).");
assert.equal(ticketProblems({ ...ok, side: "short", stop: 300 }, 378, "zh").stop, "做空的止损必须高于当前价格（378）。");
assert.equal(ticketProblems({ ...ok, stop: 450 }, null, "en").stop, undefined);
assert.equal(ticketProblems({ ...ok, ticker: "" }, null, "en").ticker, "Pick a token.");
assert.equal(ticketProblems({ ...ok, hoursNeeded: true }, null, "zh").hours, "请输入小时数。");
// Size edge cases, both languages: negative, zero, NaN (empty field), the exact limits, huge.
for (const lang of ["en", "zh"]) {
  for (const bad of [-1, 0, -0.01, NaN, Infinity]) assert.ok(ticketProblems({ ...ok, notional: bad }, null, lang).notional, `notional ${bad} ${lang}`);
  assert.ok(ticketProblems({ ...ok, notional: 10_000_001 }, null, lang).notional);
  assert.ok(ticketProblems({ ...ok, notional: 0.5 }, null, lang).notional);
  assert.equal(ticketProblems({ ...ok, notional: 1 }, null, lang).notional, undefined);
  assert.equal(ticketProblems({ ...ok, notional: 10_000_000 }, null, lang).notional, undefined);
}
assert.equal(ticketProblems({ ...ok, notional: -5 }, null, "zh").notional, "请输入大于 0 的 USDT 金额。");
// Equity: zero, negative and absurd are refused; empty (null) is allowed.
assert.ok(ticketProblems({ ...ok, equity: 0 }, null, "en").equity);
assert.ok(ticketProblems({ ...ok, equity: -10 }, null, "zh").equity);
assert.ok(ticketProblems({ ...ok, equity: 2e9 }, null, "en").equity);
assert.equal(ticketProblems({ ...ok, equity: null }, null, "en").equity, undefined);
// Stops: zero and negative are refused with or without a price; the wrong side needs the price.
assert.equal(ticketProblems({ ...ok, stop: 0 }, null, "en").stop, "A stop must be a price above 0.");
assert.equal(ticketProblems({ ...ok, stop: -3 }, 378, "zh").stop, "止损必须是大于 0 的价格。");
assert.equal(ticketProblems({ ...ok, stop: 378 }, 378, "en").stop, "A stop for a long must be below the current price (378).");
assert.equal(ticketProblems({ ...ok, stop: 360 }, 378, "en").stop, undefined);
assert.equal(ticketProblems({ ...ok, side: "short", stop: 378 }, 378, "en").stop, "A stop for a short must be above the current price (378).");
// Leverage and hours.
assert.ok(ticketProblems({ ...ok, leverage: 0 }, null, "en").leverage);
assert.ok(ticketProblems({ ...ok, leverage: 126 }, null, "zh").leverage);
assert.equal(ticketProblems({ ...ok, leverage: 125 }, null, "en").leverage, undefined);
assert.ok(ticketProblems({ ...ok, hoursNeeded: true, hours: -4 }, null, "en").hours);
console.log("errors tests ok");
