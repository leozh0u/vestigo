/*
  Lay the six generated effects against the cut, as one audio bed.

    node scripts/sound-bed.mjs

  Reads media/sound/*.mp3, writes media/intro-audio.m4a at exactly the length of
  the picture. stitch-intro.mjs muxes it in before hashing, so the audio travels
  with the video under one immutable name and a cache can never serve the sound
  of a previous cut over the picture of this one.

  ## The one thing this is for

  Everything here exists to set up a single moment: at 14.3 s the camera crosses
  the window, and the roar of altitude has to stop dead. The wind ducks to
  nothing over a quarter of a second and what is left is a room with a bird in
  it. A hard drop from loud to quiet is the strongest arrival cue available and
  it is free, which is why the bed is built around it rather than around a tune.

  Nothing here is music. A score would sit on top of the picture; these are
  sounds the picture causes, so the ear places the camera rather than being
  accompanied.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const SOUND = "media/sound";
const OUT = "media/intro-audio.m4a";

/*
  Where the picture changes, in seconds, measured off the stitched file rather
  than assumed from the beat lengths.

  The Earth beat is 5 s, the descent 9.4 s and the room 4.2 s, joined with a
  0.1 s overlap at each seam. The cloud pass was found by walking mean frame
  brightness: it rises from 117 to 207 between 10.6 and 11.1 and falls away by
  11.3, which is the camera entering and leaving the deck.
*/
const SEAM_DESCENT = 5.0;
const CLOUD = 11.0;
const SEAM_ROOM = 14.3;
const END = 18.4;

/*
  One entry per clip: when it starts, how loud, and how it opens and closes.

  Levels are in dB and they are not guesses -- each was set against what the
  clip actually measured. `through` came back peaking at 0.0 dB, which is
  clipped, so it is pulled down hard rather than limited later, because a
  limiter flattens a transient and the transient is the entire point of that
  one. `room` came back at -55 dB mean, which is correct for room tone and
  far too quiet to survive a mix, so it is lifted.
*/
const LAYERS = [
  {
    // The sphere, under the opening. Gone before the dive, because by then
    // there is air and the metal is a planet.
    file: "sphere.mp3", at: 0, gain: -7,
    fadeIn: 0.4, outAt: 3.0, fadeOut: 1.8,
  },
  {
    /*
      The wind, and it starts before the fall does.

      At 2 s the camera is still in orbit and the planet is still forming, which
      is exactly why the bed opens there: weather that begins at the same instant
      as the descent reads as an effect being switched on. It arrives underneath
      the beat that precedes it and is already there when the dive starts.

      It ends on the seam, not after it. See the note at the top.
    */
    file: "descent.mp3", at: 1.2, gain: -4,
    fadeIn: 3.4, outAt: SEAM_ROOM - 0.05, fadeOut: 0.3,
  },
  {
    // On the deck, a little before the whiteout peaks, so the ear is inside the
    // cloud fractionally before the eye agrees. Sound leads picture; the other
    // way round reads as dubbing.
    file: "cloud.mp3", at: CLOUD - 0.15, gain: -5,
    fadeIn: 0.15, outAt: CLOUD + 1.4, fadeOut: 0.6,
  },
  {
    // The crossing. Placed so the compression lands on the seam rather than
    // after it.
    file: "through.mp3", at: SEAM_ROOM - 0.55, gain: -9,
    fadeIn: 0.05, outAt: SEAM_ROOM + 1.0, fadeOut: 0.8,
  },
  {
    // Inside. Up almost immediately, because the silence it replaces is the
    // effect and a slow fade would blunt it.
    file: "room.mp3", at: SEAM_ROOM + 0.05, gain: +12,
    fadeIn: 0.5, outAt: END - 0.5, fadeOut: 0.5,
  },
  {
    // The interface arriving. One tick, right at the end, so the last thing
    // heard is small and deliberate after nine seconds of weather.
    file: "tick.mp3", at: END - 0.35, gain: -8,
    fadeIn: 0.01, outAt: END - 0.1, fadeOut: 0.1,
  },
];

const run = (cmd, args) => new Promise((res, rej) => {
  const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
  let err = ""; p.stderr.on("data", (d) => { err += d; });
  p.on("close", (c) => (c === 0 ? res() : rej(new Error(err.slice(-700)))));
});

const present = [];
for (const l of LAYERS) {
  const file = path.join(SOUND, l.file);
  if (await fs.access(file).then(() => true, () => false)) present.push({ ...l, file });
  else console.log(`  missing ${l.file}, skipping`);
}
if (!present.length) {
  console.error("no clips in media/sound. Run scripts/make-sound.mjs first.");
  process.exit(1);
}

/*
  One filter chain per clip, then a single mix.

  `adelay` places it, `volume` sets the level, `afade` opens and closes it, and
  `apad` plus the mix's own duration keeps every input the length of the
  picture -- amix ends when its *shortest* input does unless told otherwise, and
  the first version of this produced four seconds of audio against eighteen of
  video for exactly that reason.
*/
const chains = present.map((l, i) => {
  const ms = Math.round(l.at * 1000);
  return `[${i}:a]aresample=48000,` +
         `adelay=${ms}|${ms},` +
         `volume=${l.gain}dB,` +
         `afade=t=in:st=${l.at.toFixed(2)}:d=${l.fadeIn},` +
         `afade=t=out:st=${l.outAt.toFixed(2)}:d=${l.fadeOut},` +
         `apad[a${i}]`;
});

/*
  A master trim over the whole bed, and it is not a taste knob.

  The first mix measured -24 dB RMS at its loudest, which is a foreground
  level: correct for something being listened to and wrong for weather under a
  title sequence, where the picture is the subject and the sound is the room it
  happens in. Nine decibels down puts the peak of the wind near -33 and the
  room tone under -50, which is present without asking for attention.

  Applied once on the sum rather than spread across six gains, so the balance
  between the layers -- which is the part that took measuring -- cannot drift
  when the overall level is changed.
*/
const MASTER = -9;

const mixed = present.map((_, i) => `[a${i}]`).join("");
const filter = [
  ...chains,
  `${mixed}amix=inputs=${present.length}:normalize=0:dropout_transition=0[m]`,
  // A limiter rather than a normaliser on the sum, so the transients keep their
  // shape and only the overs are caught.
  `[m]volume=${MASTER}dB,alimiter=limit=0.9:level=disabled,atrim=0:${END},asetpts=N/SR/TB[out]`,
].join(";");

await run("ffmpeg", [
  "-y",
  ...present.flatMap((l) => ["-i", l.file]),
  "-filter_complex", filter,
  "-map", "[out]",
  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
  OUT,
]);

const measured = await new Promise((done) => {
  const p = spawn("ffmpeg", ["-hide_banner", "-i", OUT, "-af", "volumedetect",
                             "-f", "null", "-"], { stdio: ["ignore", "ignore", "pipe"] });
  let err = ""; p.stderr.on("data", (d) => { err += d; });
  p.on("close", () => done(err));
});
console.log(`wrote ${OUT}`);
console.log(`  peak ${/max_volume: (-?[\d.]+)/.exec(measured)?.[1] ?? "?"} dB, ` +
            `mean ${/mean_volume: (-?[\d.]+)/.exec(measured)?.[1] ?? "?"} dB`);
