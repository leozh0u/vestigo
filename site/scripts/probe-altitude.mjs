/*
  How high can the tiles go?

    node scripts/probe-altitude.mjs

  This decides whether the intro can be one continuous move or has to be two
  shots joined.

  Google's Photorealistic 3D Tiles are a *global* dataset, not a Manhattan one.
  The tileset has a root that covers the whole planet and refines as the camera
  descends. If it renders acceptably from orbit, then the entire descent — space
  to street — is one camera move through one dataset, with no seam anywhere in
  it, because there is nothing to seam: it is all the same geometry the whole
  way down.

  If it does not, the intro needs the globe for the top of the move and the
  tiles for the bottom, and the join between them has to be hidden by matching
  the two cameras exactly rather than by dissolving between two different shots.

  Renders one frame per altitude from 600 km down to 2 km, all from a single
  tileset load, which Google bills as one session.
*/
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const OUT = path.resolve("media/altitude");
const PLACE = { lat: 40.7264, lon: -73.9818 };

// Metres. 600 km is roughly where the space station is; 2 km is where the
// existing descent already looks right.
const HEIGHTS = [600000, 200000, 60000, 20000, 6000, 2000];

const harness = (w, h, place) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${w}" height="${h}" style="display:block"></canvas>
<script type="module">
  import * as THREE from "/node_modules/three/build/three.module.js";
  import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
  MANHATTAN.lat = ${place.lat};
  MANHATTAN.lon = ${place.lon};
  window.state = { stage: "starting" };
  (async () => {
    try {
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${w}, ${h}, false);
      // The far plane has to clear the planet's own radius at these altitudes,
      // or the Earth is behind it and the frame is empty.
      const camera = new THREE.PerspectiveCamera(38, ${w} / ${h}, 8, 40000000);
      const m = new Manhattan(renderer, camera);
      await m.load();
      window.__m = m;
      window.__cam = camera;
      window.state = { stage: "ready" };
    } catch (e) {
      window.state = { stage: "failed", why: String(e).slice(0, 300) };
    }
  })();
<\/script></body></html>`;

const browser = await puppeteer.launch({
  headless: true,
  args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
         "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 960, height: 540, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 140)));

await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(harness(960, 540, PLACE), { waitUntil: "networkidle0" });
await page.waitForFunction(
  "window.state !== undefined && window.state.stage !== 'starting'", { timeout: 90_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

await fs.mkdir(OUT, { recursive: true });

for (const height of HEIGHTS) {
  const stats = await page.evaluate(async (height) => {
    const m = window.__m;
    const cam = window.__cam;
    // Straight down, so the frame is only about how much detail exists at this
    // altitude and not about what angle flatters it.
    cam.position.set(0, height, height * 0.35);
    cam.lookAt(0, 0, 0);
    cam.updateMatrixWorld();
    for (let k = 0; k < 400; k++) {
      m.update();
      m.render();
      const s = m.tiles.stats ?? {};
      if (k > 10 && !s.downloading && !s.parsing) break;
      await new Promise((r) => setTimeout(r, 25));
    }
    const s = m.tiles.stats ?? {};
    let meshes = 0;
    m.tiles.group.traverse((o) => { if (o.isMesh) meshes += 1; });
    return { visible: s.visible, active: s.active, meshes };
  }, height);

  const file = path.join(OUT, `${String(height).padStart(7, "0")}m.png`);
  await page.screenshot({ path: file });
  console.log(`  ${(height / 1000).toFixed(0).padStart(4)} km  ` +
              `${stats.meshes} meshes, ${stats.visible} visible`);
}

await browser.close();
console.log(`\n${OUT}`);
