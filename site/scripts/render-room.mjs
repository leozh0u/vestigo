/*
  The last beat: across the room and onto the screen.

    node scripts/render-room.mjs

  Needs the dev server running (npm run dev) and ffmpeg on PATH.

  ## Why this is photographs and not geometry

  The first version of this beat was built: a brick patch, a sash window, a
  room, a laptop, all modelled and textured by hand and lit with three lights.
  It was rejected on sight and the verdict was right. Hand-authored brick tiles.
  Hand-authored windows are black rectangles. A hand-authored room has nothing
  in it that was not put there deliberately, and a real room is mostly things
  nobody chose.

  What was wrong with it was never the geometry. It was the textures. So this
  keeps the idea and throws away the surfaces: the room is a photograph, and the
  camera move is done to the photograph.

  ## What the move actually is

  Two plates, taken from two distances along the same axis:

    media/room/keyframe-04-room.png   the room, from just inside the window
    media/room/keyframe-05-desk.png   the desk, from about a metre away

  Each is pushed into by cropping — which on its own is a zoom, not a dolly, and
  would read as one. The dolly comes from the cut between them. They are two
  genuinely different camera positions, so the perspective really does change
  when one replaces the other: the plant and the pen cup swing out past the
  edges the way they would if the camera had travelled. Cropping supplies the
  continuous motion and the swap supplies the parallax.

  The swap is hidden the way every other seam in this intro is hidden, by
  putting it where one object fills the frame. Here that is the laptop: the
  crossfade runs at the moment the screen is 32% of the frame in both plates, so
  the two images agree about the position and size of the largest, darkest,
  most-watched thing in the shot, and what changes underneath it is out at the
  edges where nothing is being looked at.

  32% is not a taste decision either. It is the widest the near plate can be
  asked for, because at 32% it is uncropped — a crossfade any earlier would need
  to sample outside the photograph.

  ## The screen

  The interface is not drawn on top of the plate, it is mapped into it. The
  laptop's screen in each photograph is a quadrilateral, not a rectangle: it
  leans back, so its edges converge. An affine transform keeps parallel lines
  parallel and cannot represent that, so the fit would be right at two corners
  and wrong at the other two. This solves the homography instead — the 3x3
  projective map that takes the unit square to those four corners — and inverts
  it in the fragment shader, so every pixel of the frame asks which pixel of the
  interface belongs there. Correct at all four corners by construction, and it
  stays correct as the crop moves, because the crop is folded into the same
  matrix.

  The last frame's screen rectangle is written to media/room-end.json.
  stitch-intro puts it in the manifest and the page grows the live interface out
  of it, so re-rendering this shot moves the handoff with it.
*/
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer";

const args = Object.fromEntries(
  process.argv.slice(2).join(" ").split("--").filter(Boolean)
    .map((s) => s.trim().split(/\s+/)).map(([k, v]) => [k, v ?? true]),
);
const WIDTH = Number(args.width ?? 1920);
const HEIGHT = Math.round((WIDTH * 9) / 16);
const FPS = Number(args.fps ?? 30);
const SECONDS = Number(args.seconds ?? 4.2);
const OUT = args.out ?? "media/room.mp4";
const URL = args.url ?? "http://localhost:5173/";

/*
  Shutter, same as the descent's.

  Each frame is the average of several renders spread across the time the
  shutter would have been open, which is what a camera does and what a single
  instantaneous sample does not. Six samples over half a frame: 180 degrees, the
  film convention, and the number below which a fast push strobes.
*/
const SAMPLES = 6;
const SHUTTER = 0.5;

/*
  The two plates and where the laptop screen is in each, in pixels, clockwise
  from the top left of the display.

  Measured off the images rather than typed: the screen is the darkest large
  region in both, so a threshold at luminance 14 and a scan for the rows whose
  dark run is a clean rectangle finds its edges to within a pixel. Written down
  here because a measurement that has to be redone every render is a measurement
  that will eventually be wrong.
*/
const PLATES = {
  far: {
    src: "/media/room/keyframe-04-room.png",
    w: 1672, h: 941,
    screen: [[760, 426], [907, 426], [909, 530], [757, 530]],
  },
  near: {
    src: "/media/room/keyframe-05-desk.png",
    w: 1672, h: 940,
    screen: [[581, 314], [1101, 314], [1118, 651], [561, 651]],
  },
};
const UI = "/media/ui.png";

/*
  How wide the screen is, as a fraction of the frame, at each end of the move
  and at the swap.

  The end is 62% because that is what the page's handoff was built around: the
  clip finishes with the interface at that size and grows it the rest of the
  way, and a bigger number leaves less room for the growth to be a movement
  rather than a jump.

  The swap is 32% because that is the near plate uncropped. Not chosen.
*/
/*
  The start is the far plate's own framing, and it has to be derived rather
  than chosen.

  It was 0.075, picked by eye as "the room, wide". The plate's screen is 8.94%
  of it, so for the first stretch of the beat the schedule was asking for a
  crop wider than the photograph -- which clamps, and a clamped crop does not
  move. Measured on the finished cut: 0.64 seconds of frame-to-frame difference
  at exactly 0.00, immediately after the shot comes out of the dark. Two thirds
  of a second of a still photograph in the middle of a camera move, which is
  the most obvious cut in the whole intro and was put there by a number that
  looked reasonable.

  Set from the plate itself, so it starts at the widest framing that photograph
  actually has and every frame after it moves.
*/
const SWAP = 0.322;
const END = 0.62;
// Seconds of overlap at the swap. Long enough to be a dissolve, short enough
// that the two plates are never both legible.
const BLEND = 0.32;

/* The screen's centre and width in a plate, as fractions of it. */
const centreOf = (q, w, h) => [
  q.reduce((s, p) => s + p[0], 0) / 4 / w,
  q.reduce((s, p) => s + p[1], 0) / 4 / h,
];
const widthOf = (q, w) => ((q[1][0] - q[0][0]) + (q[2][0] - q[3][0])) / 2 / w;

// See the note above the SWAP and END constants.
const START = widthOf(PLATES.far.screen, PLATES.far.w);

/*
  Where the shot is at a moment, as a fraction of the whole.

  One number drives everything: how wide the screen is in the finished frame.
  Both plates are then cropped to whatever makes their own screen that wide, so
  they agree about the subject at every instant whether or not they are both
  being drawn. That is what makes the crossfade a crossfade instead of a cut.

  Geometric rather than linear, because a push that covers equal *ratios* per
  second is what reads as steady approach — the same reason the fall through the
  sky is exponential. Eased at both ends: it arrives out of the window beat
  already moving and settles before the interface takes over, and a handoff that
  is still accelerating is a handoff that jumps.
*/
function beat(t) {
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };
  /*
    Eased out only. It has to arrive already moving.

    smoothstep has zero slope at both ends, so this beat used to start from a
    standstill -- and the beat before it is a fall through the sky that is still
    travelling when the light goes. Measured across the join, the descent's last
    visible frames and the room's first ones are a shot decelerating to nothing
    and then starting again, which is what a cut is, whether or not there is
    darkness over the top of it.

    The exponent gives it 1.8 times its average speed at the moment it comes out
    of the dark and none at all by the end, which is also the right shape for
    what is happening: the camera has fallen a long way, comes through, and
    settles onto the desk.
  */
  const k = 1 - Math.pow(1 - clamp01(t), 1.8);
  const shown = Math.exp(Math.log(START) + (Math.log(END) - Math.log(START)) * k);

  const half = BLEND / SECONDS / 2;
  const at = (Math.log(SWAP) - Math.log(START)) / (Math.log(END) - Math.log(START));
  // Where the swap sits in eased time, so the blend is centred on the frame
  // where both plates show the screen at exactly the same size.
  const when = (() => {
    let lo = 0, hi = 1;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (smooth(mid) < at) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  })();
  const mix = smooth((t - (when - half)) / (2 * half));

  return { shown, mix };
}

/*
  The crop on a plate that makes its screen `shown` wide in the finished frame,
  as x, y, w, h in 0..1 of the plate.

  Clamped to the plate, because the near one cannot be asked for a screen
  narrower than it already has and the far one cannot be asked for one wider
  than its pixels support. Both limits are respected by the schedule above; the
  clamp is here so that a change to the schedule fails visibly rather than by
  sampling the edge pixel across half the frame.
*/
function crop(plate, shown) {
  const own = widthOf(plate.screen, plate.w);
  const [cx, cy] = centreOf(plate.screen, plate.w, plate.h);
  const w = Math.min(1, own / shown);
  const h = w;                      // plates and frame are both 16:9
  const x = Math.min(1 - w, Math.max(0, cx - w / 2));
  const y = Math.min(1 - h, Math.max(0, cy - h / 2));
  return [x, y, w, h];
}

/*
  The homography taking the unit square to four points, as a column-major 3x3.

  Standard eight-unknown solve: each corner gives two linear equations in the
  eight free parameters of a projective map, and the ninth is fixed by scale.
  Written out rather than pulled from a library because it is eight equations
  and the dependency would be larger than the function.
*/
function homography(q) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = q;
  // Solve for the projective terms first: the unit square's diagonal condition.
  const dx1 = x1 - x2, dx2 = x3 - x2, sx = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2, dy2 = y3 - y2, sy = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (sx * dy2 - dx2 * sy) / den;
  const h = (dx1 * sy - sx * dy1) / den;
  return [
    x1 - x0 + g * x1, y1 - y0 + g * y1, g,
    x3 - x0 + h * x3, y3 - y0 + h * y3, h,
    x0, y0, 1,
  ];
}

function invert3(m) {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h, B = f * g - d * i, C = d * h - e * g;
  const det = a * A + b * B + c * C;
  return [
    A / det, (c * h - b * i) / det, (b * f - c * e) / det,
    B / det, (a * i - c * g) / det, (c * d - a * f) / det,
    C / det, (b * g - a * h) / det, (a * e - b * d) / det,
  ];
}

/* Multiply column-major 3x3s: the result applies `b` and then `a`. */
function mul3(a, b) {
  const o = new Array(9).fill(0);
  for (let c = 0; c < 3; c++) {
    for (let r = 0; r < 3; r++) {
      let s = 0;
      for (let k = 0; k < 3; k++) s += a[k * 3 + r] * b[c * 3 + k];
      o[c * 3 + r] = s;
    }
  }
  return o;
}

/*
  Frame uv to interface uv, for one plate at one crop.

  Three steps composed into one matrix. The screen's corners are known in the
  plate; the crop maps plate coordinates into the frame; and the interface is a
  unit square. So: take the unit square to the screen quad in plate space,
  compose with the crop, invert, and the shader can ask any frame pixel which
  interface pixel belongs to it.
*/
function screenMap(plate, [cx, cy, cw, ch]) {
  const q = plate.screen.map(([x, y]) => [x / plate.w, y / plate.h]);
  const toPlate = homography(q);
  // Plate uv to frame uv: subtract the crop's origin and divide by its size.
  const toFrame = [1 / cw, 0, 0, 0, 1 / ch, 0, -cx / cw, -cy / ch, 1];
  return invert3(mul3(toFrame, toPlate));
}

/* Where the screen's four corners land in the finished frame, 0..1, y down. */
function screenRect(plate, cropRect) {
  const [cx, cy, cw, ch] = cropRect;
  const pts = plate.screen.map(([x, y]) => [
    (x / plate.w - cx) / cw, (y / plate.h - cy) / ch,
  ]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return {
    x: +((Math.min(...xs) + Math.max(...xs)) / 2).toFixed(4),
    y: +((Math.min(...ys) + Math.max(...ys)) / 2).toFixed(4),
    w: +(Math.max(...xs) - Math.min(...xs)).toFixed(4),
    h: +(Math.max(...ys) - Math.min(...ys)).toFixed(4),
  };
}

const harness = (w, h) => `
<!doctype html><html><body style="margin:0;background:#000;overflow:hidden">
<canvas id="c" width="${w}" height="${h}" style="display:block"></canvas>
<canvas id="out" width="${w}" height="${h}" style="display:none"></canvas>
<script type="module">
import * as THREE from "/node_modules/three/build/three.module.js";

const W = ${w}, H = ${h};
const canvas = document.getElementById("c");
// preserveDrawingBuffer so readPixels can be called after the draw, which is
// what the shutter accumulation below needs.
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false,
                                           preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);

const load = (src) => new Promise((done, fail) => {
  new THREE.TextureLoader().load(src, (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.magFilter = THREE.LinearFilter;
    t.generateMipmaps = true;
    // The plates are cropped into hard, so an anisotropic sample is the
    // difference between a legible bookshelf at the edge of frame and a smear.
    t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    done(t);
  }, undefined, fail);
});

const uniforms = {
  uA: { value: null }, uB: { value: null }, uUI: { value: null },
  uCropA: { value: new THREE.Vector4() }, uCropB: { value: new THREE.Vector4() },
  uMapA: { value: new THREE.Matrix3() }, uMapB: { value: new THREE.Matrix3() },
  uMix: { value: 0 },
  uGrade: { value: new THREE.Vector3(1, 1, 1) },
  uGlow: { value: 0 },
  uLift: { value: 0 },
  uVignette: { value: 0.08 },
};

const material = new THREE.ShaderMaterial({
  uniforms,
  vertexShader: \`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }\`,
  fragmentShader: \`
    precision highp float;
    varying vec2 vUv;
    uniform sampler2D uA, uB, uUI;
    uniform vec4 uCropA, uCropB;
    uniform mat3 uMapA, uMapB;
    uniform float uMix, uGlow, uVignette, uLift;
    uniform vec3 uGrade;

    /*
      One plate, cropped, with the interface mapped into its screen.

      The interface is sampled through the inverse homography, so the lean of
      the lid is respected: a pixel near the top of the display asks for a
      slightly different part of the picture than one near the bottom, which is
      what perspective is and what an affine map cannot do.

      Kept inside the quad by testing the mapped coordinate rather than by
      drawing a quad, because the edge of a drawn quad is aliased against the
      photograph behind it and a test is not.
    \*/
    vec3 plate(sampler2D tex, vec4 crop, mat3 map) {
      vec2 uv = crop.xy + vUv * crop.zw;
      vec3 base = texture2D(tex, uv).rgb;
      vec3 p = map * vec3(vUv, 1.0);
      vec2 q = p.xy / p.z;
      if (q.x > 0.0 && q.x < 1.0 && q.y > 0.0 && q.y < 1.0) {
        /*
          No flip. The homography's v runs down the screen from the top left
          corner, and the texture loader has already turned the image the right
          way up, so flipping here turns it over twice: the first render came
          out with the photo strip along the top of the laptop and the wordmark
          mirrored in the corner.
        \*/
        vec3 ui = texture2D(uUI, q).rgb;
        /*
          Graded to the room, not pasted into it.

          The page is near-black with cold grey type and the room is lit by a
          low sun through a window. A screenshot dropped in untouched is the one
          rectangle in the frame that was photographed somewhere else, and it
          reads as a sticker. Warmed towards the light in the room and lifted a
          little, which is also what a screen actually does when it is the only
          emitter in a dim room.
        \*/
        ui = ui * uGrade + uGlow * vec3(0.055, 0.048, 0.042);
        base = ui;
      }
      return base;
    }

    void main() {
      vec3 c = mix(plate(uA, uCropA, uMapA), plate(uB, uCropB, uMapB), uMix);
      /*
        Lift the shadows a little, most at the start.

        The plate is a dark room with one lit patch in it, and at the top of the
        move the bed, the bookshelf and most of the floor are at zero. That is
        the right photograph and the wrong first frame: the shot has just come
        in through a window and the room is what it came to see. Lifted only in
        the blacks, so the lit patch is untouched, and taken away as the camera
        closes on the desk and there is nothing left in frame to reveal.
      \*/
      c += uLift * (1.0 - smoothstep(0.0, 0.34, dot(c, vec3(0.2126, 0.7152, 0.0722))))
                 * vec3(0.052, 0.040, 0.031);

      /*
        The vignette goes with everything else at the end.

        By the last frame the screen is nearly two thirds of the width, so a
        vignette is darkening the corners of the interface itself -- and the
        page underneath, which is what it hands over to, has no vignette. The
        two would not match at exactly the moment they are supposed to be the
        same picture.
      \*/
      float r = distance(vUv, vec2(0.5)) * 1.42;
      c *= 1.0 - uVignette * pow(clamp(r, 0.0, 1.0), 2.4);
      gl_FragColor = vec4(c, 1.0);
    }\`,
});

const scene = new THREE.Scene();
scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

window.__room = {
  async setup(far, near, ui) {
    const [a, b, u] = await Promise.all([load(far), load(near), load(ui)]);
    uniforms.uA.value = a; uniforms.uB.value = b; uniforms.uUI.value = u;
    return true;
  },
  set(state) {
    uniforms.uCropA.value.fromArray(state.cropA);
    uniforms.uCropB.value.fromArray(state.cropB);
    uniforms.uMapA.value.fromArray(state.mapA);
    uniforms.uMapB.value.fromArray(state.mapB);
    uniforms.uMix.value = state.mix;
    uniforms.uGrade.value.fromArray(state.grade);
    uniforms.uGlow.value = state.glow;
    uniforms.uLift.value = state.lift;
    uniforms.uVignette.value = state.vignette;
  },
  draw() { renderer.render(scene, camera); },
};

/*
  The shutter, accumulated on the CPU.

  readPixels into one preallocated buffer rather than getImageData, which
  allocates eight megabytes a call and ran the descent render out of memory at
  frame 150.
*/
const gl = renderer.getContext();
const buf = new Uint8Array(W * H * 4);
const sum = new Float32Array(W * H * 4);
const out = document.getElementById("out").getContext("2d");
const img = out.createImageData(W, H);

window.__shoot = (states) => {
  sum.fill(0);
  for (const s of states) {
    window.__room.set(s);
    window.__room.draw();
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    for (let i = 0; i < sum.length; i++) sum[i] += buf[i];
  }
  const n = states.length;
  // GL reads bottom-up and a canvas is top-down.
  for (let y = 0; y < H; y++) {
    const src = (H - 1 - y) * W * 4, dst = y * W * 4;
    for (let x = 0; x < W * 4; x += 4) {
      img.data[dst + x] = sum[src + x] / n;
      img.data[dst + x + 1] = sum[src + x + 1] / n;
      img.data[dst + x + 2] = sum[src + x + 2] / n;
      img.data[dst + x + 3] = 255;
    }
  }
  out.putImageData(img, 0, 0);
};
</script></body></html>`;

/*
  The interface, warmed to the room.

  Measured rather than guessed: the plate's light is about 1.00 / 0.78 / 0.55 in
  the lit patch, and a screen in that room is seen through the same air. Pulled
  only part of the way there, because a screen is an emitter and takes the room's
  cast far less than a wall does.
*/
const GRADE = [1.0, 0.93, 0.86];

function state(t) {
  const { shown, mix } = beat(t);
  const cropA = crop(PLATES.far, shown);
  const cropB = crop(PLATES.near, shown);
  /*
    Everything the shot is doing to the picture goes away by the last frame.

    The clip hands over by growing this screen until it is the live page, and
    the live page has no warm cast on it, no glow, no lifted blacks and no
    vignette. Anything still being applied at t=1 is a difference between the
    two images at the one instant they have to be identical -- which is exactly
    the mistake the opening had, seen from the other end.

    So the grade, the glow, the lift and the vignette all run out over the last
    forty per cent, by which point the screen already fills most of the frame
    and there is almost nothing else left to grade.
  */
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };
  const page = smooth((t - 0.6) / 0.4);
  const toward = (a, b) => a + (b - a) * page;

  return {
    cropA, cropB, mix,
    mapA: screenMap(PLATES.far, cropA),
    mapB: screenMap(PLATES.near, cropB),
    grade: GRADE.map((v) => toward(v, 1)),
    glow: toward(0.9, 0),
    lift: toward(1, 0),
    vignette: toward(0.08, 0.004),
  };
}

async function main() {
  const frames = Math.round(SECONDS * FPS);
  const dir = await fs.mkdtemp(path.join(process.cwd(), ".room-"));
  console.log(`${frames} frames at ${WIDTH}x${HEIGHT}, ${FPS}fps -> ${OUT}`);

  const browser = await puppeteer.launch({
    headless: true,
    args: ["--use-gl=angle", "--use-angle=metal", "--enable-gpu",
           "--hide-scrollbars", "--enable-unsafe-swiftshader"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });
    page.on("console", (m) => { if (m.type() === "error") console.log("  page:", m.text().slice(0, 160)); });
    page.on("pageerror", (e) => console.log("  page error:", e.message.slice(0, 160)));

    // The dev server serves node_modules and media, so the harness can import
    // three and load the plates without anything being copied or bundled.
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.setContent(harness(WIDTH, HEIGHT), { waitUntil: "networkidle0" });
    await page.waitForFunction("window.__room !== undefined", { timeout: 30_000 });

    const ok = await page.evaluate((a, b, u) => window.__room.setup(a, b, u),
                                   PLATES.far.src, PLATES.near.src, UI);
    if (!ok) throw new Error("plates did not load");
    console.log("  plates loaded");

    for (let i = 0; i < frames; i++) {
      const t = i / (frames - 1);
      // The shutter's samples, spread across the time it would be open.
      const states = [];
      for (let k = 0; k < SAMPLES; k++) {
        const offset = ((k + 0.5) / SAMPLES - 0.5) * (SHUTTER / frames);
        states.push(state(Math.max(0, Math.min(1, t + offset))));
      }
      await page.evaluate((s) => window.__shoot(s), states);

      const shot = await page.$eval("#out", (el) => el.toDataURL("image/png"));
      await fs.writeFile(path.join(dir, `f${String(i).padStart(5, "0")}.png`),
                         Buffer.from(shot.split(",")[1], "base64"));
      if (i % 15 === 0) process.stdout.write(`\r  frame ${i}/${frames}`);
    }
    process.stdout.write(`\r  frame ${frames}/${frames}\n`);

    /*
      Where the screen is in the last frame, for the page to grow out of.

      Taken from the near plate, because at the end of the move the far one has
      been faded out entirely and is not in the picture.
    */
    const last = state(1);
    const rect = screenRect(PLATES.near, last.cropB);
    await fs.writeFile("media/room-end.json", `${JSON.stringify(rect, null, 2)}\n`);
    console.log(`  screen fills ${(rect.w * 100).toFixed(0)}% of the frame, ` +
                `centred at ${(rect.x * 100).toFixed(0)}%, ${(rect.y * 100).toFixed(0)}%`);

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
      "-y", "-framerate", String(fps), "-i", path.join(dir, "f%05d.png"),
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
