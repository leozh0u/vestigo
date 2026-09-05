/*
  Three frames from the descent, in about a minute.

    node scripts/probe-move.mjs            # t = 0, 0.5, 1
    node scripts/probe-move.mjs 0 0.2 0.9

  A full render is 330 frames and ten minutes, and using it to answer "is the
  picture black" wastes both. This drives the same `place()` at a handful of
  moments and reports the mean brightness of each, so a shot that has gone dark
  says so immediately and says where.

  Self-contained, like render-descent.mjs: the scene is bundled and inlined, so
  editing the repository while this runs cannot destroy it.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const TS = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
const MOMENTS = TS.length ? TS : [0, 0.5, 1];
const OUT = path.resolve("media/move");
const PLACE = { lat: 40.7264, lon: -73.9818 };

async function bundleScene() {
  const env = await fs.readFile(".env.local", "utf8").catch(() => "");
  const key = /^VITE_GOOGLE_MAPS_KEY=(.*)$/m.exec(env)?.[1]?.trim();
  if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");
  const dir = await fs.mkdtemp(".bundle-");
  const out = path.join(dir, "scene.js");
  await new Promise((res, rej) => {
    const p = spawn("npx", [
      "esbuild", "scripts/scene-entry.js", "--bundle", "--format=iife",
      "--global-name=SCENE",
      `--define:import.meta.env.VITE_GOOGLE_MAPS_KEY=${JSON.stringify(key)}`,
      `--outfile=${out}`,
    ], { stdio: ["ignore", "ignore", "inherit"] });
    p.on("close", (c) => (c === 0 ? res() : rej(new Error(`esbuild ${c}`))));
  });
  const code = await fs.readFile(out, "utf8");
  await fs.rm(dir, { recursive: true, force: true });
  return code;
}

const harness = (w, h, place, scene) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${w}" height="${h}" style="display:block"></canvas>
<script>${scene}<\/script>
<script>
  window.state = { stage: "starting" };
  (async () => {
    try {
      const { THREE, Manhattan, MANHATTAN } = window.SCENE;
      MANHATTAN.lat = ${place.lat}; MANHATTAN.lon = ${place.lon};
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${w}, ${h}, false);
      const camera = new THREE.PerspectiveCamera(38, ${w} / ${h}, 8, 40000000);
      const m = new Manhattan(renderer, camera);
      await m.load();
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
await page.setViewport({ width: 960, height: 540, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 140)));

/*
  Loaded through the dev server first, and this matters.

  Not for the modules — those are bundled and inlined below. For the
  *origin*. A page built with setContent alone is about:blank, whose origin
  is null, and Google's tile API checks the Origin header against the key's
  allowed referrers. The key is restricted to localhost:5173 and
  vestigo.earth, so from a null origin every tile request is rejected.

  Silently. TilesRenderer reports nothing downloading and nothing parsing,
  which is indistinguishable from "finished", so the settle loop exits
  immediately and the frame is photographed with no geometry in it. Two
  eleven-second renders came out black this way and both were read as a
  shading problem.

  Navigating first and then replacing the document keeps the origin and
  drops the module graph, which is the combination that was wanted: no
  imports for hot reload to tear down, and a referrer Google accepts.
*/
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" })
  .catch(() => {});
await page.setContent(harness(960, 540, PLACE, await bundleScene()),
                      { waitUntil: "domcontentloaded" });
await page.waitForFunction(
  "window.state !== undefined && window.state.stage !== 'starting'", { timeout: 90_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

await fs.mkdir(OUT, { recursive: true });

for (const t of MOMENTS) {
  const info = await page.evaluate(async (t) => {
    const m = window.__m;
    for (let k = 0; k < 500; k++) {
      m.place(t);
      m.update();
      m.render();
      const s = m.tiles.stats ?? {};
      if (k > 20 && !s.downloading && !s.parsing) break;
      await new Promise((r) => setTimeout(r, 25));
    }
    const cam = window.__cam;
    const ground = m.groundLevel() ?? 0;
    /*
      What the frame actually contains, measured off the canvas.

      Mean brightness answers "is it black", which a screenshot answers too but
      only once somebody looks. The camera numbers answer "why": a dark frame
      with the camera at the right altitude is a shading problem, and a dark
      frame with the camera somewhere absurd is not.
    */
    const c = document.getElementById("c");
    const g = document.createElement("canvas");
    g.width = 32; g.height = 18;
    const x = g.getContext("2d");
    x.drawImage(c, 0, 0, 32, 18);
    const px = x.getImageData(0, 0, 32, 18).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += px[i] + px[i + 1] + px[i + 2];
    return {
      mean: +(sum / (px.length / 4 * 3)).toFixed(1),
      altitude: Math.round(cam.position.y - ground),
      near: cam.near,
      far: cam.far,
      meshes: (() => { let n = 0; m.tiles.group.traverse((o) => { if (o.isMesh) n += 1; }); return n; })(),
      fog: m.grade ? Math.round(m.grade.uniforms.uFog.value) : null,
      sky: m.sky ? m.sky.visible : null,
    };
  }, t);

  await page.screenshot({ path: path.join(OUT, `t${t.toFixed(2)}.png`) });
  console.log(`  t=${t.toFixed(2)}  mean ${String(info.mean).padStart(5)}  ` +
              `alt ${String(info.altitude).padStart(7)}m  near ${info.near}  ` +
              `fog ${info.fog}  sky ${info.sky}  ${info.meshes} meshes`);
}

await browser.close();
console.log(`\n${OUT}`);
