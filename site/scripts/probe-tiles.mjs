/*
  Does the Manhattan tileset actually stream and render?

  A self-contained page rather than the running site, for two reasons. The dev
  server's hot reload destroys the execution context mid-test whenever a file
  changes, and borrowing the page's renderer means a failure here could be the
  page's fault rather than the tileset's. This builds its own scene, so what it
  reports is about the tiles.

    node scripts/probe-tiles.mjs

  Needs the dev server running, only to serve the modules and the key.
*/
import puppeteer from "puppeteer";

const HARNESS = `
  <!doctype html><html><body style="margin:0;background:#000">
  <canvas id="c" width="1280" height="720"></canvas>
  <script type="module">
    import * as THREE from "/node_modules/three/build/three.module.js";
    import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
    // The East Village, not the Financial District. The shot has to end on a
    // pre-war walk-up with a fire escape, and those are tenement blocks
    // uptown of the towers.
    MANHATTAN.lat = 40.7264;
    MANHATTAN.lon = -73.9818;

    window.result = { stage: "starting" };
    (async () => {
      try {
        const renderer = new THREE.WebGLRenderer({
          canvas: document.getElementById("c"), antialias: true });
        const camera = new THREE.PerspectiveCamera(50, 1280 / 720, 1, 100000);
        window.result.stage = "loading";
        const m = new Manhattan(renderer, camera);
        await m.load();
        window.result.stage = "streaming";

        // Sit at descent altitude and let tiles arrive.
        for (let i = 0; i < 500; i++) {
          m.place(0.4);
          m.update();
          m.render();
          await new Promise(r => setTimeout(r, 25));
        }
        window.__m = m;      // so a screenshot can be taken at a chosen height
        // What are the tile materials, and do they respond to light at all?
        const kinds = {};
        m.tiles.group.traverse(o => {
          if (o.isMesh && o.material) {
            const k = o.material.type;
            kinds[k] = (kinds[k] || 0) + 1;
            window.__mat = window.__mat || o.material;
          }
        });
        window.__matKinds = kinds;
        const s = m.tiles.stats ?? {};
        window.result = {
          stage: "done", ok: true, ready: m.ready,
          stats: { downloading: s.downloading, parsing: s.parsing,
                   active: s.active, visible: s.visible, inFrustum: s.inFrustum },
          meshes: (() => { let n = 0; m.tiles.group.traverse(o => { if (o.isMesh) n++; }); return n; })(),
        };
      } catch (e) {
        window.result = { stage: "failed", ok: false, why: String(e).slice(0, 400) };
      }
    })();
  <\/script></body></html>`;

const browser = await puppeteer.launch({
  headless: true,
  args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
         "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 720 });
page.on("pageerror", (e) => console.log("  page error:", String(e).slice(0, 200)));
page.on("requestfailed", (r) => {
  if (/tile|google/i.test(r.url())) {
    console.log("  request failed:", r.url().slice(0, 90), r.failure()?.errorText);
  }
});

// Served through the dev server so the module graph and the env key resolve.
await page.goto("http://localhost:5173/__probe.html", { waitUntil: "domcontentloaded" })
  .catch(() => {});
await page.setContent(HARNESS.replace(/^\s+/gm, ""), { waitUntil: "networkidle0" });

try {
  await page.waitForFunction("window.result?.stage === 'done' || window.result?.stage === 'failed'",
                             { timeout: 90_000, polling: 1000 });
} catch {
  console.log("timed out; last stage:", await page.evaluate("window.result?.stage"));
}
console.log(JSON.stringify(await page.evaluate("window.result"), null, 2));

// Frames along the descent, so the thing can actually be looked at.
for (const [name, t] of [["high", 0.45], ["mid", 0.82], ["low", 1.0]]) {
  await page.evaluate(async (t) => {
    const m = window.__m;
    for (let i = 0; i < 160; i++) {
      m.place(t); m.update(); m.render();
      await new Promise(r => setTimeout(r, 25));
    }
  }, t);
  await page.screenshot({ path: `/tmp/tiles_${name}.png` });
  console.log(`  wrote /tmp/tiles_${name}.png`);
}
await browser.close();
