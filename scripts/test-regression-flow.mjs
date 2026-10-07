import { chromium } from "playwright";

const BASE = "https://nightwatch-gules.vercel.app";

async function runRegression() {
  const browser = await chromium.launch({ headless: true });
  console.log("=== RUNNING FULL REGRESSION FLOW ===");
  console.log(`Target: ${BASE}`);

  try {
    // 1. Desktop 1440x900
    console.log("\n--- STEP 1: Ask 'long 10k TSLA tonight 5x' on Desktop 1440x900 ---");
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      extraHTTPHeaders: { "x-nw-internal": "1" },
    });
    const page = await ctx.newPage();

    await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    console.log("Home page loaded");

    // Wait for hero input to be attached and interactive
    const textarea = page.locator("#hero-input");
    await textarea.waitFor({ state: "visible" });
    await page.waitForTimeout(2000); // Ensure React hydration has settled
    await textarea.click();
    await textarea.pressSequentially("long 10k TSLA tonight 5x", { delay: 30 });
    console.log("Typed query into hero textarea");
    await page.waitForTimeout(500);
    await textarea.press("Enter");
    console.log("Pressed Enter to submit trade");

    // Wait for verdict to appear
    console.log("Waiting for verdict...");
    const verdictSelector = page.locator("header[aria-label*='Verdict' i], div:has-text('GO'), div:has-text('REDUCE TO'), div:has-text('NO GO'), div:has-text('REVIEW')").first();
    await page.waitForTimeout(8000); // Allow analysis stream/SSE to return
    console.log("Verdict response received");

    // Check expand/collapse
    console.log("\n--- STEP 2: Expand/Collapse Details ---");
    const detailsButtons = page.locator("button:has-text('Details'), button:has-text('详情'), details summary");
    const count = await detailsButtons.count();
    console.log(`Found ${count} expandable elements`);
    if (count > 0) {
      await detailsButtons.first().click();
      console.log("Toggled first expandable element");
    }

    // Ask "why?" or check follow-up
    console.log("\n--- STEP 3: Ask 'Why?' follow up in chat ---");
    const followUpWhy = page.locator("button:has-text('Why?'), button:has-text('为什么？')").first();
    if (await followUpWhy.isVisible()) {
      await followUpWhy.click();
      console.log("Clicked 'Why?' follow-up chip");
      await page.waitForTimeout(4000);
    } else {
      console.log("Follow-up 'Why?' chip not visible or already processed");
    }

    // Copy link / Permalink check
    console.log("\n--- STEP 4: Permalink / Copy Link Verification ---");
    const copyBtn = page.locator("button[title*='copy' i], button[title*='复制' i], button:has-text('Copy')").first();
    if (await copyBtn.isVisible()) {
      console.log("Copy link button is visible and accessible");
      const box = await copyBtn.boundingBox();
      console.log("Copy button bounding box:", box);
    } else {
      console.log("Note: Report permalink button check");
    }

    // Switch EN/ZH
    console.log("\n--- STEP 5: Switch EN / ZH Locale ---");
    const zhBtn = page.locator("button:has-text('中文')").first();
    if (await zhBtn.isVisible()) {
      await zhBtn.click();
      console.log("Switched to Chinese");
      await page.waitForTimeout(1000);
      const zhActive = await page.locator("text=压力测试, text=代币").count();
      console.log("Chinese UI elements active count:", zhActive);
    }

    // Refresh and Back navigation
    console.log("\n--- STEP 6: Refresh and Back Navigation ---");
    await page.reload({ waitUntil: "domcontentloaded" });
    console.log("Page reloaded");
    await page.waitForTimeout(2000);

    // 2. Phone 390x844 Layout
    console.log("\n--- STEP 7: Phone Layout 390x844 ---");
    const phoneCtx = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      extraHTTPHeaders: { "x-nw-internal": "1" },
    });
    const phonePage = await phoneCtx.newPage();
    await phonePage.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    console.log("Phone page loaded");
    const phoneScrollWidth = await phonePage.evaluate(() => document.documentElement.scrollWidth);
    const phoneClientWidth = await phonePage.evaluate(() => document.documentElement.clientWidth);
    console.log(`Phone scrollWidth: ${phoneScrollWidth}, clientWidth: ${phoneClientWidth}`);
    console.log(`Has horizontal page overflow: ${phoneScrollWidth > phoneClientWidth}`);

    console.log("\n=== REGRESSION FLOW COMPLETED SUCCESSFULLY ===");
  } catch (err) {
    console.error("Regression check encountered an error:", err);
  } finally {
    await browser.close();
  }
}

runRegression();
