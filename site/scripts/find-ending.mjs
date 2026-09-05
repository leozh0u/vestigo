/*
  Choose where the descent lands.

    node scripts/find-ending.mjs

  The last frame of the descent is the only one that has to be exactly right,
  because it is what the generated interior has to match: the building the
  camera stops on decides the brick, the window, the fire escape and the light,
  and every one of those has to be in the prompt for the next beat.

  Guessing a street corner from a map does not work. Google's photogrammetry is
  flown, so which facades survive at fifty metres and which dissolve into wax is
  not something you can predict from an address — it depends on how many passes
  covered that block and from what angle. So: render the candidate endings and
  look at them.

  All of them come out of one tileset load, which Google bills as a single
  session, so the whole sweep costs the same as one frame.
*/
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const OUT = path.resolve("media/endings");

/*
  Six blocks in the East Village and the Lower East Side.

  All tenement stock: five and six storey walk-ups from the 1900s with iron
  fire escapes on the street front, which is the building the shot needs. The
  towers downtown have none and the brownstones further west have them at the
  back where no camera can see them.
*/
const SPOTS = [
  { name: "e7th-aveA",     lat: 40.72588, lon: -73.98290, look: 210 },
  { name: "stmarks",       lat: 40.72855, lon: -73.98622, look: 160 },
  { name: "e6th-aveB",     lat: 40.72466, lon: -73.98096, look: 250 },
  { name: "ludlow",        lat: 40.72052, lon: -73.98829, look: 340 },
  { name: "e10th-aveA",    lat: 40.72760, lon: -73.98130, look: 195 },
  { name: "orchard",       lat: 40.71880, lon: -73.98940, look:  20 },
];

/*
  Apartment height, not rooftop height.

  The first sweep ran at 44 and 62 metres and every frame came back a bird's
  eye view over the roofs, which is exactly what those numbers are: a tenement
  floor is about three metres, so 44 m is the fourteenth storey of a building
  that has six. Level with a fourth-floor window is twelve to fifteen metres.

  The open question is whether Google's photogrammetry survives down there. It
  is flown, so facades are reconstructed from oblique passes and there is a
  height below which brick becomes wax. This is what measures it.
*/
// Metres above the street now, which is what they always claimed to be. The
// module measures where the street is; see Manhattan.groundLevel.
const HEIGHTS = [9, 14, 20];

const harness = (w, h) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${w}" height="${h}" style="display:block"></canvas>
<script type="module">
  import * as THREE from "/node_modules/three/build/three.module.js";
  import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
  window.state = { stage: "starting" };
  window.THREE = THREE;
  (async () => {
    try {
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${w}, ${h}, false);
      const camera = new THREE.PerspectiveCamera(38, ${w} / ${h}, 8, 80000);
      window.__mk = async (lat, lon) => {
        MANHATTAN.lat = lat; MANHATTAN.lon = lon;
        const m = new Manhattan(renderer, camera);
        await m.load();
        return m;
      };
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
await page.setContent(harness(960, 540), { waitUntil: "networkidle0" });
// window.state is undefined until the module runs, and `undefined?.stage` is
// also not 'starting', so the obvious condition passes instantly and the next
// line reads a property of nothing. Wait for the object first.
await page.waitForFunction(
  "window.state !== undefined && window.state.stage !== 'starting'",
  { timeout: 60_000 });
const ready = await page.evaluate("window.state");
if (ready.stage !== "ready") throw new Error(ready.why ?? "no tiles");

await fs.mkdir(OUT, { recursive: true });

for (const spot of SPOTS) {
  // A fresh Manhattan per spot, because the whole tileset is transformed so
  // that the chosen coordinate sits at the origin, and that transform is
  // applied once at load.
  await page.evaluate(async (lat, lon) => {
    window.__m?.dispose?.();
    window.__m = await window.__mk(lat, lon);
  }, spot.lat, spot.lon);

  for (const height of HEIGHTS) {
    await page.evaluate(async (deg, height) => {
      const m = window.__m;
      const cam = window.__cam;
      /*
        Stand in the street and look level at the building.

        `look` is a compass bearing: which way the camera faces from the chosen
        point. The camera sits 34 m back along that bearing and the aim is 8 m
        below the lens, so the lens is tilted about thirteen degrees down —
        level enough that a fifth-floor window sits in the upper half of the
        frame rather than at the bottom of a bird's-eye view.
      */
      // The origin is about sixteen metres above the street in Manhattan, so
      // everything is offset by the measured ground or the camera ends up nine
      // floors higher than the number says.
      const floor = m.groundLevel() ?? 0;
      const r = (deg * Math.PI) / 180;
      // Across a street, which in the East Village is about twenty-two metres
      // from one building face to the other.
      cam.position.set(Math.sin(r) * 22, floor + height, Math.cos(r) * 22);
      // Level, near enough. Two metres of drop over twenty-two is five degrees,
      // which reads as a camera held by a person rather than as a drone.
      cam.lookAt(0, floor + height - 2, 0);
      cam.updateMatrixWorld();
      for (let k = 0; k < 320; k++) {
        // Re-ask each pass: the ground cannot be measured until geometry has
        // arrived, and the first few frames of a fresh tileset have none.
        const g = m.groundLevel();
        if (g !== null) {
          cam.position.setY(g + height);
          cam.lookAt(0, g + height - 2, 0);
          cam.updateMatrixWorld();
        }
        m.update();
        m.render();
        const s = m.tiles.stats ?? {};
        if (k > 8 && !s.downloading && !s.parsing) break;
        await new Promise((res) => setTimeout(res, 25));
      }
    }, spot.look, height);

    const file = path.join(OUT, `${spot.name}-${height}m.png`);
    await page.screenshot({ path: file });
    console.log(`  ${path.basename(file)}`);
  }
}

await browser.close();
console.log(`\n${OUT}`);
