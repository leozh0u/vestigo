/*
  The intro's sound, generated from text.

    node scripts/make-sound.mjs            # all of them
    node scripts/make-sound.mjs descent    # just one, to iterate

  Eighteen seconds of falling through the sky in silence is the most obvious
  thing still missing from the intro, and it is the cheapest to fix. Six clips
  cover it.

  ## Why these six and not a single piece of music

  A score would sit on top of the picture. What the shot needs is the opposite:
  sound that is *caused* by what is happening, so the ear believes the camera is
  somewhere. The one that matters most is `through` — the moment the roar of
  altitude stops dead and becomes a small warm room. A cut from loud to quiet is
  the strongest arrival cue there is, and it costs nothing to produce.

  Each clip is written to media/sound/ and reported with its measured duration
  and peak level, because the two ways a generated effect comes back wrong are
  silent and clipped, and both are invisible until something is mixed.
*/
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

const OUT = path.resolve("media/sound");
const API = "https://api.elevenlabs.io/v1/sound-generation";

/*
  Durations are the shot's, not round numbers.

  The descent bed runs 20 s against a 9.4 s beat because it is laid in ahead of
  the cut and rides under the tail of the Earth beat: the wind should already be
  building while the planet is still forming, or it arrives as an effect being
  switched on.

  `influence` is how literally the model takes the words. High for the specific
  one-shots, where a described event is the whole point, and lower for the beds,
  where over-adherence produces a loop of the same gust rather than weather.
*/
const CLIPS = {
  sphere: {
    seconds: 5,
    influence: 0.45,
    text: "A large machined metal sphere rotating slowly in a vacuum, deep " +
          "resonant hum with a faint metallic shimmer, no reverb tail, clean and cold",
  },
  descent: {
    seconds: 20,
    influence: 0.35,
    text: "Continuous high-altitude air rush, starting as a distant thin whisper " +
          "and building steadily over twenty seconds into a heavy roaring wind, " +
          "deep sub-bass rising underneath, no music, no impacts",
  },
  cloud: {
    seconds: 3,
    influence: 0.6,
    text: "Passing through a dense cloud layer, the wind suddenly muffled and " +
          "dulled for a moment then opening out again, soft and wet",
  },
  through: {
    seconds: 3,
    influence: 0.7,
    text: "A fast whoosh passing close by a hard surface, air compressing for an " +
          "instant then releasing into a small enclosed quiet space",
  },
  room: {
    seconds: 8,
    influence: 0.3,
    text: "Quiet interior room tone in a small apartment, faint distant traffic " +
          "far below through a window, a single bird, almost silent, warm",
  },
  tick: {
    seconds: 1,
    influence: 0.75,
    text: "One soft low electronic tick, single, clean, no reverb",
  },
};

/*
  The key lives outside the site, next to the other secrets, and is never
  printed. site/.env.local holds the Maps key because Vite has to inline it at
  build time; this one is only ever used by this script, so it sits at the
  repository root where nothing bundles it by accident.
*/
async function key() {
  for (const p of ["../.env.local", ".env.local"]) {
    const text = await fs.readFile(p, "utf8").catch(() => "");
    const found = /^ELEVENLABS_API_KEY=(.*)$/m.exec(text)?.[1]?.trim();
    if (found) return found;
  }
  throw new Error("no ELEVENLABS_API_KEY in .env.local");
}

/* Measured, not assumed. A clip that came back silent or clipped is the whole
   failure mode here and neither shows up in a file listing. */
const probe = (file) => new Promise((done) => {
  const p = spawn("ffprobe", ["-v", "error", "-hide_banner",
    "-show_entries", "format=duration", "-of", "csv=p=0", file], { stdio: ["ignore", "pipe", "ignore"] });
  let out = ""; p.stdout.on("data", (d) => { out += d; });
  p.on("close", () => done(Number(out.trim())));
});

const level = (file) => new Promise((done) => {
  // Not -v error. volumedetect reports at info level, so quieting ffmpeg
  // quiets the measurement too and every clip comes back "?" -- which reads
  // exactly like a silent file, the thing this exists to catch.
  const p = spawn("ffmpeg", ["-hide_banner", "-i", file, "-af", "volumedetect",
                             "-f", "null", "-"], { stdio: ["ignore", "ignore", "pipe"] });
  let err = ""; p.stderr.on("data", (d) => { err += d; });
  p.on("close", () => done({
    peak: /max_volume: (-?[\d.]+) dB/.exec(err)?.[1] ?? "?",
    mean: /mean_volume: (-?[\d.]+) dB/.exec(err)?.[1] ?? "?",
  }));
});

const wanted = process.argv.slice(2);
const names = wanted.length ? wanted : Object.keys(CLIPS);

const xi = await key();
await fs.mkdir(OUT, { recursive: true });

for (const name of names) {
  const clip = CLIPS[name];
  if (!clip) { console.log(`  no clip named ${name}`); continue; }
  const res = await fetch(API, {
    method: "POST",
    headers: { "xi-api-key": xi, "content-type": "application/json" },
    body: JSON.stringify({
      text: clip.text,
      duration_seconds: clip.seconds,
      prompt_influence: clip.influence,
    }),
  });
  if (!res.ok) {
    console.log(`  ${name}: ${res.status} ${(await res.text()).slice(0, 160)}`);
    continue;
  }
  const file = path.join(OUT, `${name}.mp3`);
  await fs.writeFile(file, Buffer.from(await res.arrayBuffer()));
  const [secs, lvl] = await Promise.all([probe(file), level(file)]);
  console.log(`  ${name.padEnd(8)} ${secs.toFixed(1)}s  peak ${String(lvl.peak).padStart(6)} dB  ` +
              `mean ${String(lvl.mean).padStart(6)} dB`);
}

console.log(`\n${OUT}`);
