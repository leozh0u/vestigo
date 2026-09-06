/*
  Where the buildings are, at the height the descent is supposed to stop.

    node scripts/probe-window.mjs

  The descent should stop level with a window on an upper floor of a tenement
  and then go in. That needs an actual facade at an actual distance, and neither
  is knowable from a latitude and a longitude: the origin might be in the middle
  of the street, on a roof, or inside a building.

  So this asks the geometry. It stands at the target height and casts rays out
  in every direction, which gives the horizon profile — how far the nearest
  surface is on each bearing. A facade shows up as a run of bearings all
  reporting about the same distance; a street shows up as a gap. Then it puts a
  camera on the far side of the best gap looking at the best facade and
  photographs it, so the framing can be judged rather than guessed at.

  Heights are metres above the street, measured, not above the tileset origin.
  See Manhattan.groundLevel.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const HEIGHTS = [14, 18, 22];
const PLACE = { lat: 40.72466, lon: -73.98096 };
const W = 1280;
const H = 720;
const OUT = path.resolve("media/window");

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
// Through the dev server first, for the origin. See render-descent.mjs.
await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(() => {});
await page.setContent(harness(await bundleScene()), { waitUntil: "domcontentloaded" });
await page.waitForFunction("window.state && window.state.stage !== 'starting'", { timeout: 180_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

// Settle the street, at the altitude the ending happens at, so the fine levels
// of detail are the ones being measured.
/*
  Walked down rather than jumped to.

  Going straight to the ending loads tiles for wherever the camera lands, and
  where it lands depends on the ground level, which is not known until fine
  tiles have loaded. Stepping down through the descent lets each altitude pull
  in the level below it, which is what the real render does and the reason it
  does not hit this.
*/
await page.evaluate(async () => {
  const m = window.__m;
  for (const t of [0.5, 0.75, 0.9, 1.0]) {
    for (let k = 0; k < 700; k++) {
      m.place(t);
      m.update();
      m.render();
      const s = m.tiles.stats ?? {};
      if (k > 30 && !s.downloading && !s.parsing) break;
      await new Promise((r) => setTimeout(r, 30));
    }
  }
});

await fs.mkdir(OUT, { recursive: true });

/*
  Search the block for somewhere to stop.

  What the ending needs is a camera standing in the open at the height of an
  upper-floor window, with a building front close enough to fill the frame and
  far enough that it is not a wall of texture. Those three conditions are not
  guessable from a latitude and a longitude — the target point turns out to be
  inside a building at that height, with a facade 2.1 m away on almost every
  bearing.

  So: sample the neighbourhood on a grid, throw away anywhere that is not in the
  open, and for what is left find the nearest front between twelve and thirty
  metres. That is a camera position and something to point it at.
*/
const HEIGHT = 17;
const found = await page.evaluate((HEIGHT) => {
  const { THREE } = window.SCENE;
  const m = window.__m;
  const floor = m.groundLevel() ?? 0;
  const y = floor + HEIGHT;

  const cast = (from, deg, far = 200) => {
    const a = deg * Math.PI / 180;
    const r = new THREE.Raycaster(from,
      new THREE.Vector3(Math.sin(a), 0, Math.cos(a)).normalize(), 0.5, far);
    const h = r.intersectObject(m.tiles.group, true);
    return h.length ? h[0].distance : far;
  };

  const out = [];
  for (let x = -70; x <= 70; x += 7) {
    for (let z = -70; z <= 70; z += 7) {
      const from = new THREE.Vector3(x, y, z);
      const around = [];
      for (let deg = 0; deg < 360; deg += 15) around.push({ deg, d: cast(from, deg) });
      const clearance = Math.min(...around.map((p) => p.d));
      if (clearance < 9) continue;                 // standing in a wall
      /*
        Far enough back that the front is a front.

        Twelve to thirty metres was the first band, on the theory that closer is
        more intimate. It is not: at seventeen metres up and twelve metres out,
        Google's photogrammetry has no windows in it at all — the wall is a
        smooth pale blob, because the scan never had a clean line of sight to it.
        The tenements read from about thirty metres, where the fire escapes and
        the window reveals survive. That is where the shot has to stop, and the
        last few metres into the room belong to the generated clip.
      */
      const fronts = around.filter((p) => p.d >= 26 && p.d <= 48);
      if (!fronts.length) continue;
      const front = fronts.reduce((a, b) => (a.d < b.d ? a : b));
      // Prefer somewhere that reads as a street: open behind, built in front.
      const behind = cast(from, (front.deg + 180) % 360);
      out.push({ x, z, clearance: +clearance.toFixed(1), deg: front.deg,
                 dist: +front.d.toFixed(1), behind: +Math.min(behind, 200).toFixed(1) });
    }
  }
  out.sort((a, b) => (b.behind - b.dist) - (a.behind - a.dist));
  return { floor: +floor.toFixed(2), best: out.slice(0, 6), total: out.length };
}, HEIGHT);

console.log(`\n  street level ${found.floor} m, ${found.total} candidate positions at ${HEIGHT} m\n`);
for (const [i, c] of found.best.entries()) {
  console.log(`  ${i}  at (${c.x}, ${c.z})  front ${c.dist} m on bearing ${c.deg}, ` +
              `${c.behind} m open behind, ${c.clearance} m clear all round`);
  await page.evaluate((c, HEIGHT) => {
    const { THREE } = window.SCENE;
    const m = window.__m;
    const floor = m.groundLevel() ?? 0;
    const cam = window.__cam;
    cam.up.set(0, 1, 0);
    cam.position.set(c.x, floor + HEIGHT, c.z);
    const a = c.deg * Math.PI / 180;
    cam.lookAt(c.x + Math.sin(a) * c.dist, floor + HEIGHT, c.z + Math.cos(a) * c.dist);
    cam.near = 1; cam.far = 40000; cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    m.update();
    m.render();
  }, c, HEIGHT);
  await page.screenshot({ path: path.join(OUT, `end${i}.png`) });
}

await browser.close();
console.log(`\n${OUT}`);
