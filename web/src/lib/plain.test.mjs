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

// Chinese reports: gate reasons and caveats the engine writes in English are translated from their fixed shapes.
import { ruleReason, warningText, plainReason, capDetail } from "./plain.ts";
assert.equal(ruleReason("position is 40.0% of equity (limit 25.0%)", "zh"), "仓位占账户 40.0%（上限 25.0%）");
assert.equal(ruleReason("risk 1.91% of equity (analog 5th-percentile loss) exceeds 1.0%", "zh"), "风险占账户 1.91%（相似历史时刻的二十分之一亏损），超过上限 1.0%");
assert.equal(ruleReason("risk 1.91% of equity (analog 5th-percentile loss) exceeds 1.0%", "en"), "risk 1.91% of equity (one-in-twenty loss from past moments) exceeds 1.0%");
assert.equal(ruleReason("missing thesis, invalidation", "zh"), "缺少理由和“错在哪里”");
assert.match(ruleReason("no stop order; sized on the 5th percentile (-4.0%) instead; your 'wrong if' line is 28% away, but it is an invalidation, not a stop order", "zh"), /^没有止损单/);
assert.match(warningText("Bitget's US-stock data (analysts, insiders, live quote) is unavailable since 15:59 UTC (HTTP 503); this report has no street section", "zh"), /^Bitget 美股数据/);
assert.equal(plainReason("written_plan: missing thesis", "en"), "Plan is incomplete: your reason and 'wrong if' line are missing".replace("your reason and 'wrong if' line are", "your reason is"));
assert.equal(plainReason("written plan: missing thesis, invalidation", "en"), "Plan is incomplete: your reason and 'wrong if' line are missing");
assert.equal(plainText("regime cap binds at 715", "en"), "the market-conditions limit holds the size down at 715");
assert.equal(capDetail("1.0% of equity at risk over a 3.96% analog p5 loss", "en"), "1.0% of equity at risk over a 3.96% one-in-twenty loss from past moments");
console.log("plain zh tests ok");
