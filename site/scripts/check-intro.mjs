/*
  Is the intro actually good, measured rather than glanced at.

    node scripts/check-intro.mjs media/descent.mp4

  Four frames on a contact sheet will not catch a black stretch in the middle,
  a hitch in the camera, or the moment a level of detail arrives and the whole
  frame jumps. Every one of those has shipped in this project already, and each
  time it was found by somebody watching rather than by anything checking.

  So this samples every frame and reports the three failures that have actually
  happened:

  **Dark frames.** Two renders came back entirely black and both were read as a
  shading problem when the real cause was that no geometry had loaded at all.
  A frame darker than the floor is called out with its timestamp.

  **Discontinuities.** A continuous zoom should change gradually. Consecutive
  frames are compared, and a jump far above the run of the shot means something
  popped: a tile set arriving, a camera stepping, an exposure changing its mind.

  **A stalled camera.** The opposite failure. If two consecutive frames are
  nearly identical the move has stopped, which in a zoom that is supposed to be
  one continuous fall is as wrong as a jump.

  Exits non-zero if anything fails, so it can gate a publish.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const FILE = process.argv[2] ?? "media/descent.mp4";

// Mean brightness out of 255. Below this a frame has essentially nothing in it;
// the black renders measured 8 and the good ones run 70 to 100.
const DARK = 22;
// How many times the median frame-to-frame change a single step may be before
// it counts as a jump rather than as motion.
const JUMP = 4.5;
// Below this fraction of the median, the picture has stopped moving.
const STALL = 0.06;

const run = (cmd, args) => new Promise((res, rej) => {
  const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
  let out = "";
  let err = "";
  p.stdout.on("data", (d) => { out += d; });
  p.stderr.on("data", (d) => { err += d; });
  p.on("close", (c) => (c === 0 ? res(out) : rej(new Error(err.slice(-400)))));
});

const meta = JSON.parse(await run("ffprobe", [
  "-v", "error", "-select_streams", "v:0",
  "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
  "-show_entries", "format=duration,size", "-of", "json", FILE,
]));
const stream = meta.streams[0];
const fps = eval(stream.r_frame_rate);          // "30/1"
const seconds = Number(meta.format.duration);

/*
  Decoded small and grey.

  The questions are "is it black" and "how much did it change", and both are
  answered at 64x36. Decoding 330 frames at full size to ask them would take
  longer than the render did.
*/
const dir = await fs.mkdtemp(".check-");
try {
  await run("ffmpeg", [
    "-v", "error", "-i", FILE,
    "-vf", "scale=64:36,format=gray",
    "-f", "rawvideo", "-pix_fmt", "gray",
    path.join(dir, "frames.raw"),
  ]);
  const raw = await fs.readFile(path.join(dir, "frames.raw"));
  const size = 64 * 36;
  const count = Math.floor(raw.length / size);

  const means = [];
  const deltas = [];
  for (let i = 0; i < count; i++) {
    const frame = raw.subarray(i * size, (i + 1) * size);
    let sum = 0;
    for (const v of frame) sum += v;
    means.push(sum / size);
    if (i > 0) {
      const prev = raw.subarray((i - 1) * size, i * size);
      let diff = 0;
      for (let p = 0; p < size; p++) diff += Math.abs(frame[p] - prev[p]);
      deltas.push(diff / size);
    }
  }

  const sorted = [...deltas].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] || 0;
  const at = (i) => `${(i / fps).toFixed(2)}s (frame ${i})`;

  const dark = means.map((m, i) => [i, m]).filter(([, m]) => m < DARK);
  const jumps = deltas.map((d, i) => [i + 1, d])
    .filter(([, d]) => d > median * JUMP);
  const stalls = deltas.map((d, i) => [i + 1, d])
    .filter(([, d]) => d < median * STALL);

  console.log(`${FILE}`);
  console.log(`  ${count} frames, ${seconds.toFixed(2)}s at ${fps}fps, ` +
              `${stream.width}x${stream.height}, ` +
              `${(Number(meta.format.size) / 1e6).toFixed(1)} MB`);
  console.log(`  brightness ${Math.min(...means).toFixed(1)} to ` +
              `${Math.max(...means).toFixed(1)}, median step ${median.toFixed(2)}`);

  let bad = 0;
  if (dark.length) {
    bad += 1;
    console.log(`  DARK: ${dark.length} frames under ${DARK}, ` +
                `first at ${at(dark[0][0])} (${dark[0][1].toFixed(1)})`);
  } else console.log("  no dark frames");

  if (jumps.length) {
    bad += 1;
    console.log(`  JUMPS: ${jumps.length} steps over ${JUMP}x the median`);
    for (const [i, d] of jumps.slice(0, 5)) {
      console.log(`    ${at(i)}  ${d.toFixed(1)} vs ${median.toFixed(2)}`);
    }
  } else console.log("  no discontinuities");

  if (stalls.length) {
    bad += 1;
    console.log(`  STALLS: ${stalls.length} steps under ${STALL}x the median, ` +
                `first at ${at(stalls[0][0])}`);
  } else console.log("  never stops moving");

  process.exit(bad ? 1 : 0);
} finally {
  await fs.rm(dir, { recursive: true, force: true });
}
