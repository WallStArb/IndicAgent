// usage: node tools/motion-check.mjs http://localhost:PORT
// Fails if any text-bearing element is still invisible after the page has been scrolled,
// with reduced motion on (JS on) and with JavaScript off.
import puppeteer from "puppeteer-core";

const base = process.argv[2];
const paths = ["/", "/pipeline", "/data", "/instruments", "/concepts", "/research", "/books", "/system"];
const browser = await puppeteer.launch({ executablePath: "/usr/bin/google-chrome", args: ["--no-sandbox"] });
let failed = false;

async function hidden(page) {
  return page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll("main *, body > div *")) {
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) continue;
      let node = el;
      while (node && node !== document.body) {
        if (Number(getComputedStyle(node).opacity) < 0.01) {
          out.push(el.textContent.trim().slice(0, 40));
          break;
        }
        node = node.parentElement;
      }
    }
    return out;
  });
}

for (const mode of ["reduced-motion", "no-javascript"]) {
  for (const path of paths) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });
    if (mode === "reduced-motion") {
      await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    } else {
      await page.setJavaScriptEnabled(false);
    }
    await page.goto(base + path, { waitUntil: "networkidle0" });
    if (mode === "reduced-motion") {
      const height = await page.evaluate(() => document.documentElement.scrollHeight);
      for (let y = 0; y < height; y += 500) {
        await page.evaluate((v) => window.scrollTo(0, v), y);
        await new Promise((r) => setTimeout(r, 120));
      }
      await new Promise((r) => setTimeout(r, 600));
    }
    const bad = await hidden(page);
    if (bad.length) {
      failed = true;
      console.log(`FAIL ${mode} ${path}: ${bad.length} invisible, e.g. ${JSON.stringify(bad.slice(0, 3))}`);
    } else {
      console.log(`ok   ${mode} ${path}`);
    }
    await page.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
