import { chromium } from "playwright";

const BASE = "https://nightwatch-gules.vercel.app";

async function run() {
  const browser = await chromium.launch({ headless: true });
  console.log("=== VERIFYING ROUND 5 ON LIVE VERCEL DEPLOYMENT ===");
  console.log(`Target: ${BASE}`);

  // Test 1: Desktop 1440x900 - English and Chinese
  console.log("\n--- TEST 1: Desktop 1440x900 ---");
  const desktopCtx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    extraHTTPHeaders: { "x-nw-internal": "1" },
  });
  const page = await desktopCtx.newPage();

  // Load home page
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  console.log("Desktop Home loaded successfully");

  // Check example report visibility
  const exampleHeader = page.locator("text=/Example from|示例，生成于/").first();
  await exampleHeader.waitFor({ timeout: 15000 });
  console.log("Example report is visible");

  // Check StressBars on desktop
  const stressBars = page.locator("figure[aria-label*='stress test' i], figure[aria-label*='压力测试' i]");
  if (await stressBars.count() > 0) {
    const labels = await stressBars.locator("li span.min-w-0").allInnerTexts();
    console.log("Desktop StressBar labels count:", labels.length);
    console.log("Labels:", labels.slice(0, 4));
    // Verify unique and non-empty
    const unique = new Set(labels);
    console.log("Labels unique count:", unique.size);
    // Check bounding boxes for readability
    const firstLabelBox = await stressBars.locator("li span.min-w-0").first().boundingBox();
    console.log("First label bounding box:", firstLabelBox);
  } else {
    console.log("Note: StressBars figure not found on initial example report");
  }

  // Check SourceLegend: remains one line
  const sourceLegend = page.locator("details summary:has-text('Sources:'), details summary:has-text('来源：')");
  if (await sourceLegend.count() > 0) {
    const box = await sourceLegend.first().boundingBox();
    console.log("SourceLegend summary bounding box:", box);
    console.log("SourceLegend height:", box?.height, "(< 48px indicates 1 line)");
  } else {
    console.log("SourceLegend summary not found");
  }

  // Check "What the verdicts mean" gap
  const verdictsDetails = page.locator("details:has(summary:has-text('What the verdicts mean')), details:has(summary:has-text('各个结论是什么意思'))");
  if (await verdictsDetails.count() > 0) {
    const box = await verdictsDetails.first().boundingBox();
    console.log("'What the verdicts mean' details box:", box);
  }

  // Switch to Chinese and check report header
  console.log("\nSwitching to Chinese...");
  const zhButton = page.locator("button:has-text('中文')").first();
  if (await zhButton.count() > 0) {
    await zhButton.click();
    await page.waitForTimeout(1000);
    // Check for 市场状态：
    const zhSubhead = await page.locator("text=/市场状态：/").first().innerText().catch(() => "not found");
    console.log("Chinese subhead text:", zhSubhead);
  }

  // Check /wrong page for stray space before comma
  console.log("\n--- TEST 2: /wrong Page Checks ---");
  await page.goto(BASE + "/wrong", { waitUntil: "domcontentloaded", timeout: 60000 });
  const wrongText = await page.locator("main").innerText();
  // Check if "breach ," or "突破 ，" exists
  const hasStraySpaceEN = wrongText.includes("breach ,");
  const hasStraySpaceZH = wrongText.includes("突破 ，");
  console.log("Has stray space EN ('breach ,'):", hasStraySpaceEN);
  console.log("Has stray space ZH ('突破 ，'):", hasStraySpaceZH);

  // Check colored verdict pills on /wrong
  const verdictPills = page.locator("table tr td span[class*='text-status'], table tr td span[class*='text-primary']");
  console.log("Colored verdict pills found on /wrong:", await verdictPills.count());

  await desktopCtx.close();

  // Test 3: Phone at 390x844 with Touch Emulation
  console.log("\n--- TEST 3: Phone 390x844 Touch Emulation ---");
  const phoneCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    extraHTTPHeaders: { "x-nw-internal": "1" },
  });
  const phonePage = await phoneCtx.newPage();
  await phonePage.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  console.log("Phone Home loaded");

  // Check SourceChips tap target size
  const sourceChips = phonePage.locator("button[class*='group/chip']");
  const chipCount = await sourceChips.count();
  console.log(`Found ${chipCount} source chips`);
  if (chipCount > 0) {
    const chipBox = await sourceChips.first().boundingBox();
    console.log("First SourceChip touch button bounding box:", chipBox);
    console.log(`Height >= 40px: ${chipBox && chipBox.height >= 40}, Width >= 40px: ${chipBox && chipBox.width >= 40}`);
  }

  // Check Copy Link button
  const copyLink = phonePage.locator("button:has-text('Copy link'), button:has-text('复制链接')");
  if (await copyLink.count() > 0) {
    const copyBox = await copyLink.first().boundingBox();
    console.log("Copy link button bounding box:", copyBox);
    console.log(`Height >= 40px: ${copyBox && copyBox.height >= 40}`);
  }

  // Check Ticket/Chat tabs tap targets
  const ticketTab = phonePage.locator("button[role='tab']:has-text('Ticket'), button[role='tab']:has-text('工单')");
  if (await ticketTab.count() > 0) {
    const tabBox = await ticketTab.first().boundingBox();
    console.log("Ticket tab bounding box:", tabBox);
    console.log(`Height >= 40px: ${tabBox && tabBox.height >= 40}`);
  }

  // Check /journal "All" button tap target
  console.log("\n--- Checking /journal tap targets ---");
  await phonePage.goto(BASE + "/journal", { waitUntil: "domcontentloaded", timeout: 60000 });
  const allButton = phonePage.locator("button:has-text('All'), button:has-text('全部')").first();
  if (await allButton.count() > 0) {
    const allBox = await allButton.first().boundingBox();
    console.log("'All' button on /journal bounding box:", allBox);
    console.log(`Height >= 40px: ${allBox && allBox.height >= 40}`);
  }

  // Check /sources "FRED" button tap target
  console.log("\n--- Checking /sources tap targets ---");
  await phonePage.goto(BASE + "/sources", { waitUntil: "domcontentloaded", timeout: 60000 });
  const fredButton = phonePage.locator("button:has-text('FRED')").first();
  if (await fredButton.count() > 0) {
    const fredBox = await fredButton.first().boundingBox();
    console.log("'FRED' button on /sources bounding box:", fredBox);
    console.log(`Height >= 40px: ${fredBox && fredBox.height >= 40}`);
  }

  // Check ZH 详情 and 研究 links
  console.log("\n--- Checking ZH 详情 and 研究 links ---");
  const zhLangBtn = phonePage.locator("button:has-text('中文')").first();
  if (await zhLangBtn.count() > 0) {
    await zhLangBtn.click();
    await phonePage.waitForTimeout(500);
  }
  // On /wrong in ZH
  await phonePage.goto(BASE + "/wrong", { waitUntil: "domcontentloaded", timeout: 60000 });
  const yanJiuLink = phonePage.locator("a:has-text('研究')").first();
  if (await yanJiuLink.count() > 0) {
    const yjBox = await yanJiuLink.boundingBox();
    console.log("'研究' link bounding box:", yjBox);
  }
  await phoneCtx.close();

  // Test 4: Check /tonight two disabled buttons
  console.log("\n--- TEST 4: /tonight Add Buttons Check ---");
  const tonightPage = await browser.newPage();
  await tonightPage.goto(BASE + "/tonight", { waitUntil: "domcontentloaded", timeout: 60000 });
  const addButtons = tonightPage.locator("button:has-text('Add position'), button:has-text('添加仓位')");
  const addCount = await addButtons.count();
  console.log(`Found ${addCount} 'Add position' buttons on /tonight`);
  for (let i = 0; i < addCount; i++) {
    const btn = addButtons.nth(i);
    const disabled = await btn.isDisabled();
    const cls = await btn.getAttribute("class");
    console.log(`Button ${i}: disabled=${disabled}, class contains 'bg-primary': ${cls?.includes('bg-primary')}`);
  }
  await tonightPage.close();

  await browser.close();
  console.log("\n=== VERIFICATION RUN COMPLETE ===");
}

run().catch((err) => {
  console.error("Verification failed:", err);
  process.exit(1);
});
