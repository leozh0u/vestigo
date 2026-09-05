/*
  A few lines of the field that are being written rather than sitting there.

  The painted tiles behind them are static on purpose: a hundred and sixteen
  live text nodes across four animated layers is what took this page to a frame
  a second, and that lesson stands. So the depth stays as painted images, and
  only a handful of lines on top are alive.

  Six of them. Enough that something is always moving somewhere in the frame,
  few enough that the cost is six text nodes changing, which is nothing.

  ## Why it types rather than fades

  A fade says an animation is running. Typing says something is working: a
  reading being taken, a line being entered, a result arriving. That is the
  register the whole page is aiming for, and it is the difference between
  decoration that resembles activity and decoration that depicts it.

  The lines come from the traces, so what gets typed is what the system
  actually emitted.
*/
const FALLBACK = [
  "solar_position  elev 34.2  az 118.7",
  "place_lookup  matched 1  spread 0 km",
  "geocell_classifier  p=0.44  cell 212",
  "country_metas  traffic left  -150",
  "resolves_to COUNTRY  max 0.86",
  "verify  confirmed  1.2 km",
  "consensus  3/3  spread 4 km",
  "admissibility 0.10  contradicted",
];

// Per line: where it sits, how large, how bright, and how fast it writes.
// Spread across the frame and across depths, so they do not read as a list.
/*
  Nine, and brighter than the first pass.

  At 0.09 to 0.16 opacity they were genuinely present and genuinely invisible:
  the DOM had six lines typing real coordinates and the screen showed nothing.
  The painted layers behind them can sit that low because they are a texture;
  something that is meant to be caught being written has to be legible enough
  to catch.

  Still well under the evidence log, so the eye goes to the globe first and
  finds these second, which is the order that matters.

  Positions avoid the middle band, where the globe is. Anything written across
  the planet competes with the thing it is decorating.
*/
const SLOTS = [
  { top: "10%", left: "4%", size: 0.74, alpha: 0.34, speed: 42 },
  { top: "22%", left: "66%", size: 0.62, alpha: 0.28, speed: 58 },
  { top: "38%", left: "2%", size: 0.56, alpha: 0.24, speed: 36 },
  { top: "56%", left: "74%", size: 0.68, alpha: 0.30, speed: 50 },
  { top: "72%", left: "3%", size: 0.52, alpha: 0.22, speed: 64 },
  { top: "6%", left: "40%", size: 0.58, alpha: 0.20, speed: 46 },
  { top: "86%", left: "62%", size: 0.60, alpha: 0.26, speed: 54 },
  { top: "44%", left: "78%", size: 0.54, alpha: 0.22, speed: 40 },
  { top: "64%", left: "6%", size: 0.64, alpha: 0.27, speed: 48 },
];

const HOLD = 2600;      // how long a finished line rests before it is removed
const ERASE = 18;       // milliseconds per character deleted; faster than typing

function seeded(seed) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

async function readLines() {
  try {
    const index = await (await fetch("/traces/index.json")).json();
    const out = new Set();
    for (const entry of index.slice(0, 4)) {
      const trace = await (await fetch(`/traces/${entry.file}`)).json();
      for (const step of trace.steps ?? []) {
        const text = (step.summary ?? "").replace(/\s+/g, " ").trim();
        if (text && text.length > 12 && text.length < 58) {
          out.add(`${step.source ?? step.kind}  ${text}`);
        }
        for (const c of step.candidates ?? []) {
          out.add(`${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}  ${c.score.toFixed(3)}`);
        }
      }
    }
    return out.size > 10 ? [...out] : FALLBACK;
  } catch {
    return FALLBACK;
  }
}

class Line {
  constructor(host, slot, lines, rand) {
    this.slot = slot;
    this.lines = lines;
    this.rand = rand;
    this.el = document.createElement("span");
    this.el.className = "typed";
    Object.assign(this.el.style, {
      top: slot.top,
      left: slot.left,
      fontSize: `${slot.size}rem`,
      opacity: String(slot.alpha),
    });
    host.append(this.el);
    // Staggered, or all six start together and the effect reads as a single
    // block appearing rather than as activity.
    this.timer = setTimeout(() => this.write(), rand() * 4000);
  }

  write() {
    this.text = this.lines[Math.floor(this.rand() * this.lines.length)];
    this.i = 0;
    this.tick();
  }

  tick() {
    if (this.stopped) return;
    this.i += 1;
    this.el.textContent = this.text.slice(0, this.i);
    if (this.i < this.text.length) {
      // Jittered, because a constant interval reads as a machine printing and
      // a varying one reads as something being worked out.
      const jitter = this.slot.speed * (0.6 + this.rand() * 0.9);
      this.timer = setTimeout(() => this.tick(), jitter);
    } else {
      this.timer = setTimeout(() => this.erase(), HOLD + this.rand() * 2000);
    }
  }

  erase() {
    if (this.stopped) return;
    this.i -= 2;
    this.el.textContent = this.text.slice(0, Math.max(0, this.i));
    this.timer = this.i > 0
      ? setTimeout(() => this.erase(), ERASE)
      : setTimeout(() => this.write(), 400 + this.rand() * 1600);
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
  }
}

export async function mountTyping() {
  // Anyone who has asked for less motion gets the painted tiles and nothing
  // that moves. Typing is the most insistent thing on the page.
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return [];
  const host = document.querySelector(".field-typed");
  if (!host) return [];

  const lines = await readLines();
  const rand = seeded(20260905);
  return SLOTS.map((slot) => new Line(host, slot, lines, rand));
}
