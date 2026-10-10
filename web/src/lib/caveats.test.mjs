// Run: node --experimental-strip-types src/lib/caveats.test.mjs   (Node >= 22.6)
// The exit-cost caveat must keep saying, in both languages, that the number comes from the
// visible book and has not been checked against real fills.
import assert from "node:assert/strict";
import { EXIT_COST_CAVEAT, EXIT_COST_CAVEAT_SHORT } from "./caveats.ts";

for (const c of [EXIT_COST_CAVEAT, EXIT_COST_CAVEAT_SHORT]) {
  assert.match(c.en, /visible/);
  assert.match(c.en, /not (been )?checked against real fills/);
  assert.match(c.zh, /可见的?挂单/);
  assert.match(c.zh, /未与真实成交核对/);
  // Hidden orders on these books were never confirmed, so the caveat does not name them.
  assert.doesNotMatch(c.en, /hidden/i);
  assert.doesNotMatch(c.zh, /隐藏/);
}
assert.match(EXIT_COST_CAVEAT.en, /estimate/i);
assert.match(EXIT_COST_CAVEAT.zh, /估算/);
console.log("caveats.test ok");
