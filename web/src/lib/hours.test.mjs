// Run: node --experimental-strip-types src/lib/hours.test.mjs   (Node >= 22.6)
// Hours are written with halves rounded up (26.5 -> 27, 27.5 -> 28, 0.5 -> 1 at whole-hour sizes).
import assert from "node:assert/strict";
import { fmtHours } from "./format.ts";

assert.equal(fmtHours(26.5), "27 h");
assert.equal(fmtHours(27.5), "28 h");
assert.equal(fmtHours(0.5), "0.5 h"); // under 10 h one decimal is kept, so nothing is rounded away
assert.equal(fmtHours(10.5), "11 h");
assert.equal(fmtHours(48.5), "49 h (2.0 d)");
assert.equal(fmtHours(null), "—");
console.log("hours.test ok");
