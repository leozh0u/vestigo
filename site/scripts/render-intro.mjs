/*
  Render the Earth beat of the intro to a video file.

  The page's own scene, driven frame by frame instead of by the clock. A frame
  that takes four seconds to produce is still one sixtieth of a second of
  footage, so the result is smooth by construction. Clunkiness is a real-time
  problem and this is not real time.

    node scripts/render-intro.mjs                 # 1920x1080, 12s, 60fps
    node scripts/render-intro.mjs --width 3840 --seconds 14

  Needs the dev server running (npm run dev) and ffmpeg on PATH.

  ## The beats

  The shot is scripted here rather than taken from a run, because this is an
  opening title and not an answer. It has to be the same every time and it has
  to end pointed at New York, so the clip that follows can pick the descent up
  from where this leaves it.
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
const HEIGHT = Math.round(WIDTH * 9 / 16);
const FPS = Number(args.fps ?? 60);
const SECONDS = Number(args.seconds ?? 12);
// Outside public/, because this is the raw beat that stitch-intro.mjs joins
// to the generated clips. Only the joined intro.mp4 is served.
const OUT = args.out ?? "media/earth.mp4";
const URL = args.url ?? "http://localhost:5173/?render";

// New York, which is where the next clip has to begin. The globe is rotated so
// the city faces the camera by the end, and the camera is closing on it, so a
// cut into a descent over Manhattan has somewhere to come from.
const NYC = { lat: 40.7128, lon: -74.006 };

const easeInOut = (t) => (t < 0.5 ? 4 * t ** 3 : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

/*
  Where everything is at a given moment, as a fraction of the whole shot.

  Three beats, overlapping on purpose. The world starts coming alive while it
  is still turning, and the camera starts closing before the growth finishes,
  so no two things start and stop together. Beats that line up read as a
  slideshow.
*/
function beat(t) {
  // Turn: the whole shot, easing out, ending with New York facing the camera.
  //
  // Longitude alone is not enough. The first version set only the spin and the
  // shot ended over the Caribbean, because New York is at 40 degrees north and
  // nothing was tilting the globe to bring it up to the centre of frame. Both
  // axes, or the target is on screen and in the wrong half of it.
  const spin = easeOut(Math.min(1, t / 0.80));
  const target = -(NYC.lon * Math.PI) / 180 - Math.PI / 2;
  const rotationY = -0.9 + (target + Math.PI * 2 - -0.9) * spin;
  // Damped, as in the live flight: taking a latitude literally tips the camera
  // towards looking down the pole, which reads as a diagram rather than a place.
  const rotationX = ((NYC.lat * Math.PI) / 180) * 0.62 * spin;

  // Growth: a short beat as metal, then alive.
  //
  // The hold was 14% of the shot and the transformation took 62%, which read
  // as a long wait followed by a slow change. Watching it back, the metal
  // establishes itself in about a second and everything after that is dead
  // time. Now it starts turning almost immediately and finishes sooner,
  // leaving the last third for the approach.
  const growth = t < 0.05 ? 0
    : easeInOut(Math.min(1, (t - 0.05) / 0.48));

  // Approach: still at first, then closing. Ends near enough that the frame is
  // most planet, which is where a descent can take over.
  const near = t < 0.42 ? 0 : easeInOut((t - 0.42) / 0.58);
  const cameraZ = 3.55 + (1.72 - 3.55) * near;
  // Drifting up as it closes, so the move has a direction and is not a
  // straight push down the lens.
  const cameraY = 0.18 + 0.10 * near;

  return { progress: growth, rotationY, rotationX, cameraZ, cameraY };
}

async function main() {
  const frames = Math.round(SECONDS * FPS);
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".render-"));
  console.log(`${frames} frames at ${WIDTH}x${HEIGHT}, ${FPS}fps -> ${OUT}`);

  const browser = await puppeteer.launch({
    headless: true,
    args: [
      "--use-gl=angle",
      "--use-angle=metal",
      "--enable-gpu",
      "--hide-scrollbars",
      // Software fallback is very slow but correct, and correctness is the
      // point here: nothing is waiting on this.
      "--enable-unsafe-swiftshader",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    page.on("console", (m) => { if (m.type() === "error") console.log("  page:", m.text().slice(0, 120)); });

    await page.goto(URL, { waitUntil: "networkidle0", timeout: 60_000 });
    await page.waitForFunction("window.vestigoRender !== undefined", { timeout: 30_000 });
    await page.evaluate((w, h) => window.vestigoRender.setup({ width: w, height: h }),
                        WIDTH, HEIGHT);

    // Every texture has to have arrived before the first frame, or the head of
    // the footage is a grey sphere. This is the classic way an offscreen
    // render comes out wrong, and it is invisible until you watch it back.
    await page.waitForFunction("window.vestigoRender.loaded()", { timeout: 60_000 });
    console.log("  textures loaded");

    for (let i = 0; i < frames; i++) {
      await page.evaluate((state) => {
        window.vestigoRender.set(state);
        window.vestigoRender.step(0);
      }, beat(i / (frames - 1)));

      const shot = await page.screenshot({ type: "png", optimizeForSpeed: true });
      await fs.writeFile(path.join(dir, `f${String(i).padStart(5, "0")}.png`), shot);
      if (i % 60 === 0) process.stdout.write(`\r  frame ${i}/${frames}`);
    }
    process.stdout.write(`\r  frame ${frames}/${frames}\n`);

    await fs.mkdir(path.dirname(OUT), { recursive: true });
    await encode(dir, OUT, FPS);
    console.log(`wrote ${OUT}`);
  } finally {
    await browser.close();
    await fs.rm(dir, { recursive: true, force: true });
  }
}

function encode(dir, out, fps) {
  return new Promise((resolve, reject) => {
    const ff = spawn("ffmpeg", [
      "-y", "-framerate", String(fps),
      "-i", path.join(dir, "f%05d.png"),
      // yuv420p and even dimensions, or Safari and QuickTime refuse it. This
      // is the single most common reason a rendered clip plays everywhere
      // except the one machine somebody is watching on.
      "-c:v", "libx264", "-pix_fmt", "yuv420p",
      "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
      "-crf", "17", "-preset", "slow",
      "-movflags", "+faststart",
      out,
    ], { stdio: ["ignore", "ignore", "pipe"] });
    let err = "";
    ff.stderr.on("data", (d) => { err += d; });
    ff.on("close", (code) => code === 0 ? resolve() : reject(new Error(err.slice(-600))));
  });
}

main().catch((e) => { console.error(e.message); process.exit(1); });
