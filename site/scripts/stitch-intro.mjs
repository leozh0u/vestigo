/*
  Join the Earth beat and the generated clips into one intro.

    node scripts/stitch-intro.mjs

  Reads whatever exists in public/opening and skips what does not, so the
  pipeline works with one clip or with all four and the page always has
  something to play.

  ## Why the seams are dissolves and not cuts

  A hard cut between a rendered globe and a generated aerial will read as a
  cut, because nothing about the two shots matches: grain, colour and lens are
  all different. A short dissolve at a moment when one object fills the frame
  gives the eye nothing to compare, and the join stops being visible.

  The clips are ordered so each seam lands on such a moment: cloud, then the
  face of a building, then a window.
*/
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const DIR = "public/opening";
const ORDER = ["../media/earth.mp4", "clip1.mp4", "clip2.mp4", "clip3.mp4"];
const OUT = path.join(DIR, "intro.mp4");
const FADE = 0.45;            // seconds of overlap at each seam

const run = (cmd, args) => new Promise((res, rej) => {
  const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
  let out = "", err = "";
  p.stdout.on("data", (d) => { out += d; });
  p.stderr.on("data", (d) => { err += d; });
  p.on("close", (c) => (c === 0 ? res(out) : rej(new Error(err.slice(-500)))));
});

const duration = async (file) => Number(await run("ffprobe", [
  "-v", "error", "-show_entries", "format=duration",
  "-of", "default=noprint_wrappers=1:nokey=1", file,
]));

const present = ORDER.map((f) => path.join(DIR, f)).filter((f) => fs.existsSync(f));

if (!present.length) {
  console.error(`nothing in ${DIR}. Render the Earth beat first:\n` +
                `  node scripts/render-intro.mjs`);
  process.exit(1);
}

console.log(`joining ${present.length}: ${present.map((f) => path.basename(f)).join(", ")}`);

if (present.length === 1) {
  fs.copyFileSync(present[0], OUT);
  console.log(`only one clip, copied to ${OUT}`);
  process.exit(0);
}

const lengths = [];
for (const f of present) lengths.push(await duration(f));

/*
  xfade chains pairwise, and each link's offset is measured from the start of
  everything joined so far minus the fades already spent. Getting this wrong is
  the usual reason a stitched video jumps: the offsets drift and the last clip
  starts before the one before it has finished.
*/
const inputs = present.flatMap((f) => ["-i", f]);
let filter = "";
let label = "0:v";
let elapsed = lengths[0];
for (let i = 1; i < present.length; i++) {
  const next = `x${i}`;
  const offset = (elapsed - FADE).toFixed(3);
  filter += `[${label}][${i}:v]xfade=transition=fade:duration=${FADE}:offset=${offset}[${next}];`;
  label = next;
  elapsed = elapsed - FADE + lengths[i];
}
filter = filter.replace(/;$/, "");

await run("ffmpeg", [
  "-y", ...inputs,
  "-filter_complex", filter,
  "-map", `[${label}]`,
  // Same encoding rules as the render: yuv420p and even dimensions, or Safari
  // and QuickTime refuse the file.
  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
  "-movflags", "+faststart",
  OUT,
]);

console.log(`wrote ${OUT}  (${elapsed.toFixed(1)}s)`);
