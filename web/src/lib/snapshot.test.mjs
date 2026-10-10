// Run: node --experimental-strip-types src/lib/snapshot.test.mjs   (Node >= 22.6)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { classifyHealth, snapshotKey, shouldFallback, snapshotPost, snapshotGet, readableTimes, snapshotNoticeFor, isSnapshotAnswer, snapshotFlag, markSavedCopy, savedCopyAt } from "./snapshot.ts";

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
// A saved answer is recognised by its own intent, and its time is readable.
assert.ok(isSnapshotAnswer({ intent: { kind: "snapshot" } }));
assert.ok(!isSnapshotAnswer({ intent: { kind: "analyze" } }) && !isSnapshotAnswer({}) && !isSnapshotAnswer({ intent: null }));
// What the proxy really builds for a saved chat answer is recognised, so the fix cannot miss one.
assert.ok(isSnapshotAnswer(c));
// Regression: a live streamed answer must be kept even when the shared flag was set by an
// unrelated read that fell back to a saved copy while the analysis ran. The decision takes only
// the answer, so no flag value can turn a live answer into a "saved example".
snapshotFlag.set("2026-10-10T03:46:00Z");
const live = { intent: { kind: "analyze", ticker: "NVDA" }, report: { ticket: { ticker: "NVDA" }, forecast_id: 21509 }, reply: "GO on long 15,000 USDT of NVDA" };
assert.equal(isSnapshotAnswer(live), false);
assert.equal(isSnapshotAnswer(snapshotPost(data, "chat", '{"messages":[{"role":"user","content":"x"}]}')), true);
snapshotFlag.set(null);
// The chat component must not feed the shared flag into that decision again, and a live answer
// must clear a flag an earlier saved read left behind.
const chat = readFileSync(new URL("../components/desk/chat.tsx", import.meta.url), "utf8");
assert.ok(chat.includes("isSnapshotAnswer(res)"), "chat.tsx decides from the answer alone");
assert.ok(!/isSnapshotAnswer\([^)]*snapshotFlag/.test(chat), "chat.tsx must not pass the shared flag");
assert.ok(chat.indexOf("snapshotFlag.set(null)") > chat.indexOf("if (isSnapshotAnswer(res))"), "a live answer clears the flag after the saved-answer branch");
// Per answer: a page that holds one answer asks that answer whether it is a saved copy, never the
// shared flag, which only says that some read fell back most recently.
const savedBody = snapshotPost(data, "analyze", '{"ticker":"NVDA"}');
assert.equal(savedCopyAt(savedBody), null, "nothing is a saved copy until a response says so");
assert.equal(markSavedCopy(savedBody, "T0"), savedBody, "marking hands the body back unchanged");
assert.equal(savedCopyAt(savedBody), "T0");
const liveReport = { ticket: { ticker: "TSLA" }, forecast_id: 21509 };
snapshotFlag.set("2026-10-10T03:46:00Z"); // an unrelated read fell back to its saved copy
assert.equal(savedCopyAt(liveReport), null, "a live answer is not made a saved copy by the shared flag");
assert.equal(markSavedCopy(liveReport, null), liveReport);
assert.equal(savedCopyAt(liveReport), null);
assert.equal(savedCopyAt(savedBody), "T0", "a genuine saved copy keeps its own time, whatever the flag says");
snapshotFlag.set(null);
assert.equal(savedCopyAt(savedBody), "T0", "and keeps it once the flag is cleared");
// Bodies that are not objects cannot be marked, and must not throw.
assert.equal(markSavedCopy("text", "T0"), "text");
assert.equal(savedCopyAt("text"), null);
assert.equal(savedCopyAt(null), null);
assert.equal(savedCopyAt(undefined), null);
// The pages that decide "is this a saved copy" ask the answer, and the request layer marks it.
const src = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");
const apiSrc = src("./api.ts");
assert.ok(apiSrc.includes("markSavedCopy(data, res.headers.get(SNAPSHOT_HEADER))"), "request() marks each saved answer");
const stored = src("../app/r/[id]/stored-report.tsx");
assert.ok(!stored.includes("snapshotFlag") && stored.includes("savedCopyAt(r)"), "a stored report asks its own answer, not the shared flag");
const desk = src("../components/desk/desk-page.tsx");
assert.ok(!desk.includes("snapshotFlag") && desk.includes("savedCopyAt(got)"), "the form path asks its own answer, not the shared flag");
assert.ok(chat.indexOf("isoIn(res.reply) ||") > 0 && chat.indexOf("isoIn(res.reply) ||") < chat.indexOf("snapshotFlag.get() ??"), "a saved chat answer is dated from its own text first");
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
