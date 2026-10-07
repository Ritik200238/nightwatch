import { chromium } from "playwright";

const BASE_URL = process.env.BASE_URL || "https://nightwatch-gules.vercel.app";

async function main() {
  console.log("=== VERIFYING TASK 3 PRESENTATION POLISH ON PRODUCTION ===");
  console.log(`Target: ${BASE_URL}`);

  const browser = await chromium.launch({ headless: true });
  const results = {};

  try {
    // 1. Check SourceLegend on Desktop (1440x900)
    console.log("\n--- PART 1: SourceLegend single-line layout ---");
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(BASE_URL, { waitUntil: "networkidle" });
    
    // Look for details summary in SourceLegend
    const legendSummary = page.locator("details summary:has-text('Sources:'), details summary:has-text('来源：')").first();
    const hasLegend = await legendSummary.count() > 0;
    console.log(`SourceLegend found: ${hasLegend}`);
    
    if (hasLegend) {
      const box = await legendSummary.boundingBox();
      console.log(`SourceLegend bounding box at 1440px: height = ${box.height}px, width = ${box.width}px`);
      // A single line should have height <= 44px
      const isSingleLine = box.height <= 44;
      results.sourceLegendDesktop = { isSingleLine, height: box.height };
    }
    await page.close();

    // 2. Check /calibration layout on Desktop (1440x900) & Mobile (390x844)
    console.log("\n--- PART 2: /calibration Stats & Progressive Disclosure ---");
    const calibDesktop = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await calibDesktop.goto(`${BASE_URL}/calibration`, { waitUntil: "networkidle" });
    
    // Check desktop has resampling paragraph visible
    const deskResample = calibDesktop.locator("p.hidden.sm\\:block:has-text('Treating every forecast as independent')").first();
    const deskResampleVis = await deskResample.isVisible();
    console.log(`Desktop resampling text visible: ${deskResampleVis}`);
    results.calibrationDesktop = { resampleVisible: deskResampleVis };
    await calibDesktop.close();

    // Mobile check
    const calibMobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await calibMobile.goto(`${BASE_URL}/calibration`, { waitUntil: "networkidle" });
    const mobileDetails = calibMobile.locator("details.group.sm\\:hidden").first();
    const mobileDetailsCount = await mobileDetails.count();
    const mobileSummaryText = await mobileDetails.locator("summary").textContent();
    console.log(`Mobile progressive disclosure found: ${mobileDetailsCount > 0}, summary: "${mobileSummaryText?.trim()}"`);
    results.calibrationMobile = { hasProgressiveDisclosure: mobileDetailsCount > 0, summary: mobileSummaryText?.trim() };
    await calibMobile.close();

    // 3. Check /status 2-column layout on Desktop
    console.log("\n--- PART 3: /status 2-column layout on Desktop ---");
    const statusPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await statusPage.goto(`${BASE_URL}/status`, { waitUntil: "networkidle" });
    const statusGrids = statusPage.locator("div.grid.md\\:grid-cols-2");
    const statusGridCount = await statusGrids.count();
    console.log(`Status page 2-column grids found: ${statusGridCount}`);
    results.status2ColGrids = statusGridCount;
    await statusPage.close();

    // 4. Check /sources 2-column layout on Desktop
    console.log("\n--- PART 4: /sources 2-column layout on Desktop ---");
    const sourcesPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await sourcesPage.goto(`${BASE_URL}/sources`, { waitUntil: "networkidle" });
    const sourcesList = sourcesPage.locator("ul.grid.md\\:grid-cols-2");
    const sourcesGridCount = await sourcesList.count();
    console.log(`Sources page 2-column grid found: ${sourcesGridCount > 0}`);
    results.sourcesGrid = sourcesGridCount > 0;
    await sourcesPage.close();

    // 5. Check /wrong 2-column layout on Desktop
    console.log("\n--- PART 5: /wrong 2-column layout on Desktop ---");
    const wrongPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await wrongPage.goto(`${BASE_URL}/wrong`, { waitUntil: "networkidle" });
    const wrongList = wrongPage.locator("ul.grid.md\\:grid-cols-2");
    const wrongGridCount = await wrongList.count();
    console.log(`Wrong page 2-column grid for mistakes found: ${wrongGridCount > 0}`);
    results.wrongGrid = wrongGridCount > 0;
    await wrongPage.close();

    // 6. Check /usage 2-column layout on Desktop
    console.log("\n--- PART 6: /usage 2-column layout on Desktop ---");
    const usagePage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await usagePage.goto(`${BASE_URL}/usage`, { waitUntil: "networkidle" });
    const usageList = usagePage.locator("ul.grid.md\\:grid-cols-2");
    const usageGridCount = await usageList.count();
    console.log(`Usage page 2-column grid found: ${usageGridCount > 0}`);
    results.usageGrid = usageGridCount > 0;
    await usagePage.close();

  } finally {
    await browser.close();
  }

  console.log("\n=== ALL TASK 3 POLISH CHECKS COMPLETED ===");
  console.log(JSON.stringify(results, null, 2));
}

main().catch((err) => {
  console.error("Verification error:", err);
  process.exit(1);
});
