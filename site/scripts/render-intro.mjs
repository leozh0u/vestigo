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
import { HANDOVER, fallHeight } from "../src/globe/handover.js";

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
  /*
    The spin, the world arriving, and then the dive that hands over.

    This beat used to stop in orbit and cross-dissolve into a separate descent,
    which is two shots and a fade. It does not stop any more. It keeps falling,
    and it falls to exactly where Google's tiles pick up: straight down over New
    York at three thousand kilometres, in daylight.

    Three things have to match at that instant or the join shows. The framing,
    which is what the dive is for. The light, which is what the sun swing is
    for. And the sharpness, which cannot match — Blue Marble is 7.4 km a pixel
    and the tiles are centimetres — but a soft frame dissolving into a sharp one
    at identical framing reads as detail arriving, which is exactly what it is
    and what happens every time anybody zooms in on a map.
  */
  const easeInOut = (x) => (x < 0.5 ? 4 * x ** 3 : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const easeOut = (x) => 1 - Math.pow(1 - x, 3);
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };

  /*
    Turn: the whole shot, easing out, ending with New York facing the camera.

    Longitude alone is not enough. The first version set only the spin and the
    shot ended over the Caribbean, because New York is at 40 degrees north and
    nothing was tilting the globe to bring it up to the centre of frame.
  */
  const spin = easeOut(Math.min(1, t / 0.62));
  const target = -(NYC.lon * Math.PI) / 180 - Math.PI / 2;
  const rotationY = -0.9 + (target + Math.PI * 2 - -0.9) * spin;
  /*
    The tilt has to reach the full latitude, and it used to stop at 62% of it.

    That damping is right for the live flight, where taking a polar answer
    literally puts the camera over the top of the sphere looking down an axis.
    It is wrong here for a simple arithmetic reason: New York is at 40.7 degrees
    north, 62% of that is 25 degrees, and 25 degrees north is Cuba. The dive
    ended over the Caribbean and the tiles were waiting eighteen hundred
    kilometres away.

    So it is damped early, where the globe is still a globe and a hard tilt
    reads as a lurch, and released over the dive, where the only thing that
    matters is that the camera arrives above the place it is aiming at.
  */
  const settle = smooth((t - 0.40) / 0.60);
  const tilt = 0.62 + 0.38 * settle;
  const rotationX = ((NYC.lat * Math.PI) / 180) * tilt * spin;

  // Growth: a short beat as metal, then alive. The metal establishes itself in
  // about a second and everything after that is dead time.
  const growth = t < 0.05 ? 0 : easeInOut(Math.min(1, (t - 0.05) / 0.40));

  /*
    The dive, over the last third, and it is where this beat now ends.

    Distances are Earth radii from the centre, because that is what the camera
    works in: the surface is 1, so three thousand kilometres up is 1.47. The
    fall is exponential for the same reason the descent's is — a constant ratio
    per second is what reads as a zoom rather than as a drop.
  */
  /*
    Later, shorter, and accelerating into the handover rather than easing out of
    the shot.

    smoothstep has zero slope at both ends, so the dive arrived at three
    thousand kilometres having slowed almost to a stop. Measured on the stitched
    file, frame to frame: the globe falls away from 2.9 to 0.75 over the second
    before the seam, and the tiles pick it up at 4.0 and hold there. A five-fold
    step, with the slowest frame of the whole intro sitting immediately before
    it.

    That is the seam. Not the dissolve, not the colour, not the framing — all of
    which were wrong too and are fixed. A continuous fall that decelerates to
    nothing and then leaps back to speed is read as two shots joined, because
    that is what a cut between two shots does. Nothing about a longer or shorter
    blend changes it.

    So the dive covers the same distance in less time and eases *in* only. x to
    the 2.2 has no slope at the start, where the planet is still forming and the
    spin is carrying the frame, and 2.2 times the average rate at the end, which
    is where it has to meet the tiles. It arrives at speed and hands over at
    speed.

    The distances are unchanged. Earth radii from the centre: the surface is 1,
    so three thousand kilometres up is 1.47, which is where the descent begins.
  */
  /*
    The dive ends where the tiles begin, and then runs their curve.

    Two separate things. The first is the dive proper, which covers three and a
    half Earth radii down to three thousand kilometres and eases in only, so it
    arrives at speed instead of coasting to a halt. The second is the last
    quarter second, which is the part the dissolve overlaps.

    That tail exists because of what a dissolve actually does: it pairs the
    globe's frame at time T with the tiles' frame at T minus the offset. Ending
    the dive at the *end* of the beat meant those pairs were 3,645 km against
    3,000, then 3,427 against 2,656, then 3,000 against 2,084 — twenty-one per
    cent apart at the start of the blend and forty-four at the end. The two
    images never agreed on the size of anything, so every overlapped frame drew
    the coastline twice at two different scales, which is the picture appearing
    to jump.

    So the dive reaches three thousand kilometres at the moment the blend opens,
    and for the length of the blend the globe falls on the descent's own
    function out of handover.js. Not a curve fitted to it — the same one. Every
    paired frame is then the same place at the same size and the dissolve has
    nothing left to do but change which renderer is drawing it.
  */
  const HAND = 1 - HANDOVER.fade / SECONDS;
  const start = 0.30;
  /*
    1.12, not 1.5.

    The exponent sets how much faster than its own average the dive is moving
    when it hands over, and that has to equal the rate the tiles pick up at. The
    tiles' rate is set by the length of the descent, so lengthening the descent
    from nine seconds to twelve slowed their opening by a quarter and left the
    globe arriving a third too fast. Scaled to match.
  */
  const dive = Math.pow(clamp01((t - start) / (HAND - start)), 1.12);
  const FROM = 3.55;
  const TO = 1 + HANDOVER.top / 6371000;
  let cameraZ = Math.exp(Math.log(FROM) + (Math.log(TO) - Math.log(FROM)) * dive);
  if (t > HAND) {
    // Seconds past the handover, which is exactly how far into the descent the
    // tiles are at this frame. Earth radii from the centre, so the surface is 1.
    const into = (t - HAND) * SECONDS;
    cameraZ = 1 + fallHeight(into / HANDOVER.seconds) / 6371000;
  }
  // Straightens as it falls. The lift is what keeps the sphere off the bottom
  // of the frame early on and would be a tilt by the end, so it goes to zero.
  const cameraY = 0.18 * (1 - dive);

  /*
    The sun swings from behind the planet to behind the camera.

    It starts at SUN, which is where the site's own globe keeps it: behind and
    to the left, so the visible face is night and the cities carry the shot.
    By the end it is over the camera's shoulder and New York is in daylight,
    which is what the tiles are.

    Late, and quickly. Held at night for the first half so the beat that matters
    — metal becoming a lit planet — happens in the dark where it belongs, then
    moved over the dive so dawn arrives as the camera does.
  */
  /*
    The sun ends almost directly behind the camera.

    Not off to one side. At 1.47 radii the visible disc is large and a sun even
    slightly off-axis puts the terminator across it — the first version ended
    with a black wedge over the right third of the frame, which is a night sky
    to hand a daylight photograph. Directly behind the camera means the whole
    visible face is lit, which is what a satellite photograph of the middle of
    the day looks like and what the tiles are.
  */
  const dawn = smooth((t - 0.46) / 0.54);
  const sun = [
    -2.35 + (0.18 - -2.35) * dawn,
    0.62 + (0.14 - 0.62) * dawn,
    -1.85 + (3.20 - -1.85) * dawn,
  ];

  /*
    And it has to be exposed for daylight by the end.

    The globe's own curve takes exposure down as the world arrives, which is
    right for a night planet on a dark page and half a stop short of a lit one.
    Lifted over the same window as the dawn, so the two are the same event.
  */
  // 1.9, not 0.55. Measured: the last Earth frame came out at mean 25 and the
  // first tiles frame at 74, which is a jump of nearly two stops across a join
  // that is supposed to be invisible. The globe's own curve takes exposure down
  // as the world arrives — correct for a night planet on a dark page, and half
  // the brightness a lit one needs.
  const exposure = 1 + 1.9 * dawn;

  return { progress: growth, rotationY, rotationX, cameraZ, cameraY, sun, exposure };
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
