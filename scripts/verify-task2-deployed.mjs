import { chromium } from "playwright";

const BASE = "https://nightwatch-gules.vercel.app";

async function verifyDeployed() {
  const browser = await chromium.launch({ headless: true });
  console.log("=== VERIFYING TASK 2 DEPLOYED CHANGES ON PRODUCTION ===");
  console.log(`Target: ${BASE}`);

  const results = {
    reloadNoChat: null,
    reloadWithChat: null,
    journalAllTab: null,
    journalReplayTab: null,
    reportFooterDesktop: null,
    reportFooterMobile: null,
    chineseView: null,
  };

  try {
    // --- PART 1: DESKTOP 1440x900: RELOAD CHECKS ---
    console.log("\n--- PART 1: Reload with and without saved chat (Desktop 1440x900) ---");
    const ctxDesktop = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      extraHTTPHeaders: { "x-nw-internal": "1" },
    });
    const page = await ctxDesktop.newPage();

    // 1.1 Reload with NO saved chat
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    const exampleBefore = await page.locator("text=/Example from|示例，生成于/").count();
    console.log("Clean reload without chat: example report count =", exampleBefore);
    results.reloadNoChat = { hasExample: exampleBefore > 0 };

    // 1.2 Seed a chat session in sessionStorage, then reload
    console.log("Seeding a saved chat session in sessionStorage...");
    await page.evaluate(() => {
      sessionStorage.setItem(
        "nw-desk-chat-v1",
        JSON.stringify({
          messages: [
            { role: "user", content: "Long 10k TSLA tonight 5x" },
            { role: "assistant", content: "Checking similar moments and order book..." },
          ],
          contextId: null,
          side: "long",
        })
      );
    });

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);

    // Verify chat messages ARE visible on screen
    const restoredChatMsg = await page.locator("text=Long 10k TSLA tonight 5x").count();
    // Verify static example report is NOT visible beside the restored chat
    const exampleWithChat = await page.locator("text=/Example from|示例，生成于/").count();
    console.log(`Reload with chat: restored chat message count = ${restoredChatMsg}, example report count = ${exampleWithChat}`);
    results.reloadWithChat = {
      chatRestored: restoredChatMsg > 0,
      exampleReportHidden: exampleWithChat === 0,
    };

    // Clean up test chat
    await page.evaluate(() => sessionStorage.removeItem("nw-desk-chat-v1"));

    // --- PART 2: /journal TEXT CHECKS (0 SCORED VS SCORED ROWS) ---
    console.log("\n--- PART 2: /journal 0 scored (All/Tickets) vs scored (Replays) ---");
    await page.goto(BASE + "/journal", { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(3000);

    // 2.1 Check "All" tab (recent in-flight window)
    const plainBoxAll = await page.locator(".border-l-2").first().innerText();
    console.log("Journal (All tab) PlainBox text snippet:\n", plainBoxAll.slice(0, 200), "...");
    const hasCalibLinkAll = await page.locator(".border-l-2 a[href='/calibration']").count();
    const hasWrongLinkAll = await page.locator(".border-l-2 a[href='/wrong']").count();
    console.log("Has link to /calibration:", hasCalibLinkAll > 0, "| Has link to /wrong:", hasWrongLinkAll > 0);

    results.journalAllTab = {
      text: plainBoxAll,
      hasCalibrationLink: hasCalibLinkAll > 0,
      hasWrongLink: hasWrongLinkAll > 0,
    };

    // 2.2 Switch to "Replays" tab (scored rows exist)
    console.log("Switching to Replays tab...");
    const replayBtn = page.getByRole("button", { name: /^Replays|重演$/i });
    if (await replayBtn.isVisible()) {
      await replayBtn.click();
      await page.waitForTimeout(3000);
      const plainBoxReplay = await page.locator(".border-l-2").first().innerText();
      console.log("Journal (Replays tab) PlainBox text snippet:\n", plainBoxReplay.slice(0, 200), "...");
      results.journalReplayTab = { text: plainBoxReplay };
    }

    // --- PART 3: REPORT FOOTER AND RECEIPT LINK (DESKTOP & MOBILE) ---
    console.log("\n--- PART 3: Report footer & receipt link (Desktop 1440x900 & Phone 390x844) ---");
    // Check TSLA example report footer on Home
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(2000);

    const footerDesktop = page.locator(".border-t.border-border\\/70").first();
    if (await footerDesktop.isVisible()) {
      const footerText = await footerDesktop.innerText();
      console.log("Desktop report footer text:", footerText);
      const receiptLink = footerDesktop.locator("a[href*='/api/verify']");
      if (await receiptLink.count() > 0) {
        const box = await receiptLink.first().boundingBox();
        console.log("Desktop receipt link bounding box:", box);
        results.reportFooterDesktop = { visible: true, box, text: footerText };
      } else {
        console.log("Desktop footer visible without receipt link on example");
        results.reportFooterDesktop = { visible: true, text: footerText };
      }
    }

    // 3.2 Mobile 390x844 Touch Check
    console.log("Testing on mobile 390x844 touch viewport...");
    const ctxMobile = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      extraHTTPHeaders: { "x-nw-internal": "1" },
    });
    const pageMobile = await ctxMobile.newPage();
    await pageMobile.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
    await pageMobile.waitForTimeout(2000);

    const footerMobile = pageMobile.locator(".border-t.border-border\\/70").first();
    if (await footerMobile.isVisible()) {
      const box = await footerMobile.boundingBox();
      console.log("Mobile footer bounding box:", box);
      results.reportFooterMobile = { visible: true, box };
    }

    // --- PART 4: CHINESE VIEW ON PHONE ---
    console.log("\n--- PART 4: Chinese View Check ---");
    await pageMobile.goto(BASE + "/journal", { waitUntil: "domcontentloaded", timeout: 60000 });
    await pageMobile.waitForTimeout(2000);
    const zhToggle = pageMobile.locator("button:has-text('中文')").first();
    if (await zhToggle.isVisible()) {
      await zhToggle.click();
      await pageMobile.waitForTimeout(2000);
      const zhPlainBox = await pageMobile.locator(".border-l-2").first().innerText();
      console.log("Chinese /journal PlainBox:\n", zhPlainBox.slice(0, 200), "...");
      results.chineseView = { text: zhPlainBox };
    }

    console.log("\n=== ALL DEPLOYED CHECKS COMPLETED ===");
    console.log(JSON.stringify(results, null, 2));
  } catch (err) {
    console.error("Error during deployed verification:", err);
  } finally {
    await browser.close();
  }
}

verifyDeployed();
