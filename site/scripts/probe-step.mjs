/*
  Walk the descent one frame at a time across a moment that misbehaves.

    node scripts/probe-step.mjs 0.885 0.915

  A full render says "this frame is unlike its neighbours" and nothing about
  why. This steps through the same frames in the same order the render does —
  which matters, because the tileset's state depends on where the camera has
  been — and reports, per frame, where the camera is, how it is pointed, how
  many meshes are loaded, and how much the picture changed.

  Between them those separate a camera that jumped from geometry that changed,
  which are the only two possibilities and which need completely different
  fixes.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { HANDOVER } from "../src/globe/handover.js";

const FROM = Number(process.argv[2] ?? 0.885);
const TO = Number(process.argv[3] ?? 0.915);
const FPS = 30;
const PLACE = { lat: 40.72466, lon: -73.98096 };
const W = 1280;
const H = 720;

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
      window.__m = m; window.__cam = camera;
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
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(harness(await bundleScene()), { waitUntil: "domcontentloaded" });
await page.waitForFunction("window.state && window.state.stage !== 'starting'", { timeout: 180_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

const total = Math.round(HANDOVER.seconds * FPS);
const first = Math.floor(FROM * total);
const last = Math.ceil(TO * total);

// Walked in from well before, so the tileset arrives in the state the render
// leaves it in rather than in whatever a cold jump produces.
await page.evaluate(async (t) => {
  const m = window.__m;
  for (const s of [0.3, 0.6, 0.78]) {
    for (let k = 0; k < 700; k++) {
      m.place(s); m.update(); m.render();
      const st = m.tiles.stats ?? {};
      if (k > 30 && !st.downloading && !st.parsing) break;
      await new Promise((r) => setTimeout(r, 30));
    }
  }
}, FROM);

console.log(`  frame     t      camY    pitch°   meshes   step   note`);
let prev = null;
for (let i = first; i <= last; i++) {
  const info = await page.evaluate(async (t) => {
    const m = window.__m;
    let quiet = 0;
    for (let k = 0; k < 900; k++) {
      m.place(t); m.update(); m.render();
      const s = m.tiles.stats ?? {};
      quiet = (!s.downloading && !s.parsing) ? quiet + 1 : 0;
      if (k > 20 && quiet >= 12) break;
      await new Promise((r) => setTimeout(r, 25));
    }
    const cam = window.__cam;
    const dir = new window.SCENE.THREE.Vector3();
    cam.getWorldDirection(dir);
    let meshes = 0;
    m.tiles.group.traverse((o) => { if (o.isMesh && o.visible) meshes += 1; });
    const c = document.getElementById("c");
    const g = document.createElement("canvas");
    g.width = 48; g.height = 27;
    const x = g.getContext("2d");
    x.drawImage(c, 0, 0, 48, 27);
    const px = x.getImageData(0, 0, 48, 27).data;
    const sig = [];
    for (let p = 0; p < px.length; p += 4) {
      sig.push(0.2126 * px[p] + 0.7152 * px[p + 1] + 0.0722 * px[p + 2]);
    }
    return {
      camY: +cam.position.y.toFixed(3),
      pitch: +(Math.asin(Math.max(-1, Math.min(1, dir.y))) * 180 / Math.PI).toFixed(3),
      meshes, sig,
    };
  }, i / total);

  let step = 0;
  if (prev) {
    for (let p = 0; p < info.sig.length; p++) step += Math.abs(info.sig[p] - prev.sig[p]);
    step /= info.sig.length;
  }
  const dy = prev ? (info.camY - prev.camY).toFixed(3) : "";
  const dp = prev ? (info.pitch - prev.pitch).toFixed(3) : "";
  const dm = prev ? info.meshes - prev.meshes : 0;
  console.log(`  ${String(i).padStart(4)}  ${(i / total).toFixed(4)}  ` +
              `${String(info.camY).padStart(8)}  ${String(info.pitch).padStart(7)}  ` +
              `${String(info.meshes).padStart(5)}  ${step.toFixed(1).padStart(6)}   ` +
              `dy ${dy} dpitch ${dp} dmesh ${dm > 0 ? "+" : ""}${dm}`);
  prev = info;
}

await browser.close();
