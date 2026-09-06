/*
  How much defocus makes the tiles look like the globe, measured.

    node scripts/probe-soft.mjs 2 3 4 5

  One tileset load, several blur radii, at the resolution the intro is actually
  rendered at — which matters, because the radius is a fraction of frame width
  and probing at half resolution is how a wrong value shipped once already.

  Prints mean absolute Laplacian, the same number check-intro reports, so the
  answer can be read straight against the globe's.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const RADII = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
const TRY = RADII.length ? RADII : [2, 3, 4, 5];
const PLACE = { lat: 40.72466, lon: -73.98096 };
const W = 1920;
const H = 1080;

async function bundleScene() {
  const env = await fs.readFile(".env.local", "utf8").catch(() => "");
  const key = /^VITE_GOOGLE_MAPS_KEY=(.*)$/m.exec(env)?.[1]?.trim();
  if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");
  const dir = await fs.mkdtemp(".bundle-");
  const out = path.join(dir, "scene.js");
  await new Promise((res, rej) => {
    const p = spawn("npx", ["esbuild", "scripts/scene-entry.js", "--bundle",
      "--format=iife", "--global-name=SCENE",
      `--define:import.meta.env.VITE_GOOGLE_MAPS_KEY=${JSON.stringify(key)}`,
      `--outfile=${out}`], { stdio: ["ignore", "ignore", "inherit"] });
    p.on("close", (c) => (c === 0 ? res() : rej(new Error(`esbuild ${c}`))));
  });
  const code = await fs.readFile(out, "utf8");
  await fs.rm(dir, { recursive: true, force: true });
  return code;
}

const harness = (scene) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${W}" height="${H}" style="display:block"></canvas>
<script>${scene}<\/script>
<script>
  window.state = { stage: "starting" };
  (async () => {
    try {
      const { THREE, Manhattan, MANHATTAN } = window.SCENE;
      MANHATTAN.lat = ${PLACE.lat}; MANHATTAN.lon = ${PLACE.lon};
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${W}, ${H}, false);
      const camera = new THREE.PerspectiveCamera(42, ${W} / ${H}, 8, 40000000);
      const m = new Manhattan(renderer, camera);
      await m.load({ fade: false });
      window.__m = m;
      window.state = { stage: "ready" };
    } catch (e) { window.state = { stage: "failed", why: String(e).slice(0, 300) }; }
  })();
<\/script></body></html>`;

const browser = await puppeteer.launch({
  headless: true,
  args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
         "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
// Through the dev server first, for the origin. See render-descent.mjs.
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(harness(await bundleScene()), { waitUntil: "domcontentloaded" });
await page.waitForFunction("window.state && window.state.stage !== 'starting'", { timeout: 120_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

const OUT = path.resolve("media/soft");
await fs.mkdir(OUT, { recursive: true });

for (const r of TRY) {
  const lap = await page.evaluate(async (r) => {
    const m = window.__m;
    for (let k = 0; k < 500; k++) {
      m.place(0);
      m.update();
      m.render();
      // Overridden after render() has set it from altitude, then rendered again,
      // so the value on screen is the one being asked about.
      const s = m.tiles.stats ?? {};
      if (k > 20 && !s.downloading && !s.parsing) break;
      await new Promise((z) => setTimeout(z, 25));
    }
    m.render();
    m.grade.uniforms.uSoft.value = r;
    m.renderer.setRenderTarget(m.target);
    m.renderer.render(m.scene, m.camera);
    m.renderer.setRenderTarget(null);
    m.renderer.render(m.gradeScene, m.gradeCamera);

    // Mean absolute Laplacian at 480 wide, which is what check-intro measures.
    const c = document.getElementById("c");
    const g = document.createElement("canvas");
    g.width = 480; g.height = 270;
    const x = g.getContext("2d");
    x.drawImage(c, 0, 0, 480, 270);
    const px = x.getImageData(0, 0, 480, 270).data;
    const lum = new Float64Array(480 * 270);
    for (let i = 0; i < lum.length; i++) {
      lum[i] = 0.2126 * px[i * 4] + 0.7152 * px[i * 4 + 1] + 0.0722 * px[i * 4 + 2];
    }
    let sum = 0, n = 0;
    for (let y = 1; y < 269; y++) {
      for (let xx = 1; xx < 479; xx++) {
        const i = y * 480 + xx;
        sum += Math.abs(4 * lum[i] - lum[i - 1] - lum[i + 1] - lum[i - 480] - lum[i + 480]);
        n += 1;
      }
    }
    return sum / n;
  }, r);
  await page.screenshot({ path: path.join(OUT, `soft${r}.png`) });
  console.log(`  uSoft ${String(r).padStart(5)} px at ${W} wide   detail ${lap.toFixed(2)}`);
}

await browser.close();
console.log(`\n${OUT}`);
