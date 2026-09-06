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

  ## It does not need the dev server

  It used to, and that cost three renders. The harness imported its modules over
  http://localhost:5173, so saving any file the page transitively imported tore
  down the execution context and the run died with "Execution context was
  destroyed" — or worse, survived and wrote a file of entirely black frames,
  which is the bad kind of failure because it looks like a finished render.

  Over ten minutes of rendering, not touching the repository is not a discipline
  anyone keeps. So the scene is bundled with esbuild into one self-contained
  script and inlined into the page: no imports, no server, no watcher. Edit
  whatever you like while this runs.

  The API key is baked in by the same bundle step, read from .env.local the way
  vite would read it. It never leaves this machine — the page is built here and
  fed to a headless browser here.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";
import { HANDOVER } from "../src/globe/handover.js";

/*
  Bundle the scene into one script with no imports left in it.

  esbuild resolves three and the tiles renderer out of node_modules and inlines
  them, and `define` substitutes the key the way vite's env replacement does, so
  manhattan.js needs no change to work in both places.
*/
async function bundleScene() {
  const env = await fs.readFile(".env.local", "utf8").catch(() => "");
  const key = /^VITE_GOOGLE_MAPS_KEY=(.*)$/m.exec(env)?.[1]?.trim();
  if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");

  const out = path.join(await fs.mkdtemp(".bundle-"), "scene.js");
  await new Promise((resolve, reject) => {
    const p = spawn("npx", [
      "esbuild", "scripts/scene-entry.js",
      "--bundle", "--format=iife", "--global-name=SCENE",
      `--define:import.meta.env.VITE_GOOGLE_MAPS_KEY=${JSON.stringify(key)}`,
      `--outfile=${out}`,
    ], { stdio: ["ignore", "ignore", "inherit"] });
    p.on("close", (c) => (c === 0 ? resolve() : reject(new Error(`esbuild ${c}`))));
  });
  const code = await fs.readFile(out, "utf8");
  await fs.rm(path.dirname(out), { recursive: true, force: true });
  return code;
}

const args = Object.fromEntries(
  process.argv.slice(2).join(" ").split("--").filter(Boolean)
    .map((s) => s.trim().split(/\s+/)).map(([k, v]) => [k, v ?? true]),
);
const WIDTH = Number(args.width ?? 1920);
const HEIGHT = Math.round((WIDTH * 9) / 16);
const FPS = Number(args.fps ?? 30);
const SECONDS = Number(args.seconds ?? HANDOVER.seconds);
/*
  Metres above the street at the end of the move, and the default now comes from
  the scene rather than from here.

  Eighty was set when the shot finished on a wide view over the East Village,
  and it stayed at eighty through a rebuild of the ending that took the stop
  down to seventeen — a fifth-floor window — because place() takes the height as
  an argument and this file kept passing its own. The scene's own default is
  the one that was measured against the block. Overridable, for probing.
*/
const END = args.end === undefined ? null : Number(args.end);
const OUT = args.out ?? "media/descent.mp4";

/*
  How many instants make up one frame, and how much of the frame the shutter is
  open for.

  A hundred and eighty degrees is the film convention — open for half the frame,
  closed for half — and it is what the eye reads as normal motion. Six samples
  is enough that the smear is continuous rather than a row of ghosts at the
  speeds this shot reaches; beyond that the difference stops being visible and
  the render time keeps going up.

  Nearly free, because the cost of a frame here is waiting for tiles and the
  tile set does not change across a sixtieth of a second.
*/
const SAMPLES = Number(args.samples ?? 6);
const SHUTTER = Number(args.shutter ?? 0.5);

/*
  Where the shot lands, and it has to be a building.

  East 6th near Avenue B. The first choice was two blocks north and turned out
  to be Tompkins Square Park: the descent spent its last two seconds falling
  towards trees and finished on a wide view over rooftops, which is a flyover
  ending rather than an arrival. This block is tenement stock — six storeys,
  brick, fire escapes on the street front — which is what the generated
  interior has to plausibly belong to.

  The East Village rather than the Financial District for the same reason. The
  towers downtown have no fire escapes and the brownstones further west have
  them at the back where no camera can see them.
*/
const PLACE = { lat: 40.72466, lon: -73.98096 };

const harness = ({ width, height, place, scene, ui }) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<!--
  Two canvases. The WebGL one is drawn to several times per output frame and is
  hidden; the 2D one holds their average and is the only thing photographed.
  See shoot() below for why.
-->
<canvas id="c" width="${width}" height="${height}" style="display:none"></canvas>
<canvas id="out" width="${width}" height="${height}"
        style="display:block;width:${width}px;height:${height}px"></canvas>
<script>window.__UI_IMAGE = ${JSON.stringify(ui)};<\/script>
<script>${scene}<\/script>
<script>
  window.state = { stage: "starting" };
  (async () => {
    try {
      const { THREE, Manhattan, MANHATTAN } = window.SCENE;
      MANHATTAN.lat = ${place.lat};
      MANHATTAN.lon = ${place.lon};
      const renderer = new THREE.WebGLRenderer({
        canvas: document.getElementById("c"), antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(${width}, ${height}, false);
      // For the room at the end. The tiles are unlit and cannot cast or
      // receive, so this costs nothing until there is a room in the scene.
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      // The far plane has to clear the planet at the top of the move, where the
      // camera is six hundred kilometres up and the horizon is thousands of
      // kilometres away. At 80,000 the Earth was behind it and the opening
      // frames came back empty.
      const camera = new THREE.PerspectiveCamera(42, ${width} / ${height}, 8, 40000000);
      const m = new Manhattan(renderer, camera);
      // The interface, for the laptop screen the shot ends on. Inlined rather
      // than fetched: the harness has no server of its own and this has to be
      // on the GPU before the frame that needs it.
      m.screenImage = window.__UI_IMAGE || null;
      // No cross-fade. Every frame here is fully settled before it is
      // photographed, so the plugin's dithered alpha is a stipple over
      // the whole city and nothing else. See Manhattan.load.
      await m.load({ fade: false });
      window.__m = m;

      /*
        Motion blur, by accumulation.

        A frame of film is not an instant, it is an exposure — a shutter open
        for half a frame, gathering everything that moved past in that time.
        Every frame here has been an instant, and that is a large part of why
        the footage reads as rendered rather than as filmed: a camera falling
        from orbit at this speed would have visible smear on every frame and
        this one has none. It is also why the melted photogrammetry near the
        ground is so conspicuous. Real footage moving that fast would not
        resolve the mush either.

        Done by sampling rather than by a post-process, because a post-process
        needs velocity vectors and the tiles arrive as plain meshes with no
        history. Sampling needs nothing: place the camera at several instants
        inside the shutter, render each, average them. It is what a shutter
        does.

        The expensive part of a frame here is waiting for tiles, not drawing,
        and the tile set does not change measurably across a sixtieth of a
        second — so the wait happens once and the sub-frames are nearly free.

        Averaged in floating point rather than by drawing each at one over n
        into a canvas: that is a weighted blend favouring whichever was drawn
        last, and at eight bits per channel the rounding shows as banding in a
        night sky.
      */
      const W = ${width}, H = ${height};
      const out = document.getElementById("out").getContext("2d", { willReadFrequently: true });
      const sum = new Float32Array(W * H * 4);
      const image = out.createImageData(W, H);
      const grab = document.createElement("canvas");
      grab.width = W; grab.height = H;
      const grabCtx = grab.getContext("2d", { willReadFrequently: true });

      window.__shoot = (t, end, samples, shutter) => {
        sum.fill(0);
        for (let k = 0; k < samples; k++) {
          // Spread across the shutter and centred on the frame's own time, so
          // the blur is symmetric and the frame is not displaced in time.
          const offset = samples === 1 ? 0 : ((k + 0.5) / samples - 0.5) * shutter;
          if (end === null) m.place(t + offset); else m.place(t + offset, end);
          m.render();
          grabCtx.drawImage(document.getElementById("c"), 0, 0);
          const px = grabCtx.getImageData(0, 0, W, H).data;
          for (let i = 0; i < sum.length; i++) sum[i] += px[i];
        }
        const data = image.data;
        for (let i = 0; i < sum.length; i += 4) {
          data[i] = sum[i] / samples;
          data[i + 1] = sum[i + 1] / samples;
          data[i + 2] = sum[i + 2] / samples;
          data[i + 3] = 255;
        }
        out.putImageData(image, 0, 0);
      };

      window.state = { stage: "ready" };
    } catch (e) {
      window.state = { stage: "failed", why: String(e).slice(0, 400) };
    }
  })();
<\/script></body></html>`;

async function main() {
  const scene = await bundleScene();
  const frames = Math.round(SECONDS * FPS);
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".descent-"));
  console.log(`${frames} frames at ${WIDTH}x${HEIGHT}, ${FPS}fps -> ${OUT}`);

  /*
  The interface, as a data URI, for the laptop screen the shot ends on.

  Inlined rather than served: the harness replaces the document to drop the
  module graph, and a relative path from there is a race against the frame that
  needs it. Missing is not fatal — the screen falls back to dark and the render
  still runs — because losing thirty minutes of tiles to a missing screenshot
  would be a poor trade.
*/
const ui = await fs.readFile("media/ui.png")
  .then((b) => `data:image/png;base64,${b.toString("base64")}`)
  .catch(() => {
    console.log("  no media/ui.png — run scripts/capture-ui.mjs; screen will be dark");
    return null;
  });

const browser = await puppeteer.launch({
    headless: true,
    args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
           "--enable-unsafe-swiftshader", "--hide-scrollbars"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    page.on("pageerror", (e) => console.log("  page:", String(e).slice(0, 160)));

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
    await page.setContent(
      harness({ width: WIDTH, height: HEIGHT, place: PLACE, scene, ui }),
      { waitUntil: "domcontentloaded" });
    // window.state is undefined until the script runs, and `undefined?.stage`
    // is also not "starting", so the obvious condition passes instantly and the
    // next line reads a property of nothing.
    await page.waitForFunction(
      "window.state !== undefined && window.state.stage !== 'starting'",
      { timeout: 90_000 });
    const state = await page.evaluate("window.state");
    if (state.stage !== "ready") throw new Error(state.why ?? "tiles did not load");
    console.log("  tileset open");

    // Rolling state for the out-of-line check below.

    let previous = null;

    const recent = [];


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
      /*
        Settle, photograph, and check the photograph against the ones before it.

        A frame occasionally comes out unlike its neighbours even after the wait
        — measured on a finished render, every frame in a stretch changed by
        about twenty and one changed by sixty-five, with the frames either side
        of it perfectly smooth. That is not the camera moving faster for a
        thirtieth of a second; it is one frame photographed with a different set
        of tiles in it, a tile arriving or being evicted at the wrong moment.

        It cannot be waited away, because from inside the loop the renderer
        looks finished both times. So the frame is measured instead: a small
        greyscale signature of each frame, compared against the one before, and
        against the running median of the last dozen. Wildly out of line means
        settle again and re-shoot, up to twice. Against a rolling median rather
        than a fixed number because the shot legitimately speeds up as it falls,
        by a lot, and a threshold that works at three thousand kilometres would
        fire on every frame near the ground.
      */
      const settle = async (t, end) => page.evaluate(async (t, end) => {
        const m = window.__m;
        /*
          Quiet for a run of passes, not quiet once.

          "k > 20 and nothing in flight" only means twenty passes have happened
          and this one happens to be quiet, so any lull after the twentieth ends
          the wait. The renderer has lulls: it reports nothing downloading and
          nothing parsing while it is still working out which tiles it wants,
          and a frame photographed in that gap comes back nearly empty. One did,
          at 53 m, with a single mesh in it — and the error target is now four
          rather than twenty, so there is far more to fetch per frame and far
          more room for a gap.

          Twelve consecutive quiet passes is three hundred milliseconds of
          nothing happening, which no lull has lasted. The counter resets the
          moment anything moves again.
        */
        let quiet = 0;
        for (let k = 0; k < 900; k++) {
          // null means "whatever the scene says", which is where the measured
          // ending lives. See END above.
          if (end === null) m.place(t); else m.place(t, end);
          m.update();
          m.render();
          const s = m.tiles.stats ?? {};
          quiet = (!s.downloading && !s.parsing) ? quiet + 1 : 0;
          if (k > 20 && quiet >= 12) break;
          await new Promise((r) => setTimeout(r, 25));
        }
        // A small grey signature of what was drawn, for the check below.
        const c = document.getElementById("c");
        const g = document.createElement("canvas");
        g.width = 48; g.height = 27;
        const x = g.getContext("2d");
        x.drawImage(c, 0, 0, 48, 27);
        const px = x.getImageData(0, 0, 48, 27).data;
        const out = [];
        for (let p = 0; p < px.length; p += 4) {
          out.push(0.2126 * px[p] + 0.7152 * px[p + 1] + 0.0722 * px[p + 2]);
        }
        return out;
      }, t, end);

      let signature = await settle(t, END);
      // The shutter, then the photograph. See window.__shoot.
      await page.evaluate(([t, end, n, shutter]) => window.__shoot(t, end, n, shutter),
                          [t, END, SAMPLES, SHUTTER / frames]);
      const step = (a, b) => {
        let sum = 0;
        for (let p = 0; p < a.length; p++) sum += Math.abs(a[p] - b[p]);
        return sum / a.length;
      };
      if (previous) {
        for (let attempt = 0; attempt < 2; attempt++) {
          const now = step(signature, previous);
          const sorted = [...recent].sort((a, b) => a - b);
          const typical = sorted.length >= 6 ? sorted[Math.floor(sorted.length / 2)] : null;
          if (typical === null || now < Math.max(2, typical * 2.5)) break;
          process.stdout.write(`  reshooting frame ${i} (${now.toFixed(0)} against ${typical.toFixed(0)})`);
          signature = await settle(t, END);
          await page.evaluate(([t, end, n, shutter]) => window.__shoot(t, end, n, shutter),
                              [t, END, SAMPLES, SHUTTER / frames]);
        }
        recent.push(step(signature, previous));
        if (recent.length > 12) recent.shift();
      }
      previous = signature;

      const shot = await page.screenshot({ type: "png", optimizeForSpeed: true,
                                          clip: { x: 0, y: 0, width: WIDTH, height: HEIGHT } });
      await fs.writeFile(path.join(dir, `f${String(i).padStart(5, "0")}.png`), shot);
      if (i % 20 === 0 || i === frames - 1) process.stdout.write(`  frame ${i}/${frames}`);
    }
    console.log("");

    /*
      Where the laptop screen is in the last frame, as fractions of it.

      The clip ends on a laptop that already has the page on its screen, and the
      handoff grows that rectangle until it fills the viewport — so the real
      interface arrives exactly where the picture of it already was. Nothing has
      to be matched by eye, and nothing has to be typed into the CSS and kept in
      step with a shot that gets re-rendered: the four corners are projected
      through the camera that took the frame, which is the only thing that knows.
    */
    const screen = await page.evaluate(() => {
      const { THREE } = window.SCENE;
      const m = window.__m;
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
      // NDC is -1..1 with y up; the page thinks in 0..1 with y down.
      return {
        x: +((minX + maxX) / 2 * 0.5 + 0.5).toFixed(4),
        y: +(-(minY + maxY) / 2 * 0.5 + 0.5).toFixed(4),
        w: +((maxX - minX) / 2).toFixed(4),
        h: +((maxY - minY) / 2).toFixed(4),
      };
    });
    if (screen) {
      await fs.writeFile("media/descent-end.json",
                         `${JSON.stringify(screen, null, 2)}\n`);
      console.log(`  screen fills ${(screen.w * 100).toFixed(0)}% of the frame, ` +
                  `centred at ${(screen.x * 100).toFixed(0)}%, ${(screen.y * 100).toFixed(0)}%`);
    }

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
