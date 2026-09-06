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
import { HANDOVER } from "../src/globe/handover.js";
import { beat } from "./render-intro.mjs";
import { RENDER_LIFT } from "../src/render-mode.js";

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
/*
  The beats, and the Earth beat is deliberately not one of them.

  media/earth.mp4 still exists and is still rendered by render-intro.mjs — it is
  the metal sphere becoming a night planet, and it is good. It is not in the
  intro because putting it there means a cut. The descent begins in space
  already; joining another shot of space to the front of it is two shots of the
  same subject with a dissolve between, which is the thing this whole rebuild
  removed.

  The zoom is one camera falling through one dataset from six hundred kilometres
  to a street. Nothing goes in front of it.
*/
/*
  The Earth beat is back, and it is back because it now ends where the descent
  begins rather than somewhere near it.

  Taking it out was the right call while the two shots disagreed about altitude,
  field of view, light and exposure — joining them then was a cut wearing a
  fade. All four are matched now, measured at the seam, so the dissolve has two
  frames of the same place at the same moment to work with and there is nothing
  for the eye to catch.
*/
const ORDER = [
  "media/earth.mp4",     // metal to a lit planet, then the dive
  "media/descent.mp4",   // three thousand kilometres to a street
  "media/room.mp4",      // generated; see src/opening/PROMPTS.md
];
const OUT = path.join(DIR, "intro.mp4");
/*
  Shorter than it was, because the reasons it was long have been fixed.

  0.45 was chosen when the two beats disagreed about everything and the
  dissolve was doing the work of hiding it. It is not hiding anything now:
  the geography lines up, the light matches and the colour is within two levels
  a channel across the join. What a long dissolve buys in that situation is
  only more frames of double image, because the two beats are zooming at
  slightly different rates and every overlapped frame shows both.

  Seven frames rather than thirteen, at the fastest part of the move.
*/
const FADE = HANDOVER.fade;            // seconds of overlap at each seam

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
  /*
    One beat is still a finished intro and has to be published like one.

    This used to copy the file and exit, which skipped the hashing and the
    manifest entirely — so the page fetched /opening/intro.json, got a 404,
    concluded there was no cinematic, and started on the globe with no way in.
    The ENTER panel simply stopped appearing, which is an odd thing to debug:
    nothing errors, and the page is behaving exactly as designed for the case
    where no intro exists.
  */
  /*
    Encoded, not copied.

    The beats are mastered at crf 18, which is right for a file that is an input
    to this join: quality lost there cannot be recovered. The output is
    different — every visitor downloads it before they see anything — and a
    straight copy shipped 36.6 MB against a whole site of 14. Same treatment as
    the multi-clip path, which is the only sane arrangement: what leaves this
    script is a web file however many beats went in.
  */
  await run("ffmpeg", [
    "-y", "-i", present[0],
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "27", "-preset", "slow",
    "-movflags", "+faststart", OUT,
  ]);
  // One beat, so the whole file is that beat: its length is the cut's length.
  const only = await duration(OUT);
  publish(only, present[0] === "media/earth.mp4" ? only : 0);
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

/*
  Every beat onto the same frame rate before anything is joined.

  xfade refuses two inputs at different rates -- "First input link main frame
  rate (60/1) do not match" -- and it refuses them by failing the whole filter
  graph, so what you get is an encoder that never opens and an ffmpeg error
  five lines from the actual cause. The Earth beat is rendered at 60 for a
  sphere that has no motion blur; the descent is 30 with a 180-degree shutter,
  which is what makes it look photographed.

  Sixty is the target rather than thirty, because upsampling duplicates frames
  and downsampling drops them. A duplicated frame is invisible and costs almost
  nothing to encode -- it is a P-frame with no residual. A dropped one is a
  judder in a shot that was built to be smooth.

  setsar as well, since a pixel aspect that disagrees between two inputs fails
  the same way and is even harder to see coming.
*/
const RATE = 60;
let filter = present
  .map((_, i) => `[${i}:v]fps=${RATE},setsar=1[v${i}];`)
  .join("");
let label = "v0";
let elapsed = lengths[0];
for (let i = 1; i < present.length; i++) {
  const next = `x${i}`;
  const offset = (elapsed - FADE).toFixed(3);
  filter += `[${label}][v${i}]xfade=transition=fade:duration=${FADE}:offset=${offset}[${next}];`;
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
  change its URL, and a browser that had the old one kept playing the old one: a
  new intro shipped, the site served it, and the person it was made for saw the
  previous cut and reported that nothing had changed. Twice.

  Hashing the filename makes a new video a new URL, which no cache can get
  wrong. The page cannot hardcode a hash, so it reads this manifest — one small
  JSON file that is allowed to be re-fetched, pointing at a video that never
  needs to be.
*/
/*
  `earthSeconds` is how long the Earth beat is, which the opening pose needs:
  beat() is a function of the fraction through that beat, so asking it for
  frame zero means telling it how long the beat was. Zero when the Earth beat
  is not in the cut at all, in which case the pose is left out entirely and the
  page falls back to a plain fade.
*/
function publish(seconds, earthSeconds) {
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
  /*
    The screen's rectangle travels with the video.

    Written by render-descent from the camera that took the last frame. The page
    grows the real interface out of it, so a re-render that moves the laptop
    moves the handoff with it and there is nothing to keep in step by hand.
  */
  /*
    From the room beat now, and from the descent before there was one.

    The descent used to end on a laptop, so it was the descent that knew where
    the screen was. It ends at a hundred and fifty metres over a street, so the
    rectangle belongs to whatever beat actually finishes the film — and the
    order matters, because media/descent-end.json may still be lying around
    from an older render and would quietly win.
  */
  let screen = null;
  for (const f of ["media/room-end.json", "media/descent-end.json"]) {
    try {
      screen = JSON.parse(fs.readFileSync(f, "utf8"));
      break;
    } catch { /* not this one */ }
  }
  if (!screen) {
    console.log("  no screen rectangle: the page will fade rather than grow");
  }

  /*
    And what the globe was doing in the screenshot on that screen.

    The page sets its own globe to this before the growth begins, so the still
    it is dissolving out of and the live page it is dissolving into are the same
    picture. Written by capture-ui.mjs.
  */
  let ui = null;
  try {
    ui = JSON.parse(fs.readFileSync("media/ui-state.json", "utf8"));
  } catch { /* older capture: the planet will simply be somewhere else */ }

  /*
    And the pose the clip opens on, so the page can already be in it.

    Pressing ENTER fades this file up over the live globe. Those were two
    different pictures of the same sphere — a different rotation, a different
    camera height, a different exposure, one of them turning — so the fade
    showed both at once, which reads worse than a straight cut because a cut at
    least only shows one wrong thing.

    beat(0) is the clip's first frame by definition, so it is asked rather than
    copied. The exposure carries render-mode's video lift, because that is
    applied to every frame of the file and the page has no reason to know it
    otherwise. The distance is in the render's own sixteen-by-nine frame; the
    page corrects it for its own window, where the video is object-fit cover.
  */
  let open = null;
  if (earthSeconds > 0) {
    const first = beat(0, earthSeconds);
    open = {
      rotY: Number(first.rotationY.toFixed(5)),
      rotX: Number(first.rotationX.toFixed(5)),
      distance: Number(first.cameraZ.toFixed(4)),
      lift: Number(first.cameraY.toFixed(4)),
      exposure: Number((RENDER_LIFT * first.exposure).toFixed(4)),
    };
  }

  fs.writeFileSync(path.join(DIR, "intro.json"),
                   `${JSON.stringify({ src: `/opening/${path.basename(hashed)}`,
                                       seconds: Number(seconds.toFixed(2)),
                                       open, screen, ui }, null, 2)}\n`);
  console.log(`wrote ${hashed}  (${seconds.toFixed(1)}s)`);
}

publish(elapsed,
        present[0] === "media/earth.mp4" ? lengths[0] : 0);
