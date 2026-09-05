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

  machine.go("submitted", { entry });
  const trace = await (await fetch(`/traces/${entry.file}`)).json();
  machine.go("resolving", { trace });

  player = new Player(trace, {
    onStep: (step) => {
      renderEvidence(step);
      // Candidates appear as they are proposed, so the field of possibilities
      // is visible before it narrows.
      for (const c of step.candidates ?? []) {
        // Small. These are read against a sphere of radius 1, and anything
        // larger becomes a blob covering a country once the camera closes in.
        if (c.score > 0.06) globe.mark(c.lat, c.lon, { size: 0.004 + c.score * 0.006 });
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

function mountExamples(entries) {
  const holder = document.getElementById("examples");
  holder.replaceChildren(...entries.map((entry) => {
    const button = document.createElement("button");
    button.className = "photo";
    button.setAttribute("aria-pressed", "false");
    if (entry.photo) {
      const img = document.createElement("img");
      img.src = entry.photo;
      // The alt text says what it is, not where it is. Naming the place would
      // hand a screen reader the answer the page exists to work out.
      img.alt = "A photograph of an unknown place";
      img.loading = "lazy";
      button.append(img);
    } else {
      button.textContent = entry.subject;
    }
    button.addEventListener("click", () => {
      if (machine.state !== "idle") machine.go("idle");
      for (const b of holder.children) b.setAttribute("aria-pressed", "false");
      button.setAttribute("aria-pressed", "true");
      run(entry).catch((err) => console.error(err));
    });
    return button;
  }));
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
Opening.available().then((hasVideo) => {
  if (!hasVideo || RENDERING) return;
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
