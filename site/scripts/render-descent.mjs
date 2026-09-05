/*
  Render the descent: down through cloud into the East Village, ending level
  with a walk-up across a street.

    node scripts/render-descent.mjs                    # 1920x1080, 7s, 30fps
    node scripts/render-descent.mjs --seconds 8 --end 45

  Needs the dev server running (npm run dev) and ffmpeg on PATH.

  ## Why this cannot be a real-time recording

  The tiles stream. Every frame the camera moves, the renderer works out which
  tiles it now needs, asks Google for them and parses them, and until they have
  arrived the frame is a half-built city. Screen-capturing a live flythrough
  gives footage of a city assembling itself, which is the one thing that says
  "this is streaming" out loud.

  So each frame waits for `downloading` and `parsing` to reach zero before it is
  photographed. That makes the render slow and the footage correct — the same
  trade as the Earth beat, and for the same reason: nothing is waiting on this.

  ## Cost

  One root tileset request per run, which Google bills as one session. Their
  Enterprise SKUs include a thousand a month, so a run costs nothing and so do
  a hundred of them. Individual tile downloads are not billed. Worth stating
  because the opposite assumption — that a long flythrough costs per tile —
  would make this whole approach look reckless, and it would be.

  ## Do not edit anything while this runs

  The harness loads its modules through the dev server, so saving any file the
  page imports destroys the execution context mid-render and the run dies with
  "Execution context was destroyed". It has happened twice: once producing a
  file of entirely black frames, which is worse, because that one looked like a
  finished render.

  Commit, then render, then go and do something else.

  ## A self-contained page, deliberately

  Not the site. The dev server's hot reload destroys the execution context
  whenever a file changes, which during an eight-minute render is close to
  certain, and borrowing the page's renderer would mean a failure here could be
  the page's fault rather than the tileset's. This builds its own scene, so what
  it produces is about the tiles.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const args = Object.fromEntries(
  process.argv.slice(2).join(" ").split("--").filter(Boolean)
    .map((s) => s.trim().split(/\s+/)).map(([k, v]) => [k, v ?? true]),
);
const WIDTH = Number(args.width ?? 1920);
const HEIGHT = Math.round((WIDTH * 9) / 16);
const FPS = Number(args.fps ?? 30);
const SECONDS = Number(args.seconds ?? 11);
// Metres above the street at the end of the move. Higher than it sounds it
// should be, and the reason is in the harness below.
const END = Number(args.end ?? 80);
const OUT = args.out ?? "media/descent.mp4";

/*
  Where the shot lands.

  The East Village rather than the Financial District. The shot has to finish
  on a pre-war walk-up with a fire escape and a street under it, and those are
  tenement blocks: from among the towers downtown there is nothing of the kind
  in frame.
*/
const PLACE = { lat: 40.7264, lon: -73.9818 };

const harness = ({ width, height, place }) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${width}" height="${height}"
        style="display:block;width:${width}px;height:${height}px"></canvas>
<script type="module">
  import * as THREE from "/node_modules/three/build/three.module.js";
  import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
  MANHATTAN.lat = ${place.lat};
  MANHATTAN.lon = ${place.lon};

  window.state = { stage: "starting" };
  (async () => {
    try {
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${width}, ${height}, false);
      // Far enough for the sky dome at 60 km and the skyline behind it; near
      // enough that the depth buffer still has precision where the buildings
      // are, which the haze in the grade depends on.
      // The far plane has to clear the planet at the top of the move, where
      // the camera is six hundred kilometres up and the horizon is thousands of
      // kilometres away. At 80,000 the Earth was behind it and the opening
      // frames were empty.
      const camera = new THREE.PerspectiveCamera(38, ${width} / ${height}, 8, 40000000);
      const m = new Manhattan(renderer, camera);
      await m.load();
      window.__m = m;
      window.state = { stage: "ready" };
    } catch (e) {
      window.state = { stage: "failed", why: String(e).slice(0, 400) };
    }
  })();
<\/script></body></html>`;

async function main() {
  const frames = Math.round(SECONDS * FPS);
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".descent-"));
  console.log(`${frames} frames at ${WIDTH}x${HEIGHT}, ${FPS}fps -> ${OUT}`);

  const browser = await puppeteer.launch({
    headless: true,
    args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
           "--enable-unsafe-swiftshader", "--hide-scrollbars"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 160)));

    // Loaded through the dev server so the module graph and the API key both
    // resolve the way they do on the site.
    await page.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" })
      .catch(() => {});
    await page.setContent(harness({ width: WIDTH, height: HEIGHT, place: PLACE }),
                          { waitUntil: "networkidle0" });
    await page.waitForFunction("window.state?.stage !== 'starting'", { timeout: 60_000 });
    const state = await page.evaluate("window.state");
    if (state.stage !== "ready") throw new Error(state.why ?? "tiles did not load");
    console.log("  tileset open");

    for (let i = 0; i < frames; i++) {
      const t = i / (frames - 1);
      /*
        Settle, then photograph.

        `place` moves the camera, `update` tells the renderer what it now needs
        and starts the fetches, and the loop below spins until nothing is in
        flight. The cap exists because a frame that never settles must not stop
        the render: a slightly incomplete frame in the middle of a descent is
        recoverable, an eight-minute hang is not.
      */
      await page.evaluate(async (t, end) => {
        const m = window.__m;
        for (let k = 0; k < 600; k++) {
          m.place(t, end);
          m.update();
          m.render();
          const s = m.tiles.stats ?? {};
          // Twenty settled passes rather than six. At altitude the renderer
          // reports nothing in flight for a moment while it is still deciding
          // which tiles it wants, and a frame photographed in that gap came
          // back as an empty rectangle — one frame at 60 km did exactly that
          // in the altitude probe.
          if (k > 20 && !s.downloading && !s.parsing) break;
          await new Promise((r) => setTimeout(r, 25));
        }
      }, t, END);

      const shot = await page.screenshot({ type: "png", optimizeForSpeed: true });
      await fs.writeFile(path.join(dir, `f${String(i).padStart(5, "0")}.png`), shot);
      if (i % 20 === 0 || i === frames - 1) process.stdout.write(`  frame ${i}/${frames}`);
    }
    console.log("");

    await fs.mkdir(path.dirname(OUT), { recursive: true });
    await new Promise((resolve, reject) => {
      const ff = spawn("ffmpeg", [
        "-y", "-framerate", String(FPS),
        "-i", path.join(dir, "f%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        // 18 rather than the default. The gradient in the sky is the kind of
        // wide smooth ramp that banding shows up in first.
        "-crf", "18", "-preset", "slow",
        OUT,
      ], { stdio: ["ignore", "ignore", "inherit"] });
      ff.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}`))));
    });
    console.log(`wrote ${OUT}`);
  } finally {
    await browser.close();
    await fs.rm(dir, { recursive: true, force: true });
  }
}

await main();
