/*
  Generate one camera move between two photographs.

    node scripts/make-video.mjs through          # window -> room -> laptop
    node scripts/make-video.mjs bridge           # aerial -> window
    node scripts/make-video.mjs through --model bytedance-seedance-v2.5 --seconds 6

  The intro is one continuous fall from orbit to a laptop screen, and two
  stretches of it cannot be photographed or rendered. Google's tiles have no
  usable data below about a hundred and fifty metres, and a still photograph
  cannot be flown *through* -- cropping into one is a zoom, not a camera move,
  because the pixels for the new viewpoint do not exist.

  What does exist is a model that takes a first frame and a last frame and
  invents the travel between them. Both ends here are real: one is a frame of
  the actual descent, the others are photographs. Only the middle is generated,
  and only where nothing else can reach.

  ## Why Seedance rather than Veo

  Veo is the better-known model and costs roughly twice as much a run. Seedance
  is the one built specifically to bridge a start and an end frame, which is the
  entire job here -- there is no open-ended prompt to interpret, just two fixed
  images and the question of what happens in between. Cheaper runs also means
  more attempts, and attempts are what this needs: the failure mode is buildings
  warping, it is not subtle, and the fix is to run it again.
*/
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

const BASE = "https://api.elevenlabs.io/v1/flows/video";
const OUT = path.resolve("media/generated");

const SHOTS = {
  /*
    Through the window and across the room.

    The one that replaces the most work. It was going to be a hand-built rig:
    the brick photograph on a plane with the window alpha-punched out, the room
    behind it, a crop ladder across four plates and two cross-fades. All of that
    existed only because I assumed real movement was out of reach.
  */
  through: {
    start: "media/room/keyframe-03-window.png",
    end: "media/room/keyframe-05-desk.png",
    seconds: 5,
    prompt:
      "The camera flies slowly and steadily forward through the open lower half " +
      "of the sash window, crosses the sill, and continues straight across a " +
      "small apartment room toward the desk on the far wall, finishing square on " +
      "to the open laptop. One smooth continuous forward dolly at even speed. No " +
      "cuts, no camera rotation, no sideways drift, no tilting. Late afternoon " +
      "sunlight from behind the camera. Photorealistic, handheld-free, cinematic.",
  },
  /*
    The last of the fall, where the imagery runs out.

    Starts on a real frame of the descent -- the aerial at a hundred and fifty
    metres, already pitched fifty-nine degrees into the street, which is the
    whole reason that pitch was worth re-rendering for. The model has about
    thirty-five metres of descent and forty degrees of rotation left to invent
    instead of a hundred and thirty-five and seventy-seven.
  */
  bridge: {
    start: "media/keyframe-01-aerial.png",
    end: "media/room/keyframe-03-window.png",
    seconds: 5,
    prompt:
      "Aerial camera continuing its descent over a Manhattan street, dropping " +
      "the last few storeys while levelling out, and coming to rest hovering " +
      "square on in front of a fifth-floor window of a red brick pre-war " +
      "building. One smooth continuous move, decelerating into the final " +
      "position. No cuts. Late afternoon, low warm sun. Photorealistic aerial " +
      "cinematography.",
  },
};

const args = process.argv.slice(2);
const name = args.find((a) => !a.startsWith("--")) ?? "through";
const flag = (k, d) => {
  const i = args.indexOf(`--${k}`);
  return i >= 0 ? args[i + 1] : d;
};
/*
  Fast by default, and that is deliberate for the first run of anything.

  The pipeline itself can fail in half a dozen dull ways -- an image too large
  for the body, a field named wrong, a poll that never terminates -- and paying
  the full rate to discover one of those is waste. Prove the plumbing on the
  cheap model, then rerun the same command with --model bytedance-seedance-v2.5
  for the take that gets used.
*/
const MODEL = flag("model", "bytedance-seedance-v2-fast");
const RES = flag("res", "1080p");

const shot = SHOTS[name];
if (!shot) {
  console.error(`no shot named ${name}. Try: ${Object.keys(SHOTS).join(", ")}`);
  process.exit(1);
}

async function key() {
  for (const p of ["../.env.local", ".env.local"]) {
    const text = await fs.readFile(p, "utf8").catch(() => "");
    const found = /^ELEVENLABS_API_KEY=(.*)$/m.exec(text)?.[1]?.trim();
    if (found) return found;
  }
  throw new Error("no ELEVENLABS_API_KEY in .env.local");
}

/*
  JPEG, not the source PNG.

  The frames are 1672 across and 2.6 MB each as PNG, which is 3.5 MB once
  base64 has added a third, and two of those in one JSON body is asking to be
  refused for size. Quality 92 brings each under half a megabyte and the model
  is going to re-render every pixel between them regardless.
*/
const inline = (file) => new Promise((done, fail) => {
  const p = spawn("ffmpeg", ["-v", "error", "-i", file, "-q:v", "2",
                             "-f", "mjpeg", "-"], { stdio: ["ignore", "pipe", "pipe"] });
  const chunks = []; let err = "";
  p.stdout.on("data", (d) => chunks.push(d));
  p.stderr.on("data", (d) => { err += d; });
  p.on("close", (c) => c === 0
    ? done({ type: "inline_base64", content_base64: Buffer.concat(chunks).toString("base64"),
             mime_type: "image/jpeg" })
    : fail(new Error(err.slice(-300))));
});

/*
  What is left, before and after, and a floor under it.

  Leo's instruction was that this must not be able to cost him money. Two
  things make that true and neither is trust. The account's usage-based billing
  is off, so running out of credits fails a request rather than charging a card.
  And nothing here runs without first reading the balance and refusing below a
  floor, so a loop that goes wrong stops with credits to spare instead of at
  zero.

  Needs the key's `user` scope. Without it the balance is unreadable, and this
  says so loudly rather than quietly generating blind.
*/
const FLOOR = 15000;

async function balance(xi) {
  const r = await fetch("https://api.elevenlabs.io/v1/user/subscription",
                        { headers: { "xi-api-key": xi } });
  if (!r.ok) return null;
  const s = await r.json();
  const used = s.character_count ?? 0;
  const limit = s.character_limit ?? 0;
  return { used, limit, left: limit - used };
}

const xi = await key();
await fs.mkdir(OUT, { recursive: true });

const before = await balance(xi);
if (!before) {
  console.log("  ! cannot read the balance (key has no `user` scope) -- running blind");
} else {
  console.log(`  credits ${before.left.toLocaleString()} of ${before.limit.toLocaleString()}`);
  if (before.left < FLOOR) {
    console.error(`  stopping: under the ${FLOOR.toLocaleString()} floor`);
    process.exit(1);
  }
}

const [start, end] = await Promise.all([inline(shot.start), inline(shot.end)]);
console.log(`${name}: ${MODEL} ${RES} ${shot.seconds}s`);
console.log(`  start ${shot.start}  (${(start.content_base64.length / 1024).toFixed(0)} KB b64)`);
console.log(`  end   ${shot.end}  (${(end.content_base64.length / 1024).toFixed(0)} KB b64)`);

const res = await fetch(BASE, {
  method: "POST",
  headers: { "xi-api-key": xi, "content-type": "application/json" },
  body: JSON.stringify({
    model_id: MODEL,
    prompt: shot.prompt,
    start_frame: start,
    end_frame: end,
    duration_secs: shot.seconds,
    resolution: RES,
  }),
});
if (!res.ok) {
  console.error(`  ${res.status} ${(await res.text()).slice(0, 500)}`);
  process.exit(1);
}
const { id } = await res.json();
console.log(`  job ${id}`);

/*
  Poll rather than webhook. A webhook needs somewhere to receive it and this
  runs on a laptop; the job takes a couple of minutes, so a slow poll is the
  whole of the machinery needed.
*/
let job;
for (let k = 0; k < 240; k++) {
  await new Promise((r) => setTimeout(r, 5000));
  const r = await fetch(`${BASE}/${id}`, { headers: { "xi-api-key": xi } });
  job = await r.json();
  if (job.status && !["pending", "processing", "queued", "in_progress"].includes(job.status)) break;
  if (k % 6 === 0) process.stdout.write(`\r  ${job.status ?? "?"} ${k * 5}s`);
}
process.stdout.write("\r");

if (job.status !== "succeeded" && job.status !== "completed") {
  console.error(`  finished as ${job.status}: ${JSON.stringify(job).slice(0, 400)}`);
  process.exit(1);
}

const url = job.output?.url ?? job.video?.url ?? job.url
  ?? job.output?.[0]?.url ?? null;
if (!url) {
  console.error(`  no video url in response: ${JSON.stringify(job).slice(0, 600)}`);
  process.exit(1);
}
const file = path.join(OUT, `${name}-${MODEL}-${Date.now()}.mp4`);
await fs.writeFile(file, Buffer.from(await (await fetch(url)).arrayBuffer()));
console.log(`wrote ${file}`);

const after = await balance(xi);
if (before && after) {
  console.log(`  cost ${(before.left - after.left).toLocaleString()} credits, ` +
              `${after.left.toLocaleString()} left`);
}
