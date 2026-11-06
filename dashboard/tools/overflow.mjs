// usage: node tools/overflow.mjs http://localhost:PORT
import puppeteer from "puppeteer-core";

const base = process.argv[2];
const paths = ["/", "/pipeline", "/data", "/instruments", "/instruments/AAPL", "/concepts", "/research", "/books", "/system"];
const widths = [390, 768, 1280];
const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome",
  args: ["--no-sandbox"],
});
let failed = false;
for (const width of widths) {
  const page = await browser.newPage();
  await page.setViewport({ width, height: 900 });
  for (const path of paths) {
    await page.goto(base + path, { waitUntil: "networkidle0" });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 1) {
      console.log(`FAIL ${width}px ${path} overflows by ${over}px`);
      failed = true;
    } else {
      console.log(`ok   ${width}px ${path}`);
    }
  }
  await page.close();
}
await browser.close();
process.exit(failed ? 1 : 0);
