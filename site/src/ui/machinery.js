/*
  The right-hand side: what the system is actually doing while it works.

  The left column has always shown what was *seen*. This shows what is being
  *done with it*, which is the half the page was missing: observations arrived,
  an answer appeared, and the reasoning in between happened somewhere off
  screen. A page whose entire argument is "every claim is traceable" should not
  hide the trace.

  ## Everything here is read out of the trace

  Not one number on this panel is invented, and that constraint is the whole
  design. It would be easy to make a convincing amount of motion out of random
  hex and a scrolling word list, and it would also be the exact thing this
  project exists to argue against. So:

    - the map is `step.admissible`, the real 90x45 grid the run computed
    - the scores are `prior x admissibility`, the actual ranking function
    - the caps are `resolves_to` and `max_strength`, which are what stop a
      street sign from being allowed to name a street
    - the tool names are the tools that ran

  If it looks busy, that is because resolving a photograph is busy.
*/

// The grid the agent works in: 4 degrees a side, 90 across by 45 down, row
// major from the south-west. Read from the trace rather than assumed, and
// these are only the fallback for a trace written before the grid was
// recorded.
const COLS = 90;
const ROWS = 45;

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

const pad = (n, w) => String(n).padStart(w, " ");

export class Machinery {
  constructor(root) {
    this.root = root;
    this.cols = COLS;
    this.rows = ROWS;

    root.replaceChildren();

    const head = el("div", "mach-head");
    head.append(el("span", "mach-label", "ADMISSIBLE"));
    this.percent = el("span", "mach-percent", "100.0%");
    head.append(this.percent);
    root.append(head);

    /*
      The map, drawn at one pixel per cell and scaled up by CSS.

      Deliberately not smoothed. Each square is one 4-degree cell that the run
      either kept or ruled out, and interpolating between them would draw a
      soft gradient that implies a resolution the computation does not have.
      Hard squares are honest about how coarse the grid is.
    */
    this.canvas = el("canvas", "mach-grid");
    this.canvas.width = this.cols;
    this.canvas.height = this.rows;
    root.append(this.canvas);
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: false });
    this.image = this.ctx.createImageData(this.cols, this.rows);
    /*
      Where the land is, at the grid's own resolution.

      Without it this panel is unreadable, and the first version proved it. The
      solar constraint rules out longitudes, so what it produces is a set of
      vertical bands — which is correct, and on screen looked like an audio
      equaliser rather than a map of the world. The same picture with
      continents under it is instantly a planet with half of it ruled out.

      Sampled from the globe's own land mask so the two cannot disagree, and
      held as one boolean per cell rather than as an image, because it is
      combined per pixel in paint().
    */
    this.land = null;
    this.loadLand();
    this.paint(null);

    this.log = el("div", "mach-log");
    root.append(this.log);

    this.count = el("div", "mach-count");
    root.append(this.count);

    this.tools = new Set();
    this.lines = 0;
    this.cells = 1;
  }

  /*
    Sample the land mask down to one value per grid cell.

    Drawn into a canvas at exactly the grid size and read back, which lets the
    browser do the downsampling. A 4-degree cell is about 440 km, so a cell is
    "land" if the average across it is over a third rather than if its centre
    happens to be: at this resolution a centre test drops Britain and most of
    Japan.
  */
  loadLand() {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = this.cols;
      c.height = this.rows;
      const x = c.getContext("2d", { willReadFrequently: true });
      x.drawImage(img, 0, 0, this.cols, this.rows);
      const px = x.getImageData(0, 0, this.cols, this.rows).data;
      /*
        Flipped into the grid's order, which is the opposite of the image's.

        An equirectangular map is stored north at the top. The agent's grid is
        row-major *south to north*, as its own `order` field says. Read
        straight across, Antarctica landed on row 0 and drew as a solid green
        band along the top of the panel with the rest of the world smeared
        under it — a picture that was wrong in a way that still looked like
        data, which is the worst kind.
      */
      this.land = new Uint8Array(this.cols * this.rows);
      for (let row = 0; row < this.rows; row++) {
        const from = (this.rows - 1 - row) * this.cols;
        for (let col = 0; col < this.cols; col++) {
          this.land[row * this.cols + col] = px[(from + col) * 4] > 85 ? 1 : 0;
        }
      }
      this.paint(this.last ?? null);
    };
    // A failure here costs the continents and nothing else, so it is not worth
    // reporting: the panel still shows the right numbers without them.
    img.onerror = () => {};
    img.src = "/textures/globe-land.png";
  }

  /* A trace may declare a different grid. Read it before the first step. */
  setGrid(grid) {
    if (!grid?.cols || !grid?.rows) return;
    if (grid.cols === this.cols && grid.rows === this.rows) return;
    this.cols = grid.cols;
    this.rows = grid.rows;
    this.canvas.width = this.cols;
    this.canvas.height = this.rows;
    this.image = this.ctx.createImageData(this.cols, this.rows);
    this.paint(null);
  }

  /*
    Draw the admissibility map.

    `values` is the run's own array, one entry per cell, and it is not
    normalised: the numbers that come out are a narrow band well above zero,
    because admissibility is a multiplier and a cell that survived every
    constraint is not usually at 1.0. Stretching the band that is actually
    present is what makes the difference between a constrained world and an
    unconstrained one visible at all; scaling against 0 and 255 gives two
    pictures that look identical.

    Null paints the unconstrained state: everything is still possible, which is
    what is true before any constraint has run.
  */
  paint(values) {
    this.last = values;
    const d = this.image.data;
    const n = this.cols * this.rows;

    let lo = Infinity;
    let hi = -Infinity;
    if (values) {
      for (let i = 0; i < n; i++) {
        const v = values[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    const span = hi - lo;

    let admitted = 0;
    let landCells = 0;
    for (let i = 0; i < n; i++) {
      // Row-major south to north, and a canvas runs top to bottom, so the rows
      // are read back to front or the world comes out upside down.
      const x = i % this.cols;
      const y = this.rows - 1 - Math.floor(i / this.cols);
      const p = (y * this.cols + x) * 4;

      const k = values
        ? (span > 1e-9 ? (values[i] - lo) / span : 1)
        : 1;
      const onLand = !this.land || this.land[i];
      if (onLand) landCells += 1;
      if (onLand && k > 0.5) admitted += 1;

      /*
        Land carries the colour, sea only carries a trace of it.

        Both are admissible or not — the constraint does not care whether a
        cell is wet — but a photograph was taken somewhere, and drawing the two
        at the same strength gives a rectangle of green bands with no shape in
        it. Weighting the land is what makes the same data read as a map.
      */
      const isLand = onLand ? 1 : 0;
      const w = isLand ? 1 : 0.22;

      // The same green as a committed answer, falling to the panel's own
      // background rather than to black, so an excluded cell reads as absence
      // rather than as a hole punched in the panel.
      d[p + 0] = 11 + k * w * 78;
      d[p + 1] = 17 + k * w * 176;
      d[p + 2] = 23 + k * w * 118;
      d[p + 3] = 26 + (isLand ? k * 190 : 40 + k * 60);
    }
    this.ctx.putImageData(this.image, 0, 0);

    /*
      The percentage counts land, not the whole grid.

      Seventy per cent of the planet is sea and no photograph in this dataset
      was taken on it, so including the oceans compresses every number towards
      the same value and a constraint that rules out most of a continent barely
      moves it. Against land alone the figure means what a reader assumes it
      means: how much of the world this could still be.
    */
    this.cells = values ? admitted / Math.max(1, landCells) : 1;
    this.percent.textContent = `${(this.cells * 100).toFixed(1)}%`;
    this.percent.classList.toggle("mach-narrowed", this.cells < 0.98);
  }

  /*
    One line of machinery.

    Fixed-width columns, because the point of a readout is that the eye can
    find the same field in the same place on every row without reading any of
    them. Ragged columns are a paragraph.
  */
  write(kind, left, right) {
    const line = el("div", `mach-line mach-${kind}`);
    line.append(el("span", "mach-k", left));
    line.append(el("span", "mach-v", right));
    this.log.append(line);
    this.lines += 1;
    // Older lines leave rather than scroll. A scrollbar on a panel nobody can
    // scroll during a four-second sequence is furniture.
    while (this.log.childElementCount > 9) this.log.firstElementChild.remove();
  }

  step(s) {
    if (s.admissible?.length) this.paint(s.admissible);

    if (s.source) this.tools.add(s.source);

    switch (s.kind) {
      case "evidence": {
        /*
          The cap, and it is the most important number on the panel.

          `resolves_to` is how specific a thing this evidence could possibly
          settle, and `max_strength` is how much of that it is allowed to
          carry. A photograph of a street sign resolves to a street; a
          photograph of pine trees resolves to a region however sharp it is.
          Every overclaim this project is trying to avoid is a claim that
          ignored one of these two numbers.
        */
        const cap = s.resolves_to ?? "—";
        const max = s.max_strength ?? 1;
        this.write("ev", `${s.source} ${s.id}`, `${cap} ≤${max.toFixed(2)}`);
        break;
      }
      case "candidate": {
        const c = s.candidates?.[s.candidates.length - 1];
        if (c) {
          // The ranking function, written out. score = prior x admissibility,
          // and seeing the multiplication is the point: a candidate the model
          // liked at 1.00 stays at 1.00 until something rules territory out.
          this.write(
            "cand",
            `${c.origin} ${c.id}`,
            `${c.prior.toFixed(2)}×${c.admissibility.toFixed(2)}=${c.score.toFixed(2)}`,
          );
        }
        break;
      }
      case "constraint":
        this.write("con", `${s.source}`, `w ${(s.weight ?? 0).toFixed(3)}`);
        break;
      case "claim":
        this.write("claim", `claim ${s.id ?? ""}`.trim(), s.answer?.level ?? "—");
        break;
      case "refutation":
        this.write("ref", `refute ${s.claim_id ?? ""}`.trim(), "dropped");
        break;
      default:
        break;
    }

    this.count.textContent =
      `${pad(this.lines, 3)} steps · ${this.tools.size} tools`;
  }

  reset() {
    this.log.replaceChildren();
    this.tools.clear();
    this.lines = 0;
    this.count.textContent = "";
    this.paint(null);
  }
}
