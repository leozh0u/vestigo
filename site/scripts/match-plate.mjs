/*
  Fit the tone curve that makes the tiles look like the globe at the handover.

    node scripts/match-plate.mjs

  Writes src/globe/plate-lut.js. Run it whenever either half of the handover
  changes — the altitude it happens at, the globe's texture, the defocus, or the
  descent's grade — because the curve is fitted to those two specific frames and
  is meaningless against different ones.

  ## Why a curve

  The two halves draw water in opposite directions. On Blue Marble the Great
  Lakes are almost black and the shelf is a pale band; on Google's coarse plate
  every body of water is the same light lavender, lakes included. Across the
  seam the lakes went from black to white, in the middle of frame. Matching the
  averages of "water" and "land" cannot fix that, because it needs bright water
  pulled down while bright land stays where it is, which is a different answer
  at different input levels.

  ## The fit

  Histogram matching, per channel. Build the cumulative distribution of each
  channel in both frames, and for every input level find the level in the globe
  that sits at the same rank. A pixel in the darkest two per cent of the tiles
  comes out at whatever the darkest two per cent of the globe is, and so on all
  the way up. Nothing is assumed about what is water and what is land.

  It works here only because the framing is already identical — same place, same
  altitude, same field of view — so the two frames contain the same proportions
  of the same things and rank really does mean the same thing on both sides.
  Against unmatched framings this would be nonsense, which is why it is the last
  correction fitted rather than the first.

  Then the curve is forced monotone and smoothed. Ranks come from finite
  samples, so a curve read straight off them wobbles, and a non-monotone tone
  curve makes darker pixels come out lighter than their neighbours, which shows
  up as banding in a sky.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { HANDOVER } from "../src/globe/handover.js";

const W = 1920;
const H = 1080;
const N = 64;                       // entries in the curve
const EARTH = "media/earth.mp4";
const OUT = "src/globe/plate-lut.js";
const PLACE = { lat: 40.72466, lon: -73.98096 };

const run = (cmd, args) => new Promise((res, rej) => {
  const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
  let out = "";
  let err = "";
  p.stdout.on("data", (d) => { out += d; });
  p.stderr.on("data", (d) => { err += d; });
  p.on("close", (c) => (c === 0 ? res(out) : rej(new Error(err.slice(-400)))));
});

/*
  The globe's frame at the exact moment the blend opens.

  Not its last frame. The dissolve pairs the globe at the start of the overlap
  with the tiles at zero, so that is the frame the tiles have to match; the
  globe's final frame is a tenth of a second further down and a few per cent
  closer.
*/
async function globeFrame() {
  const seconds = Number(await run("ffprobe", ["-v", "error", "-show_entries",
    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", EARTH]));
  const at = seconds - HANDOVER.fade;
  const dir = await fs.mkdtemp(".match-");
  const raw = path.join(dir, "g.raw");
  await run("ffmpeg", ["-v", "error", "-ss", at.toFixed(3), "-i", EARTH,
    "-frames:v", "1", "-vf", `scale=${W}:${H}`, "-f", "rawvideo",
    "-pix_fmt", "rgb24", raw]);
  const buf = await fs.readFile(raw);
  await fs.rm(dir, { recursive: true, force: true });
  console.log(`  globe reference at ${at.toFixed(2)}s of ${EARTH}`);
  return buf;
}

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

/*
  The tiles' handover frame, with the curve itself switched off.

  Everything else stays: the defocus is at full strength and the vignette is
  gated off, because those are what the frame will look like when the curve is
  applied to it. Fitting against a frame graded differently from the one the
  curve runs on produces a curve that corrects for the wrong thing.
*/
async function tilesFrame() {
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

  const b64 = await page.evaluate(async () => {
    const m = window.__m;
    for (let k = 0; k < 500; k++) {
      m.place(0);
      m.update();
      m.render();
      const s = m.tiles.stats ?? {};
      if (k > 20 && !s.downloading && !s.parsing) break;
      await new Promise((z) => setTimeout(z, 25));
    }
    m.render();
    m.grade.uniforms.uMatch.value = 0;
    m.renderer.setRenderTarget(m.target);
    m.renderer.render(m.scene, m.camera);
    m.renderer.setRenderTarget(null);
    m.renderer.render(m.gradeScene, m.gradeCamera);
    return document.getElementById("c").toDataURL("image/png").split(",")[1];
  });
  await browser.close();

  const dir = await fs.mkdtemp(".match-");
  const png = path.join(dir, "t.png");
  const raw = path.join(dir, "t.raw");
  await fs.writeFile(png, Buffer.from(b64, "base64"));
  await run("ffmpeg", ["-v", "error", "-i", png, "-f", "rawvideo",
    "-pix_fmt", "rgb24", raw]);
  const buf = await fs.readFile(raw);
  await fs.rm(dir, { recursive: true, force: true });
  return buf;
}

const histogram = (buf, channel) => {
  const h = new Float64Array(256);
  for (let i = channel; i < buf.length; i += 3) h[buf[i]] += 1;
  let run = 0;
  const cdf = new Float64Array(256);
  const total = buf.length / 3;
  for (let v = 0; v < 256; v++) { run += h[v]; cdf[v] = run / total; }
  return cdf;
};

function curve(from, to) {
  // For each input level, the output level at the same rank.
  const map = new Float64Array(256);
  let j = 0;
  for (let v = 0; v < 256; v++) {
    while (j < 255 && to[j] < from[v]) j += 1;
    map[v] = j;
  }
  // Monotone, then smoothed, then sampled down to N entries. Ranks come from a
  // finite number of pixels and read straight off they wobble; a curve that is
  // not monotone puts darker pixels above lighter ones and bands the sky.
  for (let v = 1; v < 256; v++) map[v] = Math.max(map[v], map[v - 1]);
  const smooth = new Float64Array(256);
  const R = 9;
  for (let v = 0; v < 256; v++) {
    let sum = 0;
    let n = 0;
    for (let k = Math.max(0, v - R); k <= Math.min(255, v + R); k++) { sum += map[k]; n += 1; }
    smooth[v] = sum / n;
  }
  const out = [];
  for (let i = 0; i < N; i++) {
    out.push(Math.min(1, Math.max(0, smooth[Math.round((i / (N - 1)) * 255)] / 255)));
  }
  return out;
}

console.log("matching the tiles' handover frame to the globe's");
const [globe, tiles] = [await globeFrame(), await tilesFrame()];
const lut = {};
for (const [i, ch] of ["r", "g", "b"].entries()) {
  lut[ch] = curve(histogram(tiles, i), histogram(globe, i));
}

const show = (ch) => [0, 16, 32, 48, 63]
  .map((i) => `${Math.round((i / (N - 1)) * 255)}→${Math.round(lut[ch][i] * 255)}`).join("  ");
console.log(`  r  ${show("r")}`);
console.log(`  g  ${show("g")}`);
console.log(`  b  ${show("b")}`);

const body = ["r", "g", "b"]
  .map((ch) => `  ${ch}: [\n    ${lut[ch].map((v) => v.toFixed(4))
    .reduce((rows, v, i) => {
      if (i % 8 === 0) rows.push([]);
      rows[rows.length - 1].push(v);
      return rows;
    }, []).map((row) => row.join(", ")).join(",\n    ")},\n  ],`).join("\n");

await fs.writeFile(OUT, `/*
  The tone curve that puts the tiles' handover frame on the globe's.

  Generated by scripts/match-plate.mjs. Do not edit by hand: re-run it, and
  re-run it whenever either half of the handover changes.

  Per channel, ${N} entries, input level in and output level out, both 0 to 1.
  Fitted by histogram matching against two frames of the same place at the same
  altitude, which is the only condition under which that fit means anything.
*/
export const PLATE_LUT = {
${body}
};
`);
console.log(`\nwrote ${OUT}`);
