/*
  Where the laptop screen sits in the last frame of the descent.

    node scripts/probe-screen.mjs

  render-descent writes this itself, at the end of a render. This exists for the
  case where the shot has not changed but the number is wanted — after a change
  to the handoff, say — because re-rendering four hundred and fifty frames of
  streamed photogrammetry to recover four numbers is a poor trade.

  Same scene, same camera, same final placement, so it produces the same answer.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const PLACE = { lat: 40.72466, lon: -73.98096 };
const W = 1920;
const H = 1080;

const dir = await fs.mkdtemp(".bundle-");
const out = path.join(dir, "scene.js");
const env = await fs.readFile(".env.local", "utf8").catch(() => "");
const key = /^VITE_GOOGLE_MAPS_KEY=(.*)$/m.exec(env)?.[1]?.trim();
if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");
await new Promise((res, rej) => {
  const p = spawn("npx", ["esbuild", "scripts/scene-entry.js", "--bundle",
    "--format=iife", "--global-name=SCENE",
    `--define:import.meta.env.VITE_GOOGLE_MAPS_KEY=${JSON.stringify(key)}`,
    `--outfile=${out}`], { stdio: ["ignore", "ignore", "inherit"] });
  p.on("close", (c) => (c === 0 ? res() : rej(new Error(`esbuild ${c}`))));
});
const scene = await fs.readFile(out, "utf8");
await fs.rm(dir, { recursive: true, force: true });

const browser = await puppeteer.launch({
  headless: true,
  args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
         "--enable-unsafe-swiftshader", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 200)));
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(`
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${W}" height="${H}"></canvas>
<script>${scene}<\/script>
<script>
  window.state = { stage: "starting" };
  (async () => {
    try {
      const { THREE, Manhattan, MANHATTAN } = window.SCENE;
      MANHATTAN.lat = ${PLACE.lat}; MANHATTAN.lon = ${PLACE.lon};
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1); renderer.setSize(${W}, ${H}, false);
      const camera = new THREE.PerspectiveCamera(42, ${W} / ${H}, 0.02, 40000000);
      const m = new Manhattan(renderer, camera);
      await m.load({ fade: false });
      window.__m = m;
      window.state = { stage: "ready" };
    } catch (e) { window.state = { stage: "failed", why: String(e).slice(0, 300) }; }
  })();
<\/script></body></html>`, { waitUntil: "domcontentloaded" });
await page.waitForFunction("window.state && window.state.stage !== 'starting'", { timeout: 180_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

// Walked down, so the ground is measured the way the render measures it and
// the facade lands in the same place.
const screen = await page.evaluate(async () => {
  const { THREE } = window.SCENE;
  const m = window.__m;
  for (const t of [0.3, 0.6, 0.8, 0.92, 1.0]) {
    for (let k = 0; k < 700; k++) {
      m.place(t); m.update(); m.render();
      const s = m.tiles.stats ?? {};
      if (k > 30 && !s.downloading && !s.parsing) break;
      await new Promise((r) => setTimeout(r, 30));
    }
  }
  const mesh = m.facade?.userData?.screen;
  if (!mesh) return null;
  mesh.updateMatrixWorld(true);
  const g = mesh.geometry.attributes.position;
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (let i = 0; i < g.count; i++) {
    const v = new THREE.Vector3().fromBufferAttribute(g, i)
      .applyMatrix4(mesh.matrixWorld).project(m.camera);
    minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x);
    minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y);
  }
  return {
    x: +((minX + maxX) / 2 * 0.5 + 0.5).toFixed(4),
    y: +(-(minY + maxY) / 2 * 0.5 + 0.5).toFixed(4),
    w: +((maxX - minX) / 2).toFixed(4),
    h: +((maxY - minY) / 2).toFixed(4),
  };
});
await browser.close();

if (!screen) throw new Error("no facade in the scene at the end of the shot");
await fs.writeFile("media/descent-end.json", `${JSON.stringify(screen, null, 2)}\n`);
console.log(screen);
console.log(`  the screen is ${(screen.w * 100).toFixed(0)}% of the frame wide, ` +
            `centred at ${(screen.x * 100).toFixed(0)}%, ${(screen.y * 100).toFixed(0)}%`);
console.log("wrote media/descent-end.json");
