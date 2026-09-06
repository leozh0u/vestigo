/*
  The plane of the building the descent finishes on.

    node scripts/probe-facade.mjs

  Anything built onto that facade — a window to fly through, a panel of brick to
  cover what the scan melted — has to sit *on* it, in its plane, facing the way
  it faces. Guessing the orientation from the bearing the camera happens to be
  pointed is not the same thing: streets are not square to each other and the
  wall is wherever it is.

  So it is measured. A grid of rays from the camera's ending position into the
  front, keeping the hits, and a plane fitted to them by least squares. The
  spread of the hits around that plane says whether it is a flat wall worth
  fitting or a jumble the fit is meaningless on.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

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
      const camera = new THREE.PerspectiveCamera(42, ${W} / ${H}, 5, 100000);
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

// Walked down, so the fine levels around the ending are the ones measured.
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

const fit = await page.evaluate(() => {
  const { THREE } = window.SCENE;
  const m = window.__m;
  const floor = m.groundLevel() ?? 0;
  const cam = m.camera.position.clone();

  /*
    Face normals, not a plane fitted to hit points.

    Fitting a plane to where a fan of rays lands answers the wrong question when
    the fan crosses a roofline: the first attempt spanned sixteen metres of
    height, caught the roof and the setback along with the wall, and reported a
    surface tilted thirty-eight degrees from vertical with the points scattered
    by nearly a metre. That is a real description of a jumble, and useless.

    Every hit already carries the normal of the triangle it landed on. Keeping
    only the ones that are near-vertical — a wall — and averaging those gives the
    orientation of the wall itself, and how many were thrown away says how much
    of what is there is wall at all.
  */
  const normalMatrix = new THREE.Matrix3();
  const walls = [];
  const all = [];
  for (let dy = -4; dy <= 4; dy += 1) {
    for (let dx = -8; dx <= 8; dx += 1) {
      const from = new THREE.Vector3(cam.x, cam.y + dy, cam.z);
      const a = (105 + dx) * Math.PI / 180;
      const dir = new THREE.Vector3(Math.sin(a), 0, Math.cos(a)).normalize();
      const r = new THREE.Raycaster(from, dir, 1, 60);
      const h = r.intersectObject(m.tiles.group, true);
      if (!h.length || !h[0].face) continue;
      const hit = h[0];
      normalMatrix.getNormalMatrix(hit.object.matrixWorld);
      const n = hit.face.normal.clone().applyMatrix3(normalMatrix).normalize();
      if (n.dot(cam.clone().sub(hit.point)) < 0) n.negate();
      all.push({ point: hit.point.clone(), n });
      // Within thirty degrees of vertical is a wall; a roof is not.
      if (Math.abs(n.y) < 0.5) walls.push({ point: hit.point.clone(), n });
    }
  }
  if (walls.length < 8) return { rays: all.length, walls: walls.length };

  const avg = new THREE.Vector3();
  for (const w of walls) avg.add(w.n);
  avg.normalize();
  const c = walls.reduce((a, w) => a.add(w.point), new THREE.Vector3())
    .divideScalar(walls.length);
  const spread = Math.sqrt(walls.reduce((s, w) =>
    s + Math.pow(w.point.clone().sub(c).dot(avg), 2), 0) / walls.length);
  const agree = walls.reduce((s, w) => s + w.n.dot(avg), 0) / walls.length;
  const bearing = (Math.atan2(-avg.x, -avg.z) * 180 / Math.PI + 360) % 360;

  return {
    rays: all.length,
    walls: walls.length,
    floor: +floor.toFixed(2),
    camera: [+cam.x.toFixed(2), +cam.y.toFixed(2), +cam.z.toFixed(2)],
    wallCentre: [+c.x.toFixed(2), +c.y.toFixed(2), +c.z.toFixed(2)],
    heightAboveStreet: +(c.y - floor).toFixed(2),
    normal: [+avg.x.toFixed(4), +avg.y.toFixed(4), +avg.z.toFixed(4)],
    facesBearing: +bearing.toFixed(1),
    tiltFromVertical: +(Math.asin(Math.abs(avg.y)) * 180 / Math.PI).toFixed(2),
    flatnessMetres: +spread.toFixed(2),
    normalsAgree: +agree.toFixed(3),
    distance: +cam.distanceTo(c).toFixed(2),
  };
});

console.log(fit);

/*
  Square on to the wall, and is there room to stand there.

  The ending was aimed on a bearing picked by searching for *a* front, and the
  front it found faces 143 degrees while the camera approaches on 105. Thirty-
  eight degrees off square is a fine angle to look at a building and a bad one
  to fly through a window in it: the opening foreshortens to a slot and the
  frame reads as a wall with a hole rather than as somewhere to go.

  So this steps back along the wall's own normal and checks the position is in
  the open before recommending it.
*/
const squared = await page.evaluate((fit, back) => {
  const { THREE } = window.SCENE;
  const m = window.__m;
  const c = new THREE.Vector3(...fit.wallCentre);
  const n = new THREE.Vector3(...fit.normal).normalize();
  const at = c.clone().addScaledVector(n, back);

  let clear = 999;
  for (let deg = 0; deg < 360; deg += 10) {
    const a = deg * Math.PI / 180;
    const r = new THREE.Raycaster(at,
      new THREE.Vector3(Math.sin(a), 0, Math.cos(a)).normalize(), 0.5, 200);
    const h = r.intersectObject(m.tiles.group, true);
    if (h.length) clear = Math.min(clear, h[0].distance);
  }

  const cam = window.__cam;
  cam.up.set(0, 1, 0);
  cam.position.copy(at);
  cam.lookAt(c);
  cam.near = 1; cam.far = 40000; cam.updateProjectionMatrix(); cam.updateMatrixWorld();
  m.update(); m.render();

  return {
    stand: [+at.x.toFixed(2), +at.y.toFixed(2), +at.z.toFixed(2)],
    heightAboveStreet: +(at.y - (m.groundLevel() ?? 0)).toFixed(2),
    clearAllRound: +clear.toFixed(1),
    backedOff: back,
  };
}, fit, 30);

console.log(squared);
await fs.mkdir("media/facade", { recursive: true });
await page.screenshot({ path: "media/facade/square-on.png" });
console.log("media/facade/square-on.png");

await browser.close();
