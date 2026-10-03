// Real-browser smoke test against the live site. The uptime check only curls endpoints, so a
// client-side crash (a TypeError while rendering a report) went unnoticed for two days.
// Usage: node web/e2e/smoke.mjs [baseUrl]   (needs `playwright` + chromium installed)
import { chromium } from "playwright";

const BASE = (process.argv[2] || process.env.SMOKE_URL || "https://nightwatch-gules.vercel.app").replace(/\/$/, "");
const REPORT_TIMEOUT = 90_000;
const STARTERS = [
  "Hold $20k of TSLA through the weekend, stop at 350",
  "Short 5k NVDA for the next 12 hours",
  "Long 10k SPY until Monday open, thesis: strong Friday close",
];
// The hero's demo buttons (short labels in web/src/components/desk/desk-page.tsx HERO_CHIPS).
const SCENARIOS = ["NVDA weekend 15k", "5x TSLA overnight", "周末做多特斯拉"];
// Left-rail demo buttons appear once the hero has been used (scenarios.tsx short labels).
const RAIL_AFTER_REPORT = "Safest way to hold META";
const FREE_TEXT = "I'm bullish on NVDA into the weekend, 15k, stop 215";
const PAGES = ["/calibration", "/studies", "/wrong", "/status", "/usage"];
const REPORT_RE = /What history says|历史怎么说/;

const browser = await chromium.launch();
const results = [];

async function freshPage() {
  const ctx = await browser.newContext({ extraHTTPHeaders: { "x-nw-internal": "1" } });
  // The app's own marker for operator traffic, so smoke runs are not counted as usage.
  await ctx.addInitScript(() => { try { localStorage.setItem("nightwatch.internal", "1"); } catch {} });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30_000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text().slice(0, 200)}`); });
  return { ctx, page, errors };
}

async function guard(page, errors) {
  if (errors.some((e) => e.startsWith("pageerror"))) throw new Error(errors.find((e) => e.startsWith("pageerror")));
  if (await page.getByText("This page couldn", { exact: false }).count()) throw new Error("error boundary: 'This page couldn...' shown");
}

async function waitReport(page, errors) {
  const deadline = Date.now() + REPORT_TIMEOUT;
  while (Date.now() < deadline) {
    await guard(page, errors);
    if (await page.getByText(REPORT_RE).first().isVisible().catch(() => false)) break;
    await page.waitForTimeout(1000);
  }
  if (!(await page.getByText(REPORT_RE).first().isVisible().catch(() => false))) throw new Error(`no report within ${REPORT_TIMEOUT / 1000}s`);
  await page.getByText(/Running the desk|正在计算/).first().waitFor({ state: "hidden", timeout: 30_000 });
  await page.waitForTimeout(1500); // let any post-render effect throw
  await guard(page, errors);
}

async function openHome(page, errors) {
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.getByRole("tab", { name: /^(Chat|聊天)$/ }).waitFor();
  await guard(page, errors);
}

async function flow(name, fn) {
  const t0 = Date.now();
  let last = "";
  for (let attempt = 1; attempt <= 2; attempt++) {
    const { ctx, page, errors } = await freshPage();
    try {
      await fn(page, errors);
      results.push({ name, ok: true, secs: Math.round((Date.now() - t0) / 1000), attempt });
      await ctx.close();
      return;
    } catch (e) {
      last = String(e.message || e).split("\n")[0];
      await ctx.close().catch(() => {});
    }
  }
  results.push({ name, ok: false, secs: Math.round((Date.now() - t0) / 1000), err: last });
}

await flow("home + example card", async (page, errors) => {
  await openHome(page, errors);
  await page.getByText(/Example from|示例，生成于/).first().waitFor({ timeout: 45_000 });
  await guard(page, errors);
});

for (const s of STARTERS) {
  await flow(`starter: ${s.slice(0, 28)}`, async (page, errors) => {
    await openHome(page, errors);
    await page.getByRole("tab", { name: /^(Chat|聊天)$/ }).click();
    await page.getByRole("button", { name: s, exact: true }).click();
    await waitReport(page, errors);
  });
}

for (const s of SCENARIOS) {
  await flow(`scenario: ${s.slice(0, 28)}`, async (page, errors) => {
    await openHome(page, errors);
    await page.getByRole("button", { name: s }).first().click();
    await waitReport(page, errors);
  });
}

await flow(`rail after a report: ${RAIL_AFTER_REPORT}`, async (page, errors) => {
  await openHome(page, errors);
  await page.getByRole("button", { name: SCENARIOS[0] }).first().click();
  await waitReport(page, errors);
  await page.getByRole("button", { name: RAIL_AFTER_REPORT }).first().click();
  await waitReport(page, errors);
});

await flow("free-text chat", async (page, errors) => {
  await openHome(page, errors);
  await page.getByRole("tab", { name: /^(Chat|聊天)$/ }).click();
  await page.locator("#chat-input").fill(FREE_TEXT);
  await page.locator("#chat-input").press("Enter");
  await waitReport(page, errors);
});

for (const p of PAGES) {
  await flow(`page ${p}`, async (page, errors) => {
    const r = await page.goto(BASE + p, { waitUntil: "domcontentloaded", timeout: 60_000 });
    if (!r || r.status() >= 400) throw new Error(`HTTP ${r && r.status()}`);
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    await page.waitForTimeout(1500);
    await guard(page, errors);
  });
}

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`smoke ${BASE}: ${results.length - failed.length}/${results.length} flows passed`);
for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}  ${r.secs}s${r.attempt === 2 ? " (retried)" : ""}${r.err ? "  -> " + r.err : ""}`);
process.exit(failed.length ? 1 : 0);
