/*
  The built window and room, standing on the real wall.

    node scripts/probe-room.mjs

  Renders the facade patch from a few distances along the wall's own normal, so
  the two things that decide whether this works can be looked at: whether the
  patch sits flush in the scanned brick around it, and whether there is anything
  worth arriving at once the window fills the frame.

  Positions come from probe-facade — the wall's centre and its averaged face
  normal — rather than from anything typed in here.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const PLACE = { lat: 40.72466, lon: -73.98096 };
const BACK = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
const AT = BACK.length ? BACK : [26, 12, 4, 1.2];
const W = 1280;
const H = 720;
const OUT = path.resolve("media/room");

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
      const camera = new THREE.PerspectiveCamera(42, ${W} / ${H}, 0.1, 100000);
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
page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 200)));
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(harness(await bundleScene()), { waitUntil: "domcontentloaded" });
await page.waitForFunction("window.state && window.state.stage !== 'starting'", { timeout: 180_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

await page.evaluate(async () => {
  const m = window.__m;
  for (const s of [0.4, 0.7, 0.9, 1.0]) {
    for (let k = 0; k < 700; k++) {
      m.place(s); m.update(); m.render();
      const st = m.tiles.stats ?? {};
      if (k > 30 && !st.downloading && !st.parsing) break;
      await new Promise((r) => setTimeout(r, 30));
    }
  }
});

const wall = await page.evaluate(() => {
  const { THREE, buildRoom } = window.SCENE;
  const m = window.__m;
  const cam = m.camera.position.clone();
  const normalMatrix = new THREE.Matrix3();
  const walls = [];
  for (let dy = -4; dy <= 4; dy += 1) {
    for (let dx = -8; dx <= 8; dx += 1) {
      const from = new THREE.Vector3(cam.x, cam.y + dy, cam.z);
      const a = (105 + dx) * Math.PI / 180;
      const r = new THREE.Raycaster(from,
        new THREE.Vector3(Math.sin(a), 0, Math.cos(a)).normalize(), 1, 60);
      const h = r.intersectObject(m.tiles.group, true);
      if (!h.length || !h[0].face) continue;
      normalMatrix.getNormalMatrix(h[0].object.matrixWorld);
      const n = h[0].face.normal.clone().applyMatrix3(normalMatrix).normalize();
      if (n.dot(cam.clone().sub(h[0].point)) < 0) n.negate();
      if (Math.abs(n.y) < 0.5) walls.push({ point: h[0].point.clone(), n });
    }
  }
  const avg = new THREE.Vector3();
  for (const w of walls) avg.add(w.n);
  avg.normalize();
  // Flattened to horizontal: a wall is plumb and the scan's few degrees of lean
  // is the scan being wrong, not the building.
  avg.y = 0;
  avg.normalize();
  const c = walls.reduce((a, w) => a.add(w.point), new THREE.Vector3())
    .divideScalar(walls.length);

  const room = buildRoom({ centre: c, normal: avg });
  m.scene.add(room);
  window.__room = { centre: c, normal: avg };
  return {
    walls: walls.length,
    centre: [+c.x.toFixed(2), +c.y.toFixed(2), +c.z.toFixed(2)],
    normal: [+avg.x.toFixed(3), +avg.y.toFixed(3), +avg.z.toFixed(3)],
  };
});
console.log(wall);

await fs.mkdir(OUT, { recursive: true });
for (const back of AT) {
  await page.evaluate((back) => {
    const { THREE } = window.SCENE;
    const m = window.__m;
    const { centre, normal } = window.__room;
    const c = new THREE.Vector3(centre.x, centre.y, centre.z);
    const n = new THREE.Vector3(normal.x, normal.y, normal.z);
    const cam = window.__cam;
    cam.up.set(0, 1, 0);
    cam.position.copy(c).addScaledVector(n, back + 1.2);
    cam.lookAt(c.clone().addScaledVector(n, -2));
    cam.near = Math.max(0.05, back * 0.02);
    cam.far = 40000;
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    m.update();
    m.render();
  }, back);
  await page.screenshot({ path: path.join(OUT, `back${back}.png`) });
  console.log(`  ${back} m back`);
}

await browser.close();
console.log(OUT);
