/*
  A picture of the interface, for the laptop screen in the intro.

    node scripts/capture-ui.mjs

  The camera flies through a window and settles on a laptop, and the interface
  has to be *on* that laptop before the frame arrives at it — not faded up
  afterwards. A screen that is black until the shot ends and then lights up is
  two events; a screen that has been showing the page the whole way in is one
  move that finishes by filling the frame with what was already there.

  So the texture is the real page, screenshotted, rather than anything drawn to
  approximate it. When the bezel scales up at the end there is nothing to line
  up, because the thing being scaled is the thing it becomes.

  Needs the dev server. Written to media/, not to public/: it is an input to a
  render, not something the site serves.
*/
import fs from "node:fs/promises";
import puppeteer from "puppeteer";

const OUT = "media/ui.png";
// The laptop screen's own proportions, so nothing is stretched onto it.
const W = 1600;
const H = 1000;

const browser = await puppeteer.launch({
  headless: true,
  args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
         "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 200)));

await page.goto("http://localhost:5173/", { waitUntil: "networkidle2", timeout: 60_000 });

/*
  Past the opening, without waiting for it.

  Clicking ENTER plays the whole intro before the interface appears, which is
  twenty seconds of waiting for a screenshot. Removing the overlay leaves the
  page underneath, which has been there since load.
*/
await page.evaluate(() => {
  for (const el of document.querySelectorAll("[class*='opening']")) el.remove();
  document.documentElement.classList.remove("opening-open", "no-scroll");
  document.body.style.overflow = "";
});

// The globe takes a moment to have anything in it, and a screen with a blank
// globe on it is worse than no screen at all.
await page.waitForFunction(() => {
  const c = document.querySelector("canvas");
  return c && c.width > 200;
}, { timeout: 30_000 });
// Long enough for the sphere to have finished becoming a planet. Four seconds
// caught it mid-transformation, half metal, which is a fine picture and not the
// one the interface settles on.
await new Promise((r) => setTimeout(r, 14000));

await fs.mkdir("media", { recursive: true });
await page.screenshot({ path: OUT });

/*
  What the globe was doing when the picture was taken.

  The clip ends by growing this screenshot until it is the page, and the page
  underneath is live: its planet is turning. Two images that are the same in
  every respect except that one of them is moving do not cross-dissolve, they
  reveal the join — which is what made the handoff read as an edit rather than
  as an arrival.

  So the state is written down here and set on the live globe just before the
  growth starts. The two are then the same frame, and the planet begins turning
  again once the transition is over rather than during it.
*/
const state = await page.evaluate(() => {
  const g = window.__globe;
  if (!g) return null;
  return {
    rotY: +g.metal.rotation.y.toFixed(5),
    rotX: +g.metal.rotation.x.toFixed(5),
    distance: +g.camera.position.z.toFixed(4),
  };
});
if (state) {
  await fs.writeFile("media/ui-state.json", `${JSON.stringify(state, null, 2)}\n`);
  console.log("  globe at", state);
} else {
  console.log("  no globe on the page — the handoff will fall back to a fade");
}
const stat = await fs.stat(OUT);
console.log(`wrote ${OUT}  ${W}x${H}  ${(stat.size / 1e3).toFixed(0)} kB`);
await browser.close();
