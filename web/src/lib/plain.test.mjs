// Run: node --experimental-strip-types src/lib/plain.test.mjs   (Node >= 22.6)
import assert from "node:assert/strict";
import { plainText, stripSourceTags, holdLabel } from "./plain.ts";

assert.equal(stripSourceTags("Worst case is 2,147 USDT [desk]. Half size [safest ways] is fine."), "Worst case is 2,147 USDT. Half size is fine.");
assert.equal(plainText("verdict REDUCE_TO, then NO_GO", "en"), "verdict REDUCE TO, then NO GO");
assert.equal(plainText("verdict REDUCE_TO, then NO_GO", "zh"), "verdict 建议减仓, then 不建议做");
assert.equal(plainText("loss_p5_pct (one-in-twenty loss) -4.2%", "en"), "one-in-twenty loss -4.2%");
assert.equal(plainText("exit_liquidity cap binds at 715", "en"), "the exit liquidity limit holds the size down at 715");
assert.ok(!plainText("exit_liquidity cap binds", "zh").includes("_"));
assert.equal(holdLabel("next_open", "en"), "Until the next US open");
assert.ok(!holdLabel("next_open", "zh").includes("_"));
assert.equal(holdLabel("weird_kind", "en"), "weird kind");
console.log("plain tests ok");
