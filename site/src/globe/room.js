/*
  The last thirty metres, built rather than photographed, in two halves that
  never meet.

  Google's tiles stop being usable somewhere around forty metres up. Measured on
  the descent, fine detail halves between eighty-five metres and forty-five and
  falls apart below thirty: at seventeen metres the brick drips and the window
  reveals are smears. The scan is flown imagery and there was never a clean line
  of sight into a narrow street, so there is nothing there to sharpen.

  ## Two findings decided the shape of this

  **The windows in the scan are painted on.** They are texture on a flat wall,
  not openings. probe-opening.mjs went looking for something to fly into by
  casting a grid at the facade and keeping what was both set back and dark, and
  everything with a real recess — four and a half metres of it — turned out to be
  a gap between buildings. Flying at the best candidate ended up looking at the
  skyline over a roof, at a mean brightness of 97. There is no hole in that wall.

  **The scan is solid where a room would be.** The first version put a whole
  interior behind the wall in the tiles' own scene, so one camera could carry
  through without a cut. A metre inside it, Google's geometry cut straight
  across the desk: the building it reconstructed occupies that space, and no
  amount of careful placement helps, because the room is inside a mesh.

  ## So: two halves, and only one of them is ever in the city

  `buildFacade` goes into the tiles' scene. It is a patch of brick with a window
  in it and a shallow black box behind — a recess, not a room. There is nothing
  to intersect with, because there is nothing behind it but dark. It is unlit,
  like the tiles themselves, so its colour can be matched to the wall it stands
  on directly rather than through a lighting model.

  The room goes in behind that window, in the same group — which only works
  because that pass discards the depth buffer first. In the city's own scene the
  building's reconstructed volume cuts straight through an interior placed
  there; drawn after the city with depth thrown away, nothing the scan holds can
  reach it. So the camera flies through the window and keeps going, and there is
  no cut anywhere in the intro at all.
*/
import * as THREE from "three";

// How much wall one repeat of the brick texture covers. Twenty-four courses to
// a tile at about 75 mm a course plus its bed is a shade under two metres.
const METRES_PER_TILE = 1.9;

/*
  Brick, drawn rather than downloaded.

  A texture file would be one more asset to ship, to cache-bust, and to keep in
  step with a facade whose colour is measured off its surroundings at run time
  and is therefore not known when the file would have been made. Drawn at load
  it is forty lines and a millisecond, and the courses can be sized in real
  metres so the bond reads correctly at the distance the camera passes it.
*/
function brick({ base = "#8d4a37", mortar = "#9a8a7c", seed = 7 } = {}) {
  const COURSES = 24;
  const size = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const g = canvas.getContext("2d");

  g.fillStyle = mortar;
  g.fillRect(0, 0, size, size);

  // Deterministic, because a facade that is different on every render is a
  // facade that cannot be compared against the last one.
  let s = seed;
  const rand = () => {
    s = (s * 1103515245 + 12345) % 2147483648;
    return s / 2147483648;
  };

  const h = size / COURSES;
  const w = h * 2.4;                    // a brick is about two and a half high
  const rgb = new THREE.Color(base);
  for (let row = 0; row < COURSES; row++) {
    const offset = row % 2 ? w / 2 : 0; // stretcher bond
    for (let x = -w; x < size + w; x += w) {
      const c = rgb.clone();
      // Bricks vary, and a wall of one colour reads as plastic.
      c.multiplyScalar(0.82 + rand() * 0.36);
      c.offsetHSL((rand() - 0.5) * 0.02, (rand() - 0.5) * 0.08, 0);
      g.fillStyle = `#${c.getHexString()}`;
      g.fillRect(x + offset + 1.5, row * h + 1.5, w - 3, h - 3);
    }
  }

  // Grime along the courses, which is what weather does to a wall and what
  // stops a hundred rectangles reading as a hundred rectangles.
  for (let i = 0; i < 500; i++) {
    g.fillStyle = `rgba(30,20,15,${0.02 + rand() * 0.05})`;
    g.fillRect(rand() * size, rand() * size, 20 + rand() * 90, 3 + rand() * 10);
  }

  /*
    Mottling, at a scale much larger than a brick.

    Without it the wall is even, and even is the tell. Photogrammetry of a real
    building is never even: it carries the weather, the repointing, the shadow
    of a fire escape that was there when the plane went over. A hundred soft
    blobs a metre or two across, half of them lighter and half darker, give the
    surface something at the scale the eye reads a wall at — which is not the
    scale of a brick.
  */
  for (let i = 0; i < 110; i++) {
    const x = rand() * size;
    const y = rand() * size;
    const r = size * (0.04 + rand() * 0.16);
    const dark = rand() < 0.55;
    const blob = g.createRadialGradient(x, y, 0, x, y, r);
    const a = 0.05 + rand() * 0.09;
    blob.addColorStop(0, dark ? `rgba(24,16,10,${a})` : `rgba(226,208,182,${a * 0.8})`);
    blob.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = blob;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/*
  A rectangle with a rectangular hole in it, as four quads.

  Three has no hole in a PlaneGeometry, and a Shape with a path punched out of
  it triangulates into a fan whose UVs do not tile — the brick ends up stretched
  around the opening, which is precisely where the eye is going. Four plain
  rectangles keep every UV square, at the cost of writing out four rectangles.
*/
function wallWithHole({ width, height, hole, material }) {
  const group = new THREE.Group();
  const spans = [
    [-width / 2, hole.x - hole.w / 2, -height / 2, height / 2],
    [hole.x + hole.w / 2, width / 2, -height / 2, height / 2],
    [hole.x - hole.w / 2, hole.x + hole.w / 2, -height / 2, hole.y - hole.h / 2],
    [hole.x - hole.w / 2, hole.x + hole.w / 2, hole.y + hole.h / 2, height / 2],
  ];
  for (const [x0, x1, y0, y1] of spans) {
    const w = x1 - x0;
    const h = y1 - y0;
    if (w <= 0.001 || h <= 0.001) continue;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), material);
    mesh.position.set((x0 + x1) / 2, (y0 + y1) / 2, 0);
    // UVs in wall coordinates, so the bond runs continuously across the whole
    // patch instead of restarting inside each of the four pieces.
    const uv = mesh.geometry.attributes.uv;
    for (let i = 0; i < uv.count; i++) {
      uv.setXY(i,
        (x0 + uv.getX(i) * w) / METRES_PER_TILE,
        (y0 + uv.getY(i) * h) / METRES_PER_TILE);
    }
    uv.needsUpdate = true;
    group.add(mesh);
  }
  return group;
}

const box = (w, h, d, material) =>
  new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);

// The opening, in metres. A sash window in a pre-war walk-up, and the size the
// camera has to fit through.
export const WINDOW = { w: 1.24, h: 2.0 };

// How far the patch stands proud of the scanned wall, exported so the camera
// can be told where the window plane actually is.
export const PROUD = 1.3;


/*
  The patch of facade, in the city's scene.

  `centre` and `normal` come from probe-facade, which fits the wall from face
  normals rather than from hit points — a fan of rays tall enough to matter
  crosses the roofline, and a plane through wall-and-roof comes back tilted
  thirty-eight degrees from vertical, a true description of a jumble and no use
  for standing anything on.

  The group is placed at the wall and turned to face out along its normal, so
  everything inside is written in the natural frame: x across the wall, y up it,
  z out of it towards the street.
*/
export function buildFacade({ centre, normal, colour = "#8d4a37", screenImage = null }) {
  const group = new THREE.Group();
  group.position.copy(centre);
  // Face the group's +Z along the outward normal. lookAt points -Z at its
  // target, so the target goes behind.
  /*
    Faced out along the wall's normal, and that is all.

    lookAt points an object's -Z at its target, so a target behind the wall puts
    +Z out of it, which is the way the patch has to face. A half turn was added
    on top of that at one point and it was wrong twice over: it left the patch
    facing outwards only by accident of the up vector, and it put the room
    behind the camera. Rendered on its own the scene had all seventy-six of its
    meshes and all five of its lights and showed the background colour, because
    the walls were the other side of the lens.
  */
  group.lookAt(centre.clone().addScaledVector(normal, -1));
  group.rotateY(Math.PI);

  /*
    Unlit, and matched to the wall it stands on.

    The tiles arrive as MeshBasicMaterial: they ignore every light in the scene,
    because a photograph already contains its own. A lit patch sits in a
    different world from the brick around it however carefully its colour is
    picked — it answers to a sun the rest of the street cannot see. Unlit, the
    colour sampled off the scanned wall is the colour that comes out, and the
    grade then treats the two identically because it cannot tell them apart.
  */
  const brickMat = new THREE.MeshBasicMaterial({
    map: brick({ base: colour }),
    // Faded in over the photographed brick rather than swapped for it. See
    // where the opacity is driven, in Manhattan.place.
    transparent: true, opacity: 0,
  });

  /*
    Wide enough to be outside the frame by the time it matters.

    Twelve by nine looked like a rectangle pasted onto the building when the
    camera was twenty-six metres out, and it was: at that distance its edges are
    well inside frame and the eye has both the patch and the scan to compare.
    The answer is not a bigger patch on its own, which only moves the edges, but
    arriving faster: the push starts at fourteen metres, and at fourteen metres
    a thirty by twenty-two patch is half again as wide as the frame in both
    directions. From there on the edges are further outside it every metre.

    That margin is also what lets the city stop being drawn during the push. See
    where the tiles are hidden, in place().
  */
  const patch = wallWithHole({
    width: 30, height: 22, material: brickMat,
    hole: { x: 0, y: 0, w: WINDOW.w, h: WINDOW.h },
  });
  patch.position.z = PROUD;
  group.add(patch);

  const trimMat = new THREE.MeshBasicMaterial({
    color: 0x9c917f, transparent: true, opacity: 0,
  });
  const T = 0.1;
  for (const [x, y, w, h] of [
    [WINDOW.w / 2 + T / 2, 0, T, WINDOW.h + T * 2],
    [-WINDOW.w / 2 - T / 2, 0, T, WINDOW.h + T * 2],
    [0, WINDOW.h / 2 + T / 2, WINDOW.w + T * 2, T],
  ]) {
    const m = box(w, h, 0.24, trimMat);
    m.position.set(x, y, PROUD);
    group.add(m);
  }
  // Stone sill, proud and slightly sloped, which says pre-war more than the
  // brick does.
  const sill = box(WINDOW.w + 0.55, 0.14, 0.44, trimMat);
  sill.position.set(0, -WINDOW.h / 2 - 0.07, PROUD + 0.08);
  sill.rotation.x = -0.05;
  group.add(sill);

  /*
    The sash is up, and that is the whole reason there is a way in.

    A closed window means going through glass, which either looks like going
    through glass — a reflection, a refraction, a moment of nothing — or looks
    like a mistake. A raised lower sash is a rectangle of air with darkness
    behind it, and it is what an apartment on a warm afternoon looks like.
  */
  const glass = box(WINDOW.w - 0.07, WINDOW.h / 2 - 0.14, 0.04,
    new THREE.MeshBasicMaterial({
      color: 0x2a3a44, transparent: true, opacity: 0.5,
    }));
  glass.position.set(0, WINDOW.h / 4 + 0.09, PROUD - 0.06);
  group.add(glass);
  const rail = box(WINDOW.w, 0.12, 0.16, trimMat);
  rail.position.set(0, 0.03, PROUD - 0.06);
  group.add(rail);

  /*
    There is no recess any more, and there was one.

    It was a shallow black box behind the opening, put there when the plan was
    to fly at the window, go dark, and cut to the interior somewhere in that
    darkness. The room replaced it and it stayed — three metres of near-black
    box, drawn over the top of everything behind it, wrapping the camera as it
    came through the opening. The room was rendering the whole time and was
    inside a lightless box.

    That cost several passes to find, because every check said the room was
    correct: seventy-six meshes present, five lights present, bounds where they
    should be, geometry the right way round, the camera inside them. Casting a
    ray through a corner of the frame and asking what it hit named it in one
    line.
  */

  /*
    The reveal is four slabs, not a box.

    A box with BackSide draws its far face too, and that face is a wall a third
    of a metre inside the opening: the camera arrives at a quarter of a metre
    out and finds it filling two thirds of the frame in reveal-brown instead of
    finding the dark. Measured, the last frame came back at 64 where it should
    have been under 20, and it came back split — pale above, black below —
    which is what a wall across the opening looks like.

    Four slabs leave the way in open. Dark, so the opening is already dimming
    for a second before it goes black rather than dropping in one step.
  */
  const revealMat = new THREE.MeshBasicMaterial({ color: 0x2b2620 });
  const D = 0.34;
  for (const [w, h, x, y] of [
    [0.02, WINDOW.h, WINDOW.w / 2, 0],
    [0.02, WINDOW.h, -WINDOW.w / 2, 0],
    [WINDOW.w, 0.02, 0, WINDOW.h / 2],
    [WINDOW.w, 0.02, 0, -WINDOW.h / 2],
  ]) {
    const slab = box(w, h, D, revealMat);
    slab.position.set(x, y, PROUD - D / 2);
    group.add(slab);
  }

  /*
    The neighbours, painted on rather than built.

    One window in a blank wall reads as one window in a blank wall. At six
    metres out the frame is eight metres across, which on a tenement is three
    bays, so the ones either side are on screen for the whole approach and their
    absence is more conspicuous than any amount of brick detail.

    They are flat dark rectangles with a trim border and nothing behind them,
    which is exactly what the windows in Google's own imagery are. There is only
    one opening on this wall and the camera is going through it.
  */
  const paintedGlass = new THREE.MeshBasicMaterial({
    color: 0x161a1f, transparent: true, opacity: 0,
  });
  for (const [x, y] of [
    [-3.05, 0], [3.05, 0],
    [-3.05, 3.3], [0, 3.3], [3.05, 3.3],
    [-3.05, -3.3], [0, -3.3], [3.05, -3.3],
  ]) {
    const border = new THREE.Mesh(
      new THREE.PlaneGeometry(WINDOW.w + 0.2, WINDOW.h + 0.2), trimMat);
    border.position.set(x, y, PROUD + 0.01);
    group.add(border);
    const pane = new THREE.Mesh(
      new THREE.PlaneGeometry(WINDOW.w, WINDOW.h), paintedGlass);
    pane.position.set(x, y, PROUD + 0.02);
    group.add(pane);
    const ledge = box(WINDOW.w + 0.5, 0.13, 0.4, trimMat);
    ledge.position.set(x, y - WINDOW.h / 2 - 0.07, PROUD + 0.08);
    group.add(ledge);
  }

  // Every material that fades in together, so place() can drive one number.
  /*
    And the room, behind the window, in the same group.

    This is only possible because the patch is drawn in a second pass with the
    depth buffer cleared — see Manhattan.render. In the tiles' own scene the
    building's reconstructed volume cuts straight through an interior placed
    here, which is what killed the first attempt. Drawn after the city with
    depth discarded, nothing the scan contains can reach it, and the camera can
    fly through the window without a cut of any kind.
  */
  const ROOM = { w: 4.6, h: 3.0, d: 5.0 };
  const room = new THREE.Group();
  // The window sits above the middle of the room's front wall, because a window
  // in a room does: the sill is at desk height and there is wall below it.
  room.position.set(0, -0.42, PROUD - 0.34);
  group.add(room);

  const wallMat = new THREE.MeshStandardMaterial({ color: 0xcabfae, roughness: 0.95 });
  const floorMat = new THREE.MeshStandardMaterial({ color: 0x6d4c31, roughness: 0.75 });
  const insideBrick = new THREE.MeshStandardMaterial({
    map: brick({ base: "#7d4634", seed: 19 }), roughness: 0.95,
  });

  const back = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.h), insideBrick);
  back.position.z = -ROOM.d;
  room.add(back);
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.d), wallMat);
  ceiling.rotation.x = Math.PI / 2;
  ceiling.position.set(0, ROOM.h / 2, -ROOM.d / 2);
  room.add(ceiling);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.d), floorMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(0, -ROOM.h / 2, -ROOM.d / 2);
  room.add(ground);
  for (const side of [-1, 1]) {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.d, ROOM.h), wallMat);
    wall.rotation.y = side * -Math.PI / 2;
    wall.position.set(side * ROOM.w / 2, 0, -ROOM.d / 2);
    room.add(wall);
  }

  /*
    The desk under the window with the laptop facing back at it. This is the
    blocking the whole shot depends on: the camera comes in through the window
    and the screen is what it arrives at.
  */
  const deskMat = new THREE.MeshStandardMaterial({ color: 0x8a6a4a, roughness: 0.6 });
  const DESK = { y: -0.2, z: -1.25 };
  const desk = box(2.1, 0.055, 0.8, deskMat);
  desk.position.set(0.06, DESK.y, DESK.z);
  room.add(desk);
  for (const dx of [-0.92, 0.92]) {
    const leg = box(0.055, 1.3, 0.055, deskMat);
    leg.position.set(0.06 + dx, DESK.y - 0.68, DESK.z);
    room.add(leg);
  }

  const shellMat = new THREE.MeshStandardMaterial({
    color: 0xb9bcc0, roughness: 0.35, metalness: 0.6,
  });
  /*
    The interface is on the screen before the camera gets there.

    It used to be black, to be faded up inside the bezel once the shot ended.
    That is two events — a shot that finishes, then a screen that lights up —
    and the join between them is exactly the kind of thing this intro has spent
    its whole length avoiding. On from the start, the arrival is one move that
    ends with the page filling the frame, and the handoff has nothing to line up
    because the thing being scaled is the thing it becomes.

    The texture is the real page, screenshotted by scripts/capture-ui.mjs, not
    an approximation of it.
  */
  const screenMat = new THREE.MeshBasicMaterial({ color: 0x0b0c0f });
  if (screenImage) {
    const tex = new THREE.TextureLoader().load(screenImage);
    tex.colorSpace = THREE.SRGBColorSpace;
    screenMat.map = tex;
    screenMat.color.set(0xffffff);
  }
  const laptop = new THREE.Group();
  laptop.add(box(0.345, 0.014, 0.245, shellMat));
  const lid = box(0.345, 0.235, 0.012, shellMat);
  lid.position.set(0, 0.112, -0.12);
  lid.rotation.x = -0.17;
  laptop.add(lid);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.318, 0.2), screenMat);
  screen.position.set(0, 0.112, -0.113);
  screen.rotation.x = -0.17;
  laptop.add(screen);
  /*
    Not turned round.

    The lid is built behind the base and the screen faces the group's +Z, which
    is already the way the window is. Rotating the whole laptop a half turn to
    "face the camera" put the lid between the camera and the screen and pointed
    the screen at the back wall — the shot flew in and arrived at a grey lid
    with a lamp reflection on it.
  */
  laptop.position.set(0.06, DESK.y + 0.035, DESK.z - 0.03);
  room.add(laptop);

  const bottle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.037, 0.037, 0.25, 20),
    new THREE.MeshStandardMaterial({ color: 0x2f6d63, roughness: 0.3, metalness: 0.5 }));
  bottle.position.set(-0.52, DESK.y + 0.15, DESK.z + 0.1);
  room.add(bottle);
  const mug = new THREE.Mesh(
    new THREE.CylinderGeometry(0.043, 0.038, 0.095, 18),
    new THREE.MeshStandardMaterial({ color: 0xd8d2c6, roughness: 0.7 }));
  mug.position.set(0.66, DESK.y + 0.075, DESK.z + 0.16);
  room.add(mug);
  [0x7a2f2f, 0x2c3f63, 0xd9c48a].forEach((c, i) => {
    const b = box(0.22, 0.042, 0.3,
      new THREE.MeshStandardMaterial({ color: c, roughness: 0.8 }));
    b.position.set(-0.8, DESK.y + 0.05 + i * 0.045, DESK.z + 0.03);
    b.rotation.y = 0.07 * (i - 1);
    room.add(b);
  });
  for (const [x, z, r] of [[0.6, DESK.z + 0.26, 0.4], [0.4, DESK.z + 0.32, -0.9]]) {
    const sheet = new THREE.Mesh(new THREE.PlaneGeometry(0.21, 0.29),
      new THREE.MeshStandardMaterial({ color: 0xe9e4d8, roughness: 0.9 }));
    sheet.rotation.set(-Math.PI / 2, 0, r);
    sheet.position.set(x, DESK.y + 0.031, z);
    room.add(sheet);
  }

  /*
    A banner and posters, as colour and shape.

    No lettering anywhere. A wall of invented type is the clearest tell that a
    picture was made rather than taken, and there is no excuse for it here: the
    banner reads as Rice from its colours and proportions, and the posters are
    allowed to be posters without being about anything.
  */
  const flat = (w, h, color) => new THREE.Mesh(new THREE.PlaneGeometry(w, h),
    new THREE.MeshStandardMaterial({ color, roughness: 0.88 }));
  const banner = flat(1.3, 0.64, 0x00205b);
  banner.position.set(-0.35, 0.62, -ROOM.d + 0.02);
  room.add(banner);
  const band = flat(1.3, 0.1, 0xc1c6c8);
  band.position.set(-0.35, 0.5, -ROOM.d + 0.03);
  room.add(band);
  for (const [x, y, w, h, c] of [
    [0.95, 0.54, 0.54, 0.74, 0x2b3a2f],
    [1.05, -0.28, 0.46, 0.62, 0x6a3a2c],
    [-1.4, 0.26, 0.42, 0.56, 0x3a3550],
  ]) {
    const p = flat(w, h, c);
    p.position.set(x, y, -ROOM.d + 0.02);
    room.add(p);
  }
  let seed = 3;
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  for (let i = 0; i < 14; i++) {
    const card = flat(0.09 + rand() * 0.05, 0.06 + rand() * 0.05,
      [0xe8e2d2, 0xd9c9a8, 0xbfc9c4][i % 3]);
    card.position.set(-1.9 + rand() * 3.6, -0.55 + rand() * 1.5, -ROOM.d + 0.025);
    card.rotation.z = (rand() - 0.5) * 0.22;
    room.add(card);
  }

  /*
    Light, and none of it can reach the city, because the city is in the other
    scene entirely.

    Two sources: the afternoon coming in over the camera's shoulder through the
    window, which is what makes the room continuous with the street it was just
    outside, and a warm one deeper in so the back wall is not a silhouette.
  */
  /*
    A directional light aims at its target, and its target is not where it is.

    DirectionalLight.target defaults to an Object3D at the world origin, and the
    world origin here is the point on the ellipsoid the whole tileset was moved
    to — twenty-odd metres away and outside the building. So the daylight was
    pointing out of the room and across the street, and the render came back
    with a lit desk edge and everything else black.

    Given a target of its own, inside the room, it does what it is for: afternoon
    coming in over the camera's shoulder through the window.
  */
  const aim = new THREE.Object3D();
  aim.position.set(0, -0.3, -ROOM.d * 0.7);
  room.add(aim);
  /*
    Set by measurement, after a false trail worth recording.

    The room rendered black, so these were raised tenfold on the theory that
    Three's physical light units needed it. Brightness did go up, and the room
    stayed black, because the room was inside a lightless box — see the note
    where the recess used to be. With the box gone the original values were
    close to right and the raised ones blew every surface to white.

    A measured value that moves in the direction you expect is not the same as
    the right explanation.
  */
  const daylight = new THREE.DirectionalLight(0xfff2e0, 2.4);
  daylight.position.set(0.6, 1.1, 2.6);
  daylight.target = aim;
  room.add(daylight);
  // A second, weaker one from the other side, so the walls the daylight misses
  // are dim rather than absent.
  const bounce = new THREE.DirectionalLight(0xbcd0e4, 0.8);
  bounce.position.set(-2.2, 0.4, -1.2);
  bounce.target = aim;
  room.add(bounce);
  const lamp = new THREE.PointLight(0xffcf9a, 9, 10, 2);
  lamp.position.set(0.95, 0.55, -2.1);
  room.add(lamp);
  // A soft one straight down as well, so the floor and the desk are not lit
  // only from the window, and the room reads as a room rather than as a lit
  // desk in a void.
  const overhead = new THREE.PointLight(0xf0efe6, 14, 14, 2);
  overhead.position.set(-0.2, 1.25, -2.2);
  room.add(overhead);
  room.add(new THREE.AmbientLight(0xa8b6c6, 0.45));

  // Every material that fades in together, so place() drives one number.
  group.userData.fading = [brickMat, trimMat, paintedGlass, glass.material];
  group.userData.screen = screen;
  group.userData.screenWorld = () => screen.getWorldPosition(new THREE.Vector3());
  // Which way the screen faces, so the camera can finish square on to it. A
  // PlaneGeometry faces its own +Z, which is what getWorldDirection returns.
  group.userData.screenNormal = () => screen.getWorldDirection(new THREE.Vector3());
  group.userData.windowWorld = group.localToWorld(new THREE.Vector3(0, 0, PROUD));
  return group;
}
