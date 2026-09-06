/*
  Is the intro actually good, measured rather than glanced at.

    node scripts/check-intro.mjs media/descent.mp4

  Four frames on a contact sheet will not catch a black stretch in the middle,
  a hitch in the camera, or the moment a level of detail arrives and the whole
  frame jumps. Every one of those has shipped in this project already, and each
  time it was found by somebody watching rather than by anything checking.

  So this samples every frame and reports the three failures that have actually
  happened:

  **Empty frames**, which is not the same as dark ones. Two renders came back
  black and both were read as a shading problem when the real cause was that no
  geometry had loaded at all. But this intro opens on a night planet, which is
  legitimately dark — seventy frames of it sit under any mean brightness that
  would have caught those renders.

  What separates them is contrast. A frame with nothing in it is uniform: mean
  near zero and no variation. A night Earth is the opposite, a scatter of very
  bright cities on black, so its standard deviation is high while its mean is
  low. Both conditions, or the check cannot tell "nothing rendered" from
  "night" — and a test that fires on correct output gets ignored, which is worse
  than not having it.

  **Discontinuities**, and the definition matters. The first version compared
  every frame's change against the median for the whole shot, which flagged the
  end of the descent: 18.5, 18.9, 19.3, 20.1, 20.7 — a smooth ramp, because a
  camera eighty metres up covers more of the frame per metre than one three
  thousand kilometres up. That is acceleration, not a discontinuity, and there
  was nothing to fix.

  A pop is a frame unlike *its own neighbours*, not one unlike the average of a
  shot that legitimately speeds up. So each step is compared against the local
  run of steps around it. A ramp passes however steep it gets; one frame out of
  line with the two either side does not.

  **A stalled camera.** The opposite failure. If two consecutive frames are
  nearly identical the move has stopped, which in a zoom that is supposed to be
  one continuous fall is as wrong as a jump.

  **A sag**, which is the stall's quiet version and is the one that shipped.

  The globe used to reach the handover on a smoothstep, and smoothstep has zero
  slope at both ends, so the dive arrived at three thousand kilometres having
  almost stopped. Frame to frame across the join: 2.9, falling to 0.75, then the
  tiles picking it up at 4.0 and holding. A five-fold step with the slowest
  frame of the whole intro immediately before it, which is read as a cut,
  because decelerating to nothing and then leaping back to speed is what a cut
  between two shots looks like.

  None of the three checks above saw it. It is not a jump: every individual step
  sits close to the two either side, and the JUMP test compares against exactly
  that. It is not a stall: 0.75 against a median of 4 is a fifth of the shot's
  speed, nowhere near the sixteenth that counts as stopped. And it is not
  darkness. Three tests, all passing, on the single worst frame in the file.

  So: a run of frames much slower than the runs on *both* sides of it. Both
  sides matters. A shot that starts slowly and speeds up is a shot that starts
  slowly, and there are legitimate quiet passages here — the sphere turning
  before the dive begins is one. A dip with faster motion before it and faster
  motion after it is not a passage, it is a hole.

  Exits non-zero if anything fails, so it can gate a publish.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const FILE = process.argv[2] ?? "media/descent.mp4";

// A frame is empty if it is both dim and flat. The failed renders measured a
// mean of 8 with almost no variation; the night Earth runs a mean of 13 to 21
// with a spread above 20, city lights against space being the highest-contrast
// thing in the shot.
const DARK = 22;
const FLAT = 8;
// How many times its *local* neighbourhood a single step may be before it
// counts as a pop. Against the local run rather than the whole shot, because a
// zoom accelerates by design.
const JUMP = 3.2;
// How many steps either side make up that neighbourhood.
const NEAR = 6;
// Below this fraction of the median, the picture has stopped moving.
const STALL = 0.06;
// A run this much slower than the runs on both sides of it is a sag. The one
// that shipped measured 0.36 and 0.22 of its neighbours; the fixed version
// measures 0.93 and 0.97, so there is a lot of room between the two.
const SAG = 0.45;
// Frames in a run, and how far out the runs it is compared against sit. Half a
// second either way at 30fps, which is long enough that a genuine change of
// pace does not look like a hole.
const RUN = 7;
const AWAY = 22;

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
  const spreads = [];
  const deltas = [];
  for (let i = 0; i < count; i++) {
    const frame = raw.subarray(i * size, (i + 1) * size);
    let sum = 0;
    for (const v of frame) sum += v;
    const mean = sum / size;
    means.push(mean);
    let variance = 0;
    for (const v of frame) variance += (v - mean) ** 2;
    spreads.push(Math.sqrt(variance / size));
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

  /*
    The blackout at the end is not a fault, and these tests all call it one.

    The descent finishes by mixing the frame down to near-black over about a
    second, deliberately: it is how the shot leaves the street and arrives
    indoors without a cut. To these tests that is a run of dim, flat frames
    that barely differ from each other, which is exactly the signature of a
    renderer that died -- the thing they exist to catch.

    So the tail is excluded rather than the tests being loosened. Loosening
    them would blind the checks to a genuinely dead render everywhere else in
    the shot, which has happened twice. A fixed 1.2 seconds is measured from
    the end and everything before it is judged as strictly as before.
  */
  const TAIL = Math.round(fps * 1.2);
  const inTail = (frame) => frame > count - TAIL;

  const dark = means.map((m, i) => [i, m, spreads[i]])
    .filter(([i, m, sd]) => m < DARK && sd < FLAT && !inTail(i));
  /*
    Each step against the run of steps around it.

    The neighbourhood excludes the step itself, or a large one drags up the
    very number it is being judged against and hides exactly the spike this is
    looking for.
  */
  const jumps = [];
  for (let i = 0; i < deltas.length; i++) {
    const lo = Math.max(0, i - NEAR);
    const hi = Math.min(deltas.length, i + NEAR + 1);
    let sum = 0;
    let n = 0;
    for (let k = lo; k < hi; k++) {
      if (k === i) continue;
      sum += deltas[k];
      n += 1;
    }
    const local = n ? sum / n : 0;
    if (local > 0.01 && deltas[i] > local * JUMP) jumps.push([i + 1, deltas[i], local]);
  }
  const stalls = deltas.map((d, i) => [i + 1, d])
    .filter(([i, d]) => d < median * STALL && !inTail(i));

  /*
    Sags. See the note at the top.

    Compared against the slower of the two sides, not the average of both, so
    a dip only counts when the shot is genuinely faster before it *and* after
    it. Reported once per sag rather than once per frame: a hole half a second
    wide is one fault, and printing it fifteen times buries everything else.
  */
  const mean = (from, to) => {
    let sum = 0;
    let n = 0;
    for (let k = Math.max(0, from); k < Math.min(deltas.length, to); k++) {
      sum += deltas[k];
      n += 1;
    }
    return n ? sum / n : 0;
  };
  const sags = [];
  for (let i = AWAY + RUN; i < deltas.length - AWAY - RUN; i++) {
    const here = mean(i - RUN, i + RUN + 1);
    const before = mean(i - AWAY - RUN, i - AWAY + RUN);
    const after = mean(i + AWAY - RUN, i + AWAY + RUN);
    const against = Math.min(before, after);
    if (against > 0.5 && here < against * SAG) {
      const last = sags[sags.length - 1];
      if (last && i - last[0] < RUN * 2) continue;
      sags.push([i, here, against]);
    }
  }

  console.log(`${FILE}`);
  console.log(`  ${count} frames, ${seconds.toFixed(2)}s at ${fps}fps, ` +
              `${stream.width}x${stream.height}, ` +
              `${(Number(meta.format.size) / 1e6).toFixed(1)} MB`);
  console.log(`  brightness ${Math.min(...means).toFixed(1)} to ` +
              `${Math.max(...means).toFixed(1)}, ` +
              `contrast ${Math.min(...spreads).toFixed(1)} to ` +
              `${Math.max(...spreads).toFixed(1)}, ` +
              `median step ${median.toFixed(2)}`);

  let bad = 0;
  if (dark.length) {
    bad += 1;
    console.log(`  EMPTY: ${dark.length} frames dim and flat, ` +
                `first at ${at(dark[0][0])} ` +
                `(mean ${dark[0][1].toFixed(1)}, spread ${dark[0][2].toFixed(1)})`);
  } else console.log("  nothing empty");

  if (jumps.length) {
    bad += 1;
    console.log(`  JUMPS: ${jumps.length} steps over ${JUMP}x the median`);
    for (const [i, d, local] of jumps.slice(0, 5)) {
      console.log(`    ${at(i)}  ${d.toFixed(1)} against a local ${local.toFixed(1)}`);
    }
  } else console.log(`  no discontinuities (${JUMP}x local)`);

  if (stalls.length) {
    bad += 1;
    console.log(`  STALLS: ${stalls.length} steps under ${STALL}x the median, ` +
                `first at ${at(stalls[0][0])}`);
  } else console.log("  never stops moving");

  if (sags.length) {
    bad += 1;
    console.log(`  SAGS: ${sags.length} run(s) under ${SAG}x the motion either side`);
    for (const [i, here, against] of sags.slice(0, 5)) {
      console.log(`    ${at(i)}  ${here.toFixed(1)} against ${against.toFixed(1)} either side`);
    }
  } else console.log(`  no sags (${SAG}x either side)`);

  process.exit(bad ? 1 : 0);
} finally {
  await fs.rm(dir, { recursive: true, force: true });
}
