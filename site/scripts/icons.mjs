/*
  Rasterise the favicon, and render the card image that a shared link shows.

    node scripts/icons.mjs          # needs the dev server running

  ## Why PNGs at all

  An SVG favicon is enough for a browser tab and is not enough for anything
  else. Google's crawler wants a raster it can fetch at a stable URL, iOS wants
  a 180-pixel apple-touch-icon and will otherwise screenshot the page, and a
  handful of surfaces still ask for favicon.ico by path whatever the document
  says. The SVG stays as the sharp one; these are the fallbacks.

  ## Why the card image is a screenshot

  Anything else would be a drawing of the site. The one thing worth putting in
  front of somebody who has been sent the link is the thing the site is, so
  this loads the real page, drives the globe to full growth, hides the
  interface, and photographs it.
*/
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const PUBLIC = path.resolve("public");
const SVG = await fs.readFile(path.join(PUBLIC, "mark.svg"), "utf8");

// 96 is the size Google asks for and 180 is what iOS uses for a home screen.
// 32 and 16 are the tab, and they are separate files rather than one scaled
// image because a 16-pixel downsample of a 180-pixel render is mush.
const SIZES = [
  ["favicon-16x16.png", 16],
  ["favicon-32x32.png", 32],
  ["favicon-96x96.png", 96],
  ["apple-touch-icon.png", 180],
];

const browser = await puppeteer.launch({
  args: ["--use-gl=angle", "--enable-webgl", "--hide-scrollbars"],
});

async function icons() {
  const page = await browser.newPage();
  for (const [name, size] of SIZES) {
    await page.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
    // Rendered at the exact pixel size rather than scaled down from one big
    // one, so the stroke widths land where the drawing intends them to.
    await page.setContent(
      `<style>html,body{margin:0;padding:0}svg{display:block;width:${size}px;height:${size}px}</style>${SVG}`,
      { waitUntil: "domcontentloaded" },
    );
    await page.screenshot({ path: path.join(PUBLIC, name), omitBackground: false });
    console.log(`  ${name}`);
  }
  await page.close();
}

async function card() {
  const page = await browser.newPage();
  // 1200x630 is what every link preview crops to. Anything else gets cut.
  await page.setViewport({ width: 1200, height: 630, deviceScaleFactor: 2 });
  await page.goto("http://localhost:5173/", { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 3500));
  await page.evaluate(() => {
    document.querySelector(".opening-skip")?.click();
    // The controls go, the wordmark stays. A card is not clickable, so a row
    // of buttons on it is a lie about what the image is; but a picture of a
    // planet with no name on it could be anybody's.
    for (const sel of [".stack", ".bar"]) {
      const el = document.querySelector(sel);
      if (el) el.style.display = "none";
    }
    const g = window.__globe;
    g.targetProgress = 1;
    g.progress = 1;
    g.apply(1);
    g.spinning = false;
  });
  await new Promise((r) => setTimeout(r, 2000));
  // JPEG, and quality 88. The PNG of this frame is 2.7 MB; several of the
  // services that fetch a card image give up above one, and a photograph of a
  // dark planet is exactly what JPEG is good at.
  await page.screenshot({ path: path.join(PUBLIC, "card.jpg"), type: "jpeg", quality: 88 });
  console.log("  card.jpg");
  await page.close();
}

await icons();
// favicon.ico is that same 32-pixel PNG under the legacy name. Every current
// browser sniffs the content rather than trusting the extension, and a real
// ICO container buys nothing but a dependency.
await card();
await browser.close();
