// A stand-in for the Nightwatch API, for the browser tests of the saved-copy notices (banner.mjs).
// It answers from fixtures the live API gave, and a test can make it fail on purpose:
//   POST /__mode {"chat": "live" | "down", "failGets": ["/misses", ...]}
// "down" answers the chat with 503, so the web proxy falls back to its saved copy; a path in
// failGets answers 503, so that one read falls back to the saved copy while the rest stay live.
// Usage: node e2e/fake-backend.mjs [port]
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const PAGES = JSON.parse(readFileSync(join(here, "fixtures", "pages.json"), "utf8")).gets;
const REPORT = JSON.parse(readFileSync(join(here, "fixtures", "report.json"), "utf8"));
const PORT = Number(process.argv[2] || 8765);
export const LIVE_REPLY = "Live answer from the test backend.";
const LIVE_ID = 424242;

let mode = { chat: "live", failGets: [] };

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "content-type": type, "cache-control": "no-store" });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

function liveAnswer() {
  const report = { ...REPORT, forecast_id: LIVE_ID };
  return { intent: { kind: "analyze" }, ticket: report.ticket, report, reply: LIVE_REPLY, parsed_by: "rules", provider: "rules", model: null, unverified_numbers: [], language: "en" };
}

function body(req) {
  return new Promise((resolve) => {
    let s = "";
    req.on("data", (c) => (s += c));
    req.on("end", () => resolve(s));
  });
}

createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  // The browser's anonymous id and language ride on every call; the pages are keyed without them.
  for (const k of [...url.searchParams.keys()]) if (k.startsWith("nw_")) url.searchParams.delete(k);
  url.searchParams.sort();
  const key = url.pathname + (url.searchParams.size ? `?${url.searchParams}` : "");
  if (req.method === "POST" && url.pathname === "/__mode") {
    mode = { ...mode, ...JSON.parse((await body(req)) || "{}") };
    return send(res, 200, mode);
  }
  if (req.method === "GET") {
    if (mode.failGets.includes(url.pathname)) return send(res, 503, { detail: "down on purpose" });
    if (key in PAGES) return send(res, 200, PAGES[key]);
    if (url.pathname === `/reports/${LIVE_ID}`) return send(res, 200, { ...REPORT, forecast_id: LIVE_ID });
    return send(res, 404, { detail: `not in the fixtures: ${key}` });
  }
  if (req.method === "POST" && url.pathname === "/analyze") {
    await body(req);
    return send(res, 200, REPORT); // the build's demo analyses, which are not recorded
  }
  if (req.method === "POST" && (url.pathname === "/chat/stream" || url.pathname === "/chat")) {
    await body(req);
    if (mode.chat === "down") return send(res, 503, { detail: "down on purpose" });
    if (url.pathname === "/chat") return send(res, 200, liveAnswer());
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    res.write(": open\n\n");
    res.write(`event: step\ndata: ${JSON.stringify({ stage: "snapshot", en: "Read the market", zh: "读取行情", ms: 120 })}\n\n`);
    setTimeout(() => {
      res.write(`event: done\ndata: ${JSON.stringify(liveAnswer())}\n\n`);
      res.end();
    }, 300);
    return;
  }
  return send(res, 404, { detail: "not in the fixtures" });
}).listen(PORT, "127.0.0.1", () => console.log(`fake backend on ${PORT}`));
