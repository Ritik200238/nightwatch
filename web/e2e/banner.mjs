// Real-browser test of the saved-copy notices, against the built site and e2e/fake-backend.mjs.
// The unit tests (src/lib/snapshot.test.mjs) pin the decision; this pins what a person sees.
//   A. The API is down: the chat shows the saved example as a saved example, with the notice,
//      and the site banner says the live server is unreachable.
//   B. The API answers the chat live while an unrelated read fell back to the saved copy: the
//      live report is shown and kept, and no "saved example" notice is attached to it.
//   C. A stored report that loads live is not labelled a saved copy because another read fell back.
// Usage: node e2e/banner.mjs <site url> <fake backend url>   (needs `playwright` + chromium)
import { chromium } from "playwright";

const SITE = (process.argv[2] || "http://127.0.0.1:3100").replace(/\/$/, "");
const FAKE = (process.argv[3] || "http://127.0.0.1:8765").replace(/\/$/, "");
const TRADE = "Hold $20k of TSLA through the weekend, stop at 350";
const LIVE_REPLY = "Live answer from the test backend.";
const SAVED_CHAT = /The live server is unreachable right now; the example is a saved one from/;
const SITE_BANNER = /Live server unreachable — showing a saved snapshot from/;
const REPORT_RE = /What history says/;
const EXAMPLE_RE = /Example from/;
const STORED_SAVED = /The live server is not answering, so this is the saved copy from/;

async function setMode(mode) {
  const r = await fetch(`${FAKE}/__mode`, { method: "POST", body: JSON.stringify(mode) });
  if (!r.ok) throw new Error(`could not set the fake backend's mode: ${r.status}`);
}

const browser = await chromium.launch();
const version = browser.version();
const results = [];

async function scenario(name, mode, fn) {
  await setMode({ chat: "live", failGets: [], ...mode });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.setDefaultTimeout(60_000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const t0 = Date.now();
  try {
    await fn(page);
    if (errors.length) throw new Error(`page error: ${errors[0]}`);
    results.push({ name, ok: true, secs: Math.round((Date.now() - t0) / 1000) });
  } catch (e) {
    await page.screenshot({ path: `banner-${results.length + 1}.png`, fullPage: true }).catch(() => {});
    results.push({ name, ok: false, err: String(e.message || e).split("\n")[0] });
  } finally {
    await ctx.close();
  }
}

async function openHome(page) {
  await page.goto(SITE + "/", { waitUntil: "domcontentloaded" });
  await page.locator("#hero-input").waitFor();
  await page.getByText(/\d+ tokens/).first().waitFor({ timeout: 45_000 }); // the page's scripts are live
}

async function ask(page) {
  await page.locator("#hero-input").fill(TRADE);
  await page.locator("#hero-input").press("Enter");
}

await scenario("A. API down: the saved example is labelled, the banner shows", { chat: "down" }, async (page) => {
  await openHome(page);
  await ask(page);
  await page.getByText(SAVED_CHAT).first().waitFor();
  await page.getByText(SITE_BANNER).first().waitFor();
  if (await page.getByText(LIVE_REPLY).count()) throw new Error("a live answer appeared although the API was down");
});

await scenario("B. live answer while another read fell back: kept, not labelled saved", { failGets: ["/misses", "/verify"] }, async (page) => {
  await openHome(page);
  await page.getByText(SITE_BANNER).first().waitFor(); // the unrelated fallback really happened first
  await ask(page);
  await page.getByText(LIVE_REPLY).first().waitFor();
  await page.getByText(REPORT_RE).first().waitFor();
  if (await page.getByText(EXAMPLE_RE).first().isVisible().catch(() => false)) throw new Error("the stored example is still shown instead of the live report");
  await page.waitForTimeout(2_000); // let anything that would discard it run
  if (!(await page.getByText(LIVE_REPLY).first().isVisible())) throw new Error("the live answer was discarded");
  if (await page.getByText(SAVED_CHAT).count()) throw new Error("the live answer was labelled a saved example");
});

await scenario("C. stored report loaded live while another read fell back: not labelled saved", { failGets: ["/misses", "/verify"] }, async (page) => {
  await page.goto(SITE + "/r/424242", { waitUntil: "domcontentloaded" });
  await page.getByText(REPORT_RE).first().waitFor();
  await page.waitForTimeout(3_000); // the record chip's reads fall back meanwhile
  if (await page.getByText(STORED_SAVED).count()) throw new Error("a live stored report was labelled a saved copy");
});

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`banner ${SITE}: ${results.length - failed.length}/${results.length} scenarios passed (chromium ${version})`);
for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.ok ? `  ${r.secs}s` : `  -> ${r.err}`}`);
process.exit(failed.length ? 1 : 0);
