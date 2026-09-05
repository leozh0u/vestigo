/*
  The entry point. Wires the pieces together and owns the only frame loop.

  Read this file first: it is the one place that knows about all of them.
  globe/ knows nothing about traces, sequence/ knows nothing about three.js,
  and ui/ knows nothing about either. Keeping them apart is what makes any one
  of them replaceable.
*/
import { Globe } from "./globe/globe.js";
import { Opening } from "./opening/opening.js";
import { Flight } from "./globe/camera.js";
import { Drag } from "./globe/drag.js";
import { Machine } from "./sequence/machine.js";
import { Player } from "./sequence/player.js";
import { renderEvidence, renderReceipt, clearEvidence } from "./ui/panels.js";
import { Machinery } from "./ui/machinery.js";
import { mountField } from "./ui/field.js";
import { mountTyping } from "./ui/typing.js";
import "./style.css";

const canvas = document.getElementById("stage");
const globe = new Globe(canvas);
const flight = new Flight(globe);
// The canvas ignores pointer events so the UI above it stays clickable, so the
// drag listens on the page and reads movement rather than hit-testing.
const drag = new Drag(globe, document.body);
const machine = new Machine("idle");
const ui = document.getElementById("ui");
const machinery = new Machinery(document.getElementById("machinery"));

let player = null;
let final = null;

/*
  One debugging handle, set once.

  It used to be assigned twice inside run(), with two different shapes — the
  second dropped the player getter — so what `window.__vestigo.player` did
  depended on how far the run had got. Getters instead, so it is always current
  and there is nothing to keep in step.
*/
window.__vestigo = {
  globe, flight, machine,
  get player() { return player; },
  get final() { return final; },
};
// The globe alone, because the offscreen render scripts and every console
// poke reach for it and nothing else.
window.__globe = globe;

// CSS reads the state off the DOM, so the stylesheet can react without any
// JavaScript setting a style directly. One source of truth, two readers.
machine.onChange(({ to }) => { ui.dataset.state = to; });

async function loadIndex() {
  const res = await fetch("/traces/index.json");
  if (!res.ok) throw new Error(`no trace index (${res.status})`);
  return res.json();
}

async function run(entry) {
  player?.cancel();
  flight.cancel();
  clearEvidence();
  globe.clearMarkers();
  globe.setProgress(0);
  // The previous answer, if there was one, left the globe holding still. A new
  // question has nothing to hold still for.
  globe.release();
  machinery.reset();

  machine.go("submitted", { entry });
  const trace = await (await fetch(`/traces/${entry.file}`)).json();
  // The grid comes from the trace, since a run is free to have used a
  // different resolution and the panel should draw what was actually computed.
  machinery.setGrid(trace.grid);
  machine.go("resolving", { trace });

  player = new Player(trace, {
    onStep: (step) => {
      renderEvidence(step);
      machinery.step(step);
      // Candidates appear as they are proposed, so the field of possibilities
      // is visible before it narrows.
      for (const c of step.candidates ?? []) {
        // Small. These are read against a sphere of radius 1, and anything
        // larger becomes a blob covering a country once the camera closes in.
        // Bigger than before across the whole range. These are read against a
        // night side covered in city lights, and at 0.004 the weakest
        // candidates were a green pixel on top of a white one.
        if (c.score > 0.06) globe.mark(c.lat, c.lon, { size: 0.006 + c.score * 0.008 });
      }
    },
    onProgress: (t) => globe.setProgress(t),
    onDone: (done) => {
      final = done;
      const answer = final?.answer;
      const point = final?.candidates?.[0];
      renderReceipt(final);
      // The flight only happens when there is something to fly to. A run that
      // declined leaves the camera where it is, which is the honest picture of
      // what happened.
      if (answer && point) {
        flight.to(point.lat, point.lon, answer.level, {
          onDone: () => machine.go("arrived", { final }),
        });
      } else {
        machine.go("arrived", { final });
      }
    },
  });
}

/*
  The strip of photographs, built twice.

  It travels, so it has to be seamless, and the only way to make a loop of
  images seamless is to have two of them: the track holds the whole set and
  then the whole set again, and the animation slides it exactly half its width
  before starting over. At that instant the second copy is sitting where the
  first one started and there is nothing to see.

  Which means every photograph exists as two buttons, so pressing either has to
  do the same thing and both have to show as pressed. Keyed on the entry's file
  rather than on the element.
*/
function mountExamples(entries) {
  const track = document.getElementById("examples-track");
  const buttons = [];

  const make = (entry, copy) => {
    const button = document.createElement("button");
    button.className = "photo";
    button.dataset.file = entry.file;
    button.setAttribute("aria-pressed", "false");
    // The second copy is the same control as the first, so a screen reader
    // should be told about it once.
    if (copy) button.setAttribute("aria-hidden", "true");
    if (entry.photo) {
      const img = document.createElement("img");
      img.src = entry.photo;
      // The alt text says what it is, not where it is. Naming the place would
      // hand a screen reader the answer the page exists to work out.
      img.alt = "A photograph of an unknown place";
      // Not lazy any more. Half of these start off screen by design and a lazy
      // image that scrolls into view mid-loop arrives as a grey gap.
      button.append(img);
    } else {
      button.textContent = entry.subject;
    }
    button.addEventListener("click", () => {
      if (machine.state !== "idle") machine.go("idle");
      for (const b of buttons) {
        b.setAttribute("aria-pressed", String(b.dataset.file === entry.file));
      }
      run(entry).catch((err) => console.error(err));
    });
    buttons.push(button);
    return button;
  };

  /*
    How many copies of the set, and two is not enough.

    The track slides left by exactly one set's width and then jumps back, which
    is seamless only if there is still a full screen of photographs to the right
    at the moment it jumps. With two copies and a set 1008px wide, a 1938px
    window is showing everything up to 2946px by the end of the slide while the
    track stops at 2016 — so the last third of the strip was empty, the
    photographs ran out, and the row sat half bare until the animation looped.
    On a narrow window it never showed at all, which is why it looked
    intermittent rather than broken.

    The requirement is width >= viewport + travel, and travel is one set. So the
    number of copies is however many sets cover the screen, plus one.
  */
  const fill = () => {
    track.replaceChildren();
    buttons.length = 0;
    track.append(...entries.map((e) => make(e, false)));
    const set = track.scrollWidth;
    if (!set) return 0;

    const window_ = document.getElementById("examples").clientWidth || set;
    // One more than strictly needed. The requirement is exactly
    // width >= viewport + travel, and at 1938px that left 78px of slack, which
    // is close enough to zero that a sub-pixel rounding anywhere shows as a
    // gap at the far end of the slide. A spare set costs nine img tags.
    const copies = Math.ceil(window_ / set) + 2;
    for (let c = 1; c < copies; c++) {
      track.append(...entries.map((e) => make(e, true)));
    }

    /*
      The repeat period, measured rather than computed.

      It is not one set's width. scrollWidth of a single set is the sum of the
      photographs plus the gaps *between* them — the last one has no trailing
      gap — but once a second copy is appended there is a gap between the two
      copies as well. Sliding by the set width therefore leaves the strip half
      a rem short of where it started on every loop, and that error accumulates
      into a visible jump.

      The distance from the first photograph of one copy to the first
      photograph of the next is the period by definition, and it does not care
      how the gaps are arranged.
    */
    const first = track.children[0];
    const second = track.children[entries.length];
    return second ? second.offsetLeft - first.offsetLeft : set;
  };

  /*
    Speed comes from the width rather than being a fixed duration.

    A constant duration means the strip moves at whatever speed nine
    photographs happen to imply, and adding a tenth silently speeds it up.
    Sixty pixels a second is slow enough to read a photograph as it passes and
    fast enough that the row is visibly alive.
  */
  const measure = () => {
    const period = fill();
    if (!period) return;
    track.style.setProperty("--travel", `${period}px`);
    track.style.setProperty("--duration", `${(period / 60).toFixed(1)}s`);
  };
  measure();
  // Widths are wrong until the photographs have decoded, so measure again once
  // they have rather than guessing at a delay.
  Promise.all(
    [...track.querySelectorAll("img")].map((i) => i.decode().catch(() => {})),
  ).then(measure);

  // Resizing changes how many copies are needed. Debounced, because a drag of
  // the window edge fires this continuously and each call rebuilds the row.
  let pending = 0;
  window.addEventListener("resize", () => {
    clearTimeout(pending);
    pending = setTimeout(measure, 180);
  });
}

/*
  One frame loop for the whole page.

  Everything animated is driven from here rather than from its own timer, so
  nothing can drift out of step with anything else. The order matters: the
  flight moves the globe, the drag coasts it if no flight is running, and only
  then is anything drawn.
*/
/*
  Render mode, when the URL asks for it.

  A recording must not run on requestAnimationFrame: a real-time loop drops
  frames while a shader compiles, runs at whatever rate the machine manages,
  and gives a different result every time. Under ?render the frame loop is not
  started at all and an external script steps the scene by exact amounts.
*/
const RENDERING = new URLSearchParams(location.search).has("render");
if (RENDERING) {
  // Everything that is not the globe. The opening panel is appended to the
  // body rather than into #ui, so hiding #ui alone left ENTER and the readings
  // sitting in the middle of the footage.
  document.getElementById("ui").style.display = "none";
  const hideChrome = document.createElement("style");
  hideChrome.textContent = `
    #ui, .opening, .grain, .vignette { display: none !important; }
    .field { opacity: 0.35; }
    html, body { background: #04060a; }`;
  document.head.append(hideChrome);
  const { installRenderMode } = await import("./render-mode.js");
  installRenderMode({
    globe, flight, machine,
    loadTrace: async (file) => {
      const trace = await (await fetch(`/traces/${file}`)).json();
      player = new Player(trace, {
        onStep: () => {},
        onProgress: (t) => globe.setProgress(t),
        onDone: () => {},
      });
      return trace;
    },
    play: () => player,
  });
}

let last = performance.now();
function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.05);   // capped, so a backgrounded
  last = now;                                        // tab does not jump on return
  // Order matters. The player may finish and start a flight this frame, the
  // flight moves the globe, the drag coasts it only when no flight is running,
  // and nothing is drawn until all three have had their say.
  player?.update(dt);
  flight.update(now);
  drag.update(Boolean(flight.active));
  globe.render(dt);
  requestAnimationFrame(frame);
}
if (!RENDERING) requestAnimationFrame(frame);

document.body.style.cursor = "grab";

// The background reads from the traces, so it says the same things the page
// is arguing about rather than resembling them.
mountField();
mountTyping();

/*
  The opening, if there is one to show.

  Mounted only when a clip is actually on disk. Showing a "Begin" panel that
  dismisses itself with nothing behind it is worse than not showing one, and
  this page has to work for somebody opening it thirty seconds before an
  interview.
*/
// Resolves to the intro's URL or null, rather than a boolean: the file is named
// after a hash of its contents so that replacing it cannot be defeated by a
// cache, which means nothing can hardcode the path. See opening.js.
Opening.available().then((src) => {
  if (!src || RENDERING) return;
  new Opening({
    onBegin: () => { globe.spinning = false; },
    onFinish: () => { globe.spinning = true; },
  }).mount();
});

loadIndex()
  .then(mountExamples)
  .catch((err) => {
    console.warn("no traces yet:", err.message);
    document.getElementById("examples").textContent =
      "No traces built yet. Run scripts/build_site_traces.py.";
  });
