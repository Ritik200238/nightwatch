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
console.log("errors tests ok");
