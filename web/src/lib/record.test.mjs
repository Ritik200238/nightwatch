// Run: node --experimental-strip-types src/lib/record.test.mjs   (Node >= 22.6)
// The live record says its denominators: forecasts, the distinct events they cover, and the nights.
import assert from "node:assert/strict";
import { recordCountsText } from "./record.ts";

// /misses totals.ticket as served on 9 Oct 2026.
const live = { scored: 1805, missed: 58, rate: 0.032, distinct_events: 656, n_nights: 22 };
assert.equal(recordCountsText(live, "en"), "1,805 forecasts scored · 656 distinct events · 22 nights");
assert.equal(recordCountsText(live, "zh"), "已评分 1,805 个预测 · 656 个独立事件 · 22 个夜晚");
// An older server or a saved snapshot without the extra fields: say only what was sent.
assert.equal(recordCountsText({ scored: 1699 }, "en"), "1,699 forecasts scored");
assert.equal(recordCountsText({ scored: 3, distinct_events: 2, n_nights: 1 }, "en"), "3 forecasts scored · 2 distinct events · 1 night");
console.log("record.test ok");
