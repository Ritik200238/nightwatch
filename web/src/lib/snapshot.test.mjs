// Run: node --experimental-strip-types src/lib/snapshot.test.mjs   (Node >= 22.6)
import assert from "node:assert/strict";
import { classifyHealth, snapshotKey, shouldFallback, snapshotPost, snapshotGet, readableTimes, snapshotNoticeFor, isSnapshotAnswer } from "./snapshot.ts";

const data = { generated_at: "T0", gets: { "/universe?core=true": [1], "/a?x=1&y=2": "ok" }, reports: { TSLA: { t: "TSLA" }, NVDA: { t: "NVDA" } } };
assert.equal(snapshotKey("a", "?y=2&x=1"), "/a?x=1&y=2");
assert.equal(snapshotGet(data, "a", "?y=2&x=1"), "ok");
assert.equal(snapshotGet(data, "nope", ""), null);
assert.ok(shouldFallback(null) && shouldFallback(502) && shouldFallback(503) && shouldFallback(504) && !shouldFallback(422) && !shouldFallback(200));
// A real server error is shown as an error, never swapped for a saved example of another trade.
assert.ok(!shouldFallback(500) && !shouldFallback(501) && !shouldFallback(500 + 7));
assert.equal(snapshotPost(data, "analyze", '{"ticker":"NVDA"}').t, "NVDA");
assert.equal(snapshotPost(data, "analyze", '{"ticker":"ZZZ"}').t, "TSLA");
const c = snapshotPost(data, "chat", '{"messages":[{"role":"user","content":"long nvda 5000"}]}');
assert.equal(c.report.t, "NVDA");
assert.ok(c.reply.startsWith("The live server is unreachable right now; this is a saved example from T0"));
assert.equal(snapshotPost(null, "chat", "{}"), null);
// A browser always adds its anonymous id and language; the saved page must still match.
assert.equal(snapshotKey("/calibration", "?nw_client=abc&nw_lang=zh&nw_internal=1"), snapshotKey("calibration"));
assert.equal(snapshotKey("universe", "?nw_client=x&core=true"), "/universe?core=true");
// A snapshot answer is recognised by its intent or by the proxy header, and its time is readable.
assert.ok(isSnapshotAnswer({ intent: { kind: "snapshot" } }, null) && isSnapshotAnswer({}, "2026-09-12T10:00:00Z"));
assert.ok(!isSnapshotAnswer({ intent: { kind: "analyze" } }, null));
assert.ok(!readableTimes("saved from 2026-09-12T10:00:00+00:00, ok", "en-US").includes("T10:00"));
assert.ok(readableTimes("from 2026-09-12T10:00:00Z.", "zh-CN").includes("2026"));
assert.ok(snapshotNoticeFor("2026-09-12T10:00:00Z", "zh").startsWith("实时服务器"));
assert.equal(readableTimes("no date here"), "no date here");
// A saved /health is down, never up, and says when the copy is from.
assert.deepEqual(classifyHealth(true, "2026-10-05T18:18:28Z", 200), { state: "down", savedAt: "2026-10-05T18:18:28Z" });
assert.deepEqual(classifyHealth(false, null, 200), { state: "down" });
assert.deepEqual(classifyHealth(true, null, 500), { state: "up" });
assert.deepEqual(classifyHealth(true, null, 4000), { state: "slow" });
console.log("snapshot tests ok");
