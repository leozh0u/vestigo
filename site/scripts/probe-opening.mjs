/*
  Find a window on the wall the shot finishes on, and check it goes dark.

    node scripts/probe-opening.mjs

  The intro now ends by flying into a window rather than by stopping in front of
  a building, and the join to the built interior happens at the moment the
  opening fills the frame. That only works if the opening is a real recess in
  the scan and if it really does go dark, so both are measured here rather than
  assumed.

  Two signals, and both are needed. A window is **recessed**: rays aimed at it
  travel further before they hit anything than rays aimed at the brick beside
  it. A window is also **dark**, because there is no light in the reconstruction
  behind it. Recession alone finds gaps in the mesh, which are holes rather than
  windows and lead to open sky. Darkness alone finds shadow. Together they find
  windows.

  Reported in metres above the street, which is what the descent is written in.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const PLACE = { lat: 40.72466, lon: -73.98096 };
const W = 1280;
const H = 720;
const OUT = path.resolve("media/opening");
// Where the camera stands to survey the wall, metres out along its normal.
const SURVEY = 26;

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

await fs.mkdir(OUT, { recursive: true });

const found = await page.evaluate((SURVEY) => {
  const { THREE, buildFacade } = window.SCENE;
  const m = window.__m;
  const floor = m.groundLevel() ?? 0;
  const from0 = m.camera.position.clone();

  // The wall, from face normals, flattened to plumb: a wall is vertical and the
  // scan's few degrees of lean is the scan being wrong, not the building.
  const nm = new THREE.Matrix3();
  const walls = [];
  for (let dy = -4; dy <= 4; dy += 1) {
    for (let dx = -8; dx <= 8; dx += 1) {
      const from = new THREE.Vector3(from0.x, from0.y + dy, from0.z);
      const a = (105 + dx) * Math.PI / 180;
      const r = new THREE.Raycaster(from,
        new THREE.Vector3(Math.sin(a), 0, Math.cos(a)).normalize(), 1, 60);
      const h = r.intersectObject(m.tiles.group, true);
      if (!h.length || !h[0].face) continue;
      nm.getNormalMatrix(h[0].object.matrixWorld);
      const n = h[0].face.normal.clone().applyMatrix3(nm).normalize();
      if (n.dot(from0.clone().sub(h[0].point)) < 0) n.negate();
      if (Math.abs(n.y) < 0.5) walls.push({ p: h[0].point.clone(), n });
    }
  }
  const normal = new THREE.Vector3();
  for (const w of walls) normal.add(w.n);
  normal.y = 0;
  normal.normalize();
  const centre = walls.reduce((a, w) => a.add(w.p), new THREE.Vector3())
    .divideScalar(walls.length);

  /*
    The window goes where the wall is flattest, at the height a fifth floor is.

    Not where the scan has a dark rectangle painted on it: those are texture, and
    putting a built window over a painted one gives two windows in the same
    place. What matters is that the brick behind the patch is even, so the patch
    sits down on it instead of hovering over a bulge.
  */
  const across = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), normal).normalize();
  const eye = centre.clone().addScaledVector(normal, SURVEY);
  const HEIGHT = 16;
  let best = null;
  for (let s = -7; s <= 7; s += 0.5) {
    const depths = [];
    for (let dh = -1.6; dh <= 1.6; dh += 0.4) {
      for (let ds = -0.9; ds <= 0.9; ds += 0.45) {
        const target = centre.clone()
          .addScaledVector(across, s + ds)
          .setY(floor + HEIGHT + dh);
        const r = new THREE.Raycaster(eye, target.clone().sub(eye).normalize(), 1, 200);
        const h = r.intersectObject(m.tiles.group, true);
        if (h.length) depths.push(h[0].distance);
      }
    }
    if (depths.length < 20) continue;
    const mean = depths.reduce((a, b) => a + b, 0) / depths.length;
    const rough = Math.sqrt(depths.reduce((a, b) => a + (b - mean) ** 2, 0) / depths.length);
    if (!best || rough < best.rough) best = { s, rough: +rough.toFixed(3), mean: +mean.toFixed(2) };
  }

  // The window's own point on the wall: along the wall by the chosen offset, at
  // the chosen height, and on the surface the rays actually hit there.
  const aim = centre.clone().addScaledVector(across, best.s).setY(floor + HEIGHT);
  const ray = new THREE.Raycaster(eye, aim.clone().sub(eye).normalize(), 1, 200);
  const hit = ray.intersectObject(m.tiles.group, true)[0];
  const windowAt = hit ? hit.point.clone() : aim;

  /*
    The brick's colour, read off the wall rather than chosen.

    The patch is unlit, and so are the tiles, so what is sampled is what will
    come out. Sampled around the window and not on it, and with the darkest
    fifth thrown away, because the painted-on windows are part of that wall and
    averaging them in makes the brick too dark.
  */
  const cam = window.__cam;
  cam.up.set(0, 1, 0);
  cam.position.copy(eye);
  cam.lookAt(centre);
  cam.near = 0.5; cam.far = 40000;
  cam.updateProjectionMatrix(); cam.updateMatrixWorld();
  m.update(); m.render();
  const c = document.getElementById("c");
  const g = document.createElement("canvas");
  g.width = c.width; g.height = c.height;
  const gx = g.getContext("2d");
  gx.drawImage(c, 0, 0);
  const px = gx.getImageData(0, 0, g.width, g.height).data;
  const samples = [];
  for (let dh = -3; dh <= 3; dh += 0.5) {
    for (let ds = -6; ds <= 6; ds += 0.5) {
      const target = centre.clone()
        .addScaledVector(across, best.s + ds)
        .setY(floor + HEIGHT + dh);
      const v = target.project(cam);
      const x = Math.round((v.x * 0.5 + 0.5) * g.width);
      const y = Math.round((-v.y * 0.5 + 0.5) * g.height);
      if (x < 0 || y < 0 || x >= g.width || y >= g.height) continue;
      const i = (y * g.width + x) * 4;
      samples.push([px[i], px[i + 1], px[i + 2],
        0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]]);
    }
  }
  samples.sort((a, b) => a[3] - b[3]);
  const keep = samples.slice(Math.floor(samples.length * 0.2));
  const avg = keep.reduce((a, s) => [a[0] + s[0], a[1] + s[1], a[2] + s[2]], [0, 0, 0])
    .map((v) => Math.round(v / keep.length));
  const hex = "#" + avg.map((v) => v.toString(16).padStart(2, "0")).join("");

  const facade = buildFacade({ centre: windowAt, normal, colour: hex });
  m.scene.add(facade);
  window.__facade = { at: windowAt, normal, hex };

  return {
    floor: +floor.toFixed(2),
    normal: [+normal.x.toFixed(4), 0, +normal.z.toFixed(4)],
    flattestAcross: best.s,
    roughnessThere: best.rough,
    windowAt: [+windowAt.x.toFixed(2), +windowAt.y.toFixed(2), +windowAt.z.toFixed(2)],
    windowHeightAboveStreet: +(windowAt.y - floor).toFixed(2),
    brickColour: hex,
    sampled: keep.length,
  };
}, SURVEY);

console.log(JSON.stringify(found, null, 2));
await page.screenshot({ path: path.join(OUT, "survey.png") });

for (const back of [14, 6, 2, 0.6, 0.25]) {
  const lum = await page.evaluate((back) => {
    const { THREE } = window.SCENE;
    const m = window.__m;
    const at = new THREE.Vector3().copy(window.__facade.at);
    const n = new THREE.Vector3().copy(window.__facade.normal);
    // The window plane is the patch's front face, which stands proud of the
    // scanned wall. Distances here are from that plane.
    const plane = at.clone().addScaledVector(n, 1.3);
    const cam = window.__cam;
    cam.up.set(0, 1, 0);
    cam.position.copy(plane).addScaledVector(n, back);
    cam.lookAt(plane.clone().addScaledVector(n, -4));
    cam.near = Math.max(0.03, back * 0.03);
    cam.far = 100000;
    cam.updateProjectionMatrix(); cam.updateMatrixWorld();
    m.update(); m.render();
    const c = document.getElementById("c");
    const g = document.createElement("canvas");
    g.width = 64; g.height = 36;
    const x = g.getContext("2d");
    x.drawImage(c, 0, 0, 64, 36);
    const d = x.getImageData(0, 0, 64, 36).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) {
      sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    }
    return +(sum / (d.length / 4)).toFixed(1);
  }, back);
  await page.screenshot({ path: path.join(OUT, `at${back}.png`) });
  console.log(`  ${String(back).padStart(5)} m from the window   mean brightness ${lum}`);
}

await browser.close();
console.log(OUT);
