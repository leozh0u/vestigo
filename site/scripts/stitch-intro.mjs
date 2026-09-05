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
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const DIR = "public/opening";
/*
  The beats, in order, and where each one comes from.

  The first two are rendered by this repository and live outside public/,
  because they are inputs to this join rather than things the site serves. The
  third is generated elsewhere and dropped into media/ by hand.

  Missing files are skipped, so this works with one beat or with all three and
  the page always has something to play.
*/
// Relative to the site root, which is where this script is run from. They were
// relative to DIR, which resolved public/opening/../media — a directory that
// does not exist — so every beat was silently "missing" and the script reported
// an empty opening directory that was not empty.
const ORDER = [
  "media/earth.mp4",     // the planet, from scripts/render-intro.mjs
  "media/descent.mp4",   // Manhattan, from scripts/render-descent.mjs
  "media/room.mp4",      // generated; see src/opening/PROMPTS.md
];
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

const present = ORDER.filter((f) => fs.existsSync(f));

if (!present.length) {
  console.error("no beats rendered yet. Start with:\n" +
                "  node scripts/render-intro.mjs");
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
  /*
    27, not 18.

    18 is a mastering setting and belongs on the individual beats, where the
    file is an input to this join and quality lost there cannot be recovered.
    The output is different: it is downloaded by every visitor before they see
    anything, and at 18 the twelve seconds came to 19 MB against a whole site
    of 16.

    27 brings it to 5 MB. The footage is dark, slow and grainy, which is the
    kind that survives compression best — most of the bitrate at 18 was being
    spent on noise in a night sky.
  */
  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "27", "-preset", "slow",
  "-movflags", "+faststart",
  OUT,
]);

/*
  Name the file after its contents, and write the name where the page can read
  it.

  The intro lived at a fixed /opening/intro.mp4. Replacing it therefore did not
  change its URL, and a browser that had the old one kept playing the old one:
  a new intro shipped, the site served it, and the person it was made for saw
  the previous cut and reported that nothing had changed. Twice.

  Hashing the filename makes a new video a new URL, which no cache can get
  wrong. The page cannot hardcode a hash, so it reads this manifest — one small
  JSON file that is allowed to be re-fetched, pointing at a video that never
  needs to be.
*/
const digest = crypto.createHash("sha256")
  .update(fs.readFileSync(OUT)).digest("hex").slice(0, 10);
const hashed = path.join(DIR, `intro-${digest}.mp4`);

// Anything from a previous build, gone. Otherwise every intro ever stitched
// accumulates in public/ and ships with the site.
for (const f of fs.readdirSync(DIR)) {
  if (/^intro-[0-9a-f]{10}\.mp4$/.test(f) && path.join(DIR, f) !== hashed) {
    fs.unlinkSync(path.join(DIR, f));
  }
}
fs.renameSync(OUT, hashed);
fs.writeFileSync(path.join(DIR, "intro.json"),
                 `${JSON.stringify({ src: `/opening/${path.basename(hashed)}`,
                                     seconds: Number(elapsed.toFixed(2)) }, null, 2)}\n`);

console.log(`wrote ${hashed}  (${elapsed.toFixed(1)}s)`);
