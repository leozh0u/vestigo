/*
  The background: a field of readings, at four depths.

  ## Why this is drawn to a canvas and not written as elements

  The first version made 116 absolutely positioned spans across four layers,
  each layer animating a transform. Every frame the compositor had to handle
  four large layers full of live text nodes, on top of a WebGL canvas, and the
  page ran at about one frame a second.

  Text does not need to be text here. Nobody selects it, nothing reads it, and
  it never changes. So it is painted once into an offscreen canvas and used as
  a background image, and after that a layer is a single picture the GPU
  translates. One paint at load, then no layout and no repaint at all.

  ## Why it reads as depth

  Parallax. Near layers are larger, brighter and faster; far layers are small,
  dim and nearly still, and the eye takes that as distance without being told.
  The globe sits between them, so the page has a front and a back.

  ## Why the content is real

  Decorative fake code was the thing this replaced. Every line is pulled from
  the traces the site plays: coordinates that were proposed, tools that ran,
  confidences that were computed. Somebody who leans in and reads it finds the
  system's own working.
*/
const FALLBACK = [
  "solar_position  elev 34.2  az 118.7",
  "place_lookup  matched 1  spread 0 km",
  "geocell_classifier  p=0.44  cell 212",
  "country_metas  traffic left  -150",
  "31.5885, 74.3106  score 0.312",
  "resolves_to COUNTRY  max 0.86",
  "verify  confirmed  1.2 km",
  "consensus  3/3  spread 4 km",
  "claim CITY 0.88  capped from POINT",
  "admissibility 0.10  contradicted",
];

// tile: how large a patch is painted before it repeats. scale: font size in
// that patch. alpha: how bright. Near layers are larger, brighter, faster.
const LAYERS = {
  1: { tile: 900, scale: 13, alpha: 0.085, rows: 12, speed: 150 },
  2: { tile: 760, scale: 10, alpha: 0.065, rows: 15, speed: 220 },
  3: { tile: 620, scale: 8, alpha: 0.05, rows: 19, speed: 320 },
  4: { tile: 520, scale: 6, alpha: 0.04, rows: 24, speed: 460 },
};

/* A repeatable shuffle, so the layout is identical on every load. A background
   that rearranges itself on refresh reads as noise rather than as a place. */
function seeded(seed) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

/* One tile, painted once. It has to repeat seamlessly, so anything drawn near
   an edge is drawn again on the opposite side. */
function paintTile(lines, spec, rand) {
  const size = spec.tile;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.font = `300 ${spec.scale}px "IBM Plex Mono", ui-monospace, monospace`;
  ctx.textBaseline = "middle";

  for (let i = 0; i < spec.rows; i++) {
    const text = lines[Math.floor(rand() * lines.length)];
    const x = rand() * size;
    const y = (i + rand() * 0.6) * (size / spec.rows);
    ctx.fillStyle = `rgba(143, 185, 200, ${spec.alpha * (0.5 + rand())})`;
    ctx.fillText(text, x, y);
    // Wrapped copies, so the tile joins itself without a visible seam.
    const width = ctx.measureText(text).width;
    if (x + width > size) ctx.fillText(text, x - size, y);
  }
  return canvas.toDataURL("image/png");
}

async function readLines() {
  try {
    const index = await (await fetch("/traces/index.json")).json();
    const lines = new Set();
    for (const entry of index.slice(0, 4)) {
      const trace = await (await fetch(`/traces/${entry.file}`)).json();
      for (const step of trace.steps ?? []) {
        const text = (step.summary ?? "").replace(/\s+/g, " ").trim();
        if (text && text.length < 64) lines.add(`${step.source ?? step.kind}  ${text}`);
        for (const c of step.candidates ?? []) {
          lines.add(`${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}  ${c.score.toFixed(3)}`);
        }
      }
    }
    return lines.size > 20 ? [...lines] : FALLBACK;
  } catch {
    return FALLBACK;
  }
}

export async function mountField() {
  const lines = await readLines();
  const rand = seeded(20260904);

  for (const el of document.querySelectorAll(".field-layer")) {
    const spec = LAYERS[Number(el.dataset.depth)];
    if (!spec) continue;
    el.style.backgroundImage = `url(${paintTile(lines, spec, rand)})`;
    el.style.backgroundRepeat = "repeat";
    el.style.animationDuration = `${spec.speed}s`;
  }
}
