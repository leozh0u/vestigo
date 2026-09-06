/*
  The last beat: a photograph of the room, pushing in on the laptop.

    node scripts/render-room.mjs --photo media/desk.jpg \
      --corners "812,441 1396,433 1401,806 806,812"

  Writes media/room.mp4 and media/room-end.json. stitch-intro.mjs joins the
  first and puts the second in the manifest, and the page grows the interface
  out of the rectangle it names.

  ## Why a photograph and not a model

  The intro used to end by flying through a window into a room built out of
  boxes in three.js, and it looked like boxes in three.js. That is not a
  question of effort — the descent above it is real photography at centimetre
  resolution, and nothing hand-built sits next to that without announcing
  itself. Google's own reconstruction cannot help either: below about forty
  metres it has no data, its windows are painted onto the wall rather than
  modelled, and the buildings are solid where a room would be.

  So the room is a photograph of a real room, and the only synthetic thing in it
  is the interface on the screen, which is a screenshot of the real interface.

  ## Why there is no parallax

  This is a flat push on a still image: the camera crops in and nothing moves
  relative to anything else. The obvious upgrade is to cut the photograph into
  depth layers and slide them at different rates, and it is the wrong call here.
  Fake parallax is only convincing where the cut edges are hidden, a desk lamp
  and a chair back are exactly where they are not, and a wrong parallax reads as
  wrong far more loudly than no parallax reads as flat. Over three and a half
  seconds at this magnification there is nothing for the eye to miss.

  ## The screen

  The four corners are given by hand, in pixels, clockwise from the top left of
  the screen as it appears in the photograph. The interface is then drawn into
  that quadrilateral with a projective warp — not an affine one. An affine map
  can shear and scale but it keeps parallel lines parallel, and the two vertical
  edges of a photographed screen are not parallel unless the camera was exactly
  square on. Every screen replacement done with a plain transform has the same
  tell: the image sits inside a frame that does not match it.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const args = Object.fromEntries(
  process.argv.slice(2).join(" ").split("--").filter(Boolean)
    .map((s) => s.trim()).map((s) => {
      const i = s.indexOf(" ");
      return i === -1 ? [s, true] : [s.slice(0, i), s.slice(i + 1).trim()];
    }),
);

const PHOTO = args.photo ?? "media/desk.jpg";
const UI = args.ui ?? "media/ui.png";
const OUT = args.out ?? "media/room.mp4";
const WIDTH = Number(args.width ?? 1920);
const HEIGHT = Math.round(WIDTH * 9 / 16);
const FPS = Number(args.fps ?? 30);
const SECONDS = Number(args.seconds ?? 3.6);

/*
  How much of the frame the screen fills at the end.

  Matched to what the old ending arrived at, because the page's handoff was
  built and tuned against that number: the video scales about the rectangle's
  centre until the rectangle fills the viewport, and a much smaller rectangle
  means a much larger scale and a more violent last move.
*/
const FILL = Number(args.fill ?? 0.62);

/*
  Out of the dark, and it has to be the same dark.

  The descent ends by mixing to this colour rather than to zero. A beat that
  opened from pure black against one that closed to near-black would put a
  visible step in the middle of the join, which is the one place in the whole
  intro where there is nothing else on screen to distract from it.
*/
const DARK = "#020203";

const corners = (args.corners ?? "").trim().split(/\s+/)
  .map((pair) => pair.split(",").map(Number));

if (corners.length !== 4 || corners.some((c) => c.length !== 2 || c.some(Number.isNaN))) {
  console.error(
    'need --corners "x1,y1 x2,y2 x3,y3 x4,y4", clockwise from the screen\'s\n' +
    "top left, in pixels of the photograph.");
  process.exit(1);
}

const dataURI = async (file) => {
  const buf = await fs.readFile(file);
  const type = file.endsWith(".png") ? "image/png" : "image/jpeg";
  return `data:${type};base64,${buf.toString("base64")}`;
};

/*
  The page that does the work.

  Two canvases. `plate` is the photograph at its own resolution with the
  interface warped onto the screen, composited once. `out` is the frame being
  photographed, and every frame is one drawImage out of the plate — a crop that
  shrinks towards the screen — plus a wash of the dark at the head of the shot.

  Drawing the whole move out of one high-resolution still is what keeps it
  smooth. The alternative, re-warping every frame, re-samples the interface 108
  times and every one of them lands on a slightly different pixel grid, which is
  visible as the text crawling.
*/
const harness = (photo, ui, quad) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="out" width="${WIDTH}" height="${HEIGHT}" style="display:block"></canvas>
<script>
const QUAD = ${JSON.stringify(quad)};
const load = (src) => new Promise((done, fail) => {
  const i = new Image(); i.onload = () => done(i); i.onerror = fail; i.src = src;
});

/*
  Draw an image into an arbitrary quadrilateral, with perspective.

  A 2D canvas transform is affine: six numbers, and it cannot make parallel
  lines converge. A photographed screen's edges converge unless the camera was
  exactly square on, so an affine warp leaves the interface visibly not sitting
  in its own frame.

  The way round it is the one every software rasteriser used before hardware:
  split the quad into triangles, and give each vertex a third texture
  coordinate that carries the perspective divide. For a quad the right values
  come from the diagonals — the point where they cross divides each one in a
  ratio, and that ratio is exactly the ratio of the two vertices' w. So the
  quad is drawn as two affine triangles whose texture coordinates have already
  been divided through, and the seam along the diagonal disappears because both
  halves agree there by construction.

  Done on a WebGL context rather than by hand, because a hand-written
  rasteriser at this resolution is slow and this is a solved problem: give the
  shader vec3 coordinates and use texture2DProj.
*/
function warpInto(ctx, image, quad) {
  const w = ctx.canvas.width, h = ctx.canvas.height;
  const gl = document.createElement("canvas");
  gl.width = w; gl.height = h;
  const g = gl.getContext("webgl", { premultipliedAlpha: false, alpha: true });

  // Where the diagonals cross, and how each one is divided there.
  const [p0, p1, p2, p3] = quad;
  const cross = (a, b, c, d) => {
    const d1 = [b[0] - a[0], b[1] - a[1]];
    const d2 = [d[0] - c[0], d[1] - c[1]];
    const den = d1[0] * d2[1] - d1[1] * d2[0];
    const t = ((c[0] - a[0]) * d2[1] - (c[1] - a[1]) * d2[0]) / den;
    return [a[0] + d1[0] * t, a[1] + d1[1] * t];
  };
  const c = cross(p0, p2, p1, p3);
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const d0 = dist(p0, c), d1 = dist(p1, c), d2 = dist(p2, c), d3 = dist(p3, c);
  // w for each corner. A degenerate quad gives a zero here; fall back to 1,
  // which is the affine answer and is right for a square-on screen anyway.
  const q = [
    (d0 + d2) / d2 || 1, (d1 + d3) / d3 || 1,
    (d2 + d0) / d0 || 1, (d3 + d1) / d1 || 1,
  ];

  // Clip space, y up; the quad is in pixels, y down.
  const clip = quad.map(([x, y]) => [x / w * 2 - 1, 1 - y / h * 2]);
  const uv = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const verts = [];
  for (const i of [0, 1, 2, 0, 2, 3]) {
    verts.push(clip[i][0], clip[i][1],
               uv[i][0] * q[i], uv[i][1] * q[i], q[i]);
  }

  const sh = (type, src) => {
    const s = g.createShader(type); g.shaderSource(s, src); g.compileShader(s);
    if (!g.getShaderParameter(s, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(s));
    return s;
  };
  const prog = g.createProgram();
  g.attachShader(prog, sh(g.VERTEX_SHADER, \`
    attribute vec2 aPos; attribute vec3 aUv; varying vec3 vUv;
    void main() { vUv = aUv; gl_Position = vec4(aPos, 0.0, 1.0); }\`));
  g.attachShader(prog, sh(g.FRAGMENT_SHADER, \`
    precision highp float; uniform sampler2D uTex; varying vec3 vUv;
    void main() { gl_FragColor = texture2DProj(uTex, vUv); }\`));
  g.linkProgram(prog); g.useProgram(prog);

  const buf = g.createBuffer();
  g.bindBuffer(g.ARRAY_BUFFER, buf);
  g.bufferData(g.ARRAY_BUFFER, new Float32Array(verts), g.STATIC_DRAW);
  const aPos = g.getAttribLocation(prog, "aPos");
  const aUv = g.getAttribLocation(prog, "aUv");
  g.enableVertexAttribArray(aPos);
  g.vertexAttribPointer(aPos, 2, g.FLOAT, false, 20, 0);
  g.enableVertexAttribArray(aUv);
  g.vertexAttribPointer(aUv, 3, g.FLOAT, false, 20, 8);

  const tex = g.createTexture();
  g.bindTexture(g.TEXTURE_2D, tex);
  /*
    Not flipped, and this is the one line that decides which way up the
    interface ends up.

    A texture coordinate of zero maps to the first row uploaded, and for an
    HTML image that is the top row. UNPACK_FLIP_Y_WEBGL makes it the bottom row
    instead, which is what you want when the thing being textured has its own
    y-up convention. This quad does not: its corners are given in image pixels,
    y down, and its texture coordinates are given to match. Flipping put the
    photo strip along the top of the laptop screen and the wordmark upside down
    in the corner, which is a mistake that looks like a bug in the warp and is
    not.
  */
  g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, false);
  g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE);
  g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE);
  g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MIN_FILTER, g.LINEAR);
  g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MAG_FILTER, g.LINEAR);
  g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, g.RGBA, g.UNSIGNED_BYTE, image);

  g.viewport(0, 0, w, h);
  g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT);
  g.drawArrays(g.TRIANGLES, 0, 6);
  ctx.drawImage(gl, 0, 0);
}

window.__setup = async () => {
  const photo = await load(${JSON.stringify(photo)});
  const ui = await load(${JSON.stringify(ui)});

  const plate = document.createElement("canvas");
  plate.width = photo.naturalWidth; plate.height = photo.naturalHeight;
  const pc = plate.getContext("2d");
  pc.drawImage(photo, 0, 0);
  warpInto(pc, ui, QUAD);

  /*
    A trace of the screen's own light on its bezel.

    A dark laptop screen in a photograph is dark all the way to its edge; a lit
    one throws a little onto the frame around it. Without this the interface
    reads as a rectangle pasted on, and it is the single cheapest thing that
    stops it. Kept small — this is a hint, not a glow.
  */
  pc.save();
  pc.globalCompositeOperation = "lighter";
  pc.globalAlpha = 0.14;
  pc.filter = "blur(28px)";
  warpInto(pc, ui, QUAD);
  pc.restore();

  window.__plate = plate;
  return { width: plate.width, height: plate.height };
};

/*
  One frame: a crop of the plate, and the dark over it.

  The crop is given as a centre and a width in plate pixels; the height follows
  the output's aspect, so the shot cannot drift out of ratio however the ease
  is changed.
*/
window.__frame = ({ cx, cy, cw, dark }) => {
  const out = document.getElementById("out");
  const ctx = out.getContext("2d");
  const ch = cw * ${HEIGHT} / ${WIDTH};
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(window.__plate, cx - cw / 2, cy - ch / 2, cw, ch,
                0, 0, ${WIDTH}, ${HEIGHT});
  if (dark > 0) {
    ctx.save();
    ctx.globalAlpha = dark;
    ctx.fillStyle = ${JSON.stringify(DARK)};
    ctx.fillRect(0, 0, ${WIDTH}, ${HEIGHT});
    ctx.restore();
  }
};
</script></body></html>`;

async function main() {
  for (const f of [PHOTO, UI]) {
    try { await fs.access(f); } catch {
      console.error(`missing ${f}`);
      process.exit(1);
    }
  }

  const frames = Math.round(SECONDS * FPS);
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".room-"));
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
           "--hide-scrollbars", "--enable-unsafe-swiftshader"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    page.on("pageerror", (e) => console.log("  page:", e.message.slice(0, 160)));
    await page.setContent(harness(await dataURI(PHOTO), await dataURI(UI), corners),
                          { waitUntil: "load" });
    const plate = await page.evaluate(() => window.__setup());
    console.log(`plate ${plate.width}x${plate.height}, ${frames} frames -> ${OUT}`);

    /*
      Where the move starts and where it ends.

      It ends on the screen: centred on the middle of the quad, cropped so the
      quad spans FILL of the frame. It starts on as much of the photograph as
      the output's ratio allows, centred on the same point rather than on the
      middle of the picture — a push that also slides sideways reads as a pan,
      and this is not a pan.
    */
    const xs = corners.map((c) => c[0]);
    const ys = corners.map((c) => c[1]);
    const screen = {
      cx: (Math.min(...xs) + Math.max(...xs)) / 2,
      cy: (Math.min(...ys) + Math.max(...ys)) / 2,
      w: Math.max(...xs) - Math.min(...xs),
      h: Math.max(...ys) - Math.min(...ys),
    };
    const endW = screen.w / FILL;
    // The widest crop that stays inside the photograph while centred on the
    // screen, so no frame ever shows an edge.
    const startW = Math.min(
      plate.width, plate.height * WIDTH / HEIGHT,
      2 * Math.min(screen.cx, plate.width - screen.cx),
      2 * Math.min(screen.cy, plate.height - screen.cy) * WIDTH / HEIGHT,
    );

    /*
      Eased out, and in log space.

      Log space for the same reason the fall above it is: a crop that narrows by
      a constant number of pixels a second appears to accelerate, because what
      the eye reads is the ratio. A constant ratio is a constant apparent speed,
      and this shot has to feel like the same move the descent was making.
    */
    const easeOut = (x) => 1 - Math.pow(1 - x, 2.4);

    for (let i = 0; i < frames; i++) {
      const t = i / (frames - 1);
      const k = easeOut(t);
      const cw = Math.exp(Math.log(startW) + (Math.log(endW) - Math.log(startW)) * k);
      /*
        Up out of the dark over the first fifth, which is slower than the
        descent went into it.

        Coming up is always slower than going down in a transition like this:
        going down the audience already knows what it is looking at, and coming
        up they are being asked to read a new place. Rushing it is what makes a
        cut feel like a cut.
      */
      const lift = Math.min(1, t / 0.2);
      const dark = 1 - lift * lift * (3 - 2 * lift);
      await page.evaluate((f) => window.__frame(f),
                          { cx: screen.cx, cy: screen.cy, cw, dark });
      const shot = await page.screenshot({ type: "png", optimizeForSpeed: true });
      await fs.writeFile(path.join(dir, `f${String(i).padStart(5, "0")}.png`), shot);
      if (i % 30 === 0) process.stdout.write(`\r  frame ${i}/${frames}`);
    }
    process.stdout.write(`\r  frame ${frames}/${frames}\n`);

    /*
      Where the screen is in the last frame, as fractions of it.

      The same contract render-descent used to write, so the page's handoff is
      unchanged: it scales the video about this rectangle's centre until the
      rectangle fills the viewport, and the live interface is already there.
    */
    const ch = endW * HEIGHT / WIDTH;
    // Dead centre, because the crop is centred on the screen for the whole
    // move. Written out rather than assumed, so a shot that ends off-centre
    // later only has to change one line.
    const rect = {
      x: 0.5,
      y: 0.5,
      w: +(screen.w / endW).toFixed(4),
      h: +(screen.h / ch).toFixed(4),
    };
    await fs.writeFile("media/room-end.json", `${JSON.stringify(rect, null, 2)}\n`);
    console.log(`  screen fills ${(rect.w * 100).toFixed(0)}% of the last frame`);

    await fs.mkdir(path.dirname(OUT), { recursive: true });
    await encode(dir, OUT, FPS);
    console.log(`wrote ${OUT}`);
  } finally {
    await browser.close();
    await fs.rm(dir, { recursive: true, force: true });
  }
}

function encode(dir, out, fps) {
  return new Promise((resolve, reject) => {
    const ff = spawn("ffmpeg", [
      "-y", "-framerate", String(fps),
      "-i", path.join(dir, "f%05d.png"),
      "-c:v", "libx264", "-pix_fmt", "yuv420p",
      "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
      "-crf", "17", "-preset", "slow", "-movflags", "+faststart", out,
    ], { stdio: ["ignore", "ignore", "pipe"] });
    let err = "";
    ff.stderr.on("data", (d) => { err += d; });
    ff.on("close", (c) => (c === 0 ? resolve() : reject(new Error(err.slice(-600)))));
  });
}

main().catch((e) => { console.error(e.message); process.exit(1); });
