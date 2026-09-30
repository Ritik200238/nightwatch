// Prebuild: save the live API's answers so the site can still show something if the
// box is down. Never fails the build: on any problem it keeps going and writes what it has.
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "snapshot", "generated.json");
const ORIGIN = (process.env.NIGHTWATCH_API_ORIGIN ?? "").replace(/\/$/, "");

// Keys must match snapshotKey(): sorted query params.
const GETS = ["/health", "/universe?core=true", "/sources", "/calibration", "/studies", "/misses", "/verify", "/anchors", "/lessons", "/forecasts?limit=100", "/lenses"];
const DEMOS = [
  { ticker: "TSLA", side: "long", notional_quote: 20000, account_equity_quote: 200000, horizon_kind: "next_open", thesis: "Delivery numbers beat and the trend is up.", invalidation: "Closes below the recent swing low.", record: false },
  { ticker: "NVDA", side: "long", notional_quote: 20000, leverage: 5, horizon_kind: "next_open", thesis: "Momentum into earnings.", invalidation: "Loses the 20-day average.", record: false },
  { ticker: "AAPL", side: "short", notional_quote: 10000, horizon_kind: "next_open", thesis: "Stretched after a run.", invalidation: "Breaks to a new high.", record: false },
];

async function call(path, init, ms) {
  const res = await fetch(ORIGIN + path, { ...init, headers: { "content-type": "application/json" }, signal: AbortSignal.timeout(ms) });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

async function main() {
  if (!ORIGIN) return console.log("[snapshot] NIGHTWATCH_API_ORIGIN unset; skipping");
  const out = { generated_at: new Date().toISOString(), gets: {}, reports: {} };
  await Promise.all([
    ...GETS.map(async (p) => {
      try {
        out.gets[p] = await call(p, {}, 30000);
      } catch (e) {
        console.log(`[snapshot] skip ${p}: ${e.message}`);
      }
    }),
    ...DEMOS.map(async (d) => {
      try {
        out.reports[d.ticker] = await call("/analyze", { method: "POST", body: JSON.stringify(d) }, 120000);
      } catch (e) {
        console.log(`[snapshot] skip ${d.ticker}: ${e.message}`);
      }
    }),
  ]);
  if (!Object.keys(out.gets).length && !Object.keys(out.reports).length && existsSync(OUT)) return console.log("[snapshot] nothing fetched; keeping previous file");
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(out));
  console.log(`[snapshot] saved ${Object.keys(out.gets).length} pages, ${Object.keys(out.reports).length} reports`);
}

main().catch((e) => console.log("[snapshot] failed, continuing:", e.message));
