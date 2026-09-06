/*
  The last thirty metres, built rather than photographed.

  Google's tiles stop being usable somewhere around forty metres up. Measured on
  the descent, fine detail halves between eighty-five metres and forty-five and
  falls apart below thirty: at seventeen metres the brick drips and the window
  reveals are smears. The scan is flown imagery and there was never a clean line
  of sight into a narrow street, so there is nothing there to sharpen.

  The usual answer is to generate the last stretch and cut to it. This does the
  opposite: it puts a window and a room into the same scene, on the real
  building's own wall, and lets the same camera keep going. There is no cut to
  hide, no grade to match and no second renderer whose colour has to be brought
  into line — the failure mode that cost this project a day at the other seam.
  What covers the melted geometry is geometry, and it is in front of it.

  ## Where it goes

  Measured by scripts/probe-facade.mjs, which fires a fan of rays into the front
  the shot ends on and keeps the *face normals* rather than fitting a plane to
  the hit points. Fitting points fails here: a fan tall enough to matter crosses
  the roofline, and a plane through wall-and-roof comes back tilted thirty-eight
  degrees from vertical, which is a true description of a jumble and no use for
  standing anything on. Sixty-two of seventy-three rays land on near-vertical
  faces whose normals agree to within a few degrees, and averaging those gives
  the wall.

  ## Why everything here is unlit or its own light

  The tiles arrive as MeshBasicMaterial, which ignores every light in the scene.
  That is right for photogrammetry — the photograph already contains its own
  lighting — and it means the lights in this scene exist only because the loader
  expects them to. So the room can have whatever lighting it wants without
  touching the city around it: nothing in the tiles can see these lights, and
  nothing here has to match an exposure that was baked in years ago in a
  different city on a different afternoon.
*/
import * as THREE from "three";

/*
  Brick, drawn rather than downloaded.

  A texture file would be one more asset to ship, to cache-bust and to keep in
  step with a facade whose colour is measured from its surroundings. Drawn at
  load it is forty lines and takes a millisecond, and the courses can be sized
  in real metres so the bond reads correctly at the distance the camera actually
  passes it.
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
      const v = 0.82 + rand() * 0.36;
      c.multiplyScalar(v);
      c.offsetHSL((rand() - 0.5) * 0.02, (rand() - 0.5) * 0.08, 0);
      g.fillStyle = `#${c.getHexString()}`;
      g.fillRect(x + offset + 1.5, row * h + 1.5, w - 3, h - 3);
    }
  }

  // Grime down the courses, heavier low, which is what weather does to a wall.
  for (let i = 0; i < 400; i++) {
    const x = rand() * size;
    const y = rand() * size;
    g.fillStyle = `rgba(30,20,15,${0.02 + rand() * 0.05})`;
    g.fillRect(x, y, 20 + rand() * 90, 3 + rand() * 10);
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/*
  A rectangle with a rectangular hole in it, as four quads.

  Three has no hole in a PlaneGeometry and a Shape with a path punched out
  triangulates into a fan whose UVs do not tile — the brick ends up stretched
  around the opening, which is exactly where the eye is going. Four plain
  rectangles around the hole keep every UV square, at the cost of having to
  write out four rectangles.
*/
function wallWithHole({ width, height, hole, material }) {
  const group = new THREE.Group();
  const spans = [
    // left, right, below, above
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
    // Per-piece UVs, so the bond runs continuously across the whole wall
    // instead of restarting inside each rectangle.
    const uv = mesh.geometry.attributes.uv;
    for (let i = 0; i < uv.count; i++) {
      const u = uv.getX(i);
      const v = uv.getY(i);
      uv.setXY(i, (x0 + u * w) / METRES_PER_TILE, (y0 + v * h) / METRES_PER_TILE);
    }
    uv.needsUpdate = true;
    group.add(mesh);
  }
  return group;
}

// How much wall one repeat of the brick texture covers. Twenty-four courses to
// a tile at about 75 mm a course plus its bed is a shade under two metres.
const METRES_PER_TILE = 1.9;

const box = (w, h, d, material) =>
  new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);

/*
  The facade patch, the window, and the room behind it.

  `centre` and `normal` come from probe-facade. The group is placed at the wall
  and turned to face out along its normal, so everything inside is written in
  the natural frame: x across the wall, y up it, z out of it towards the street.
*/
export function buildRoom({ centre, normal, sill = 0 }) {
  const group = new THREE.Group();
  group.position.copy(centre);
  // Face the group's +Z along the wall's outward normal. lookAt points -Z at
  // the target, so the target is *behind* the group.
  group.lookAt(centre.clone().addScaledVector(normal, -1));
  group.rotateY(Math.PI);

  const WINDOW = { w: 1.15, h: 1.9, x: 0, y: sill };
  const ROOM = { w: 4.4, h: 2.9, d: 4.6 };

  const brickTex = brick();
  brickTex.repeat.set(1, 1);
  const brickMat = new THREE.MeshStandardMaterial({
    map: brickTex, roughness: 0.94, metalness: 0,
  });

  /*
    The patch is only as big as it needs to be.

    Wider than the frame at the moment the camera reaches it and no wider: what
    it is for is covering the melted brick the shot flies into, and every extra
    metre is another metre of edge that has to agree with the scan around it. At
    the speed this arrives, twelve by nine is comfortably outside the frame
    before the window fills it.
  */
  const patch = wallWithHole({
    width: 12, height: 9, material: brickMat,
    hole: { x: WINDOW.x, y: WINDOW.y, w: WINDOW.w, h: WINDOW.h },
  });
  // A hand's breadth proud of the scanned surface, so it wins the depth test
  // against the bumps rather than fighting them. The scan is flat to about two
  // metres over this patch, which is why it is this much and not a centimetre.
  patch.position.z = 1.2;
  group.add(patch);

  const trimMat = new THREE.MeshStandardMaterial({
    color: 0xe8e2d6, roughness: 0.7,
  });
  const frame = new THREE.Group();
  const T = 0.09;
  const jamb = [
    [WINDOW.w / 2 + T / 2, WINDOW.y, T, WINDOW.h + T * 2],
    [-WINDOW.w / 2 - T / 2, WINDOW.y, T, WINDOW.h + T * 2],
    [WINDOW.x, WINDOW.y + WINDOW.h / 2 + T / 2, WINDOW.w + T * 2, T],
  ];
  for (const [x, y, w, h] of jamb) {
    const m = box(w, h, 0.22, trimMat);
    m.position.set(x, y, 1.2);
    frame.add(m);
  }
  // Stone sill, proud of the wall and sloped, which is the detail that says
  // "pre-war" more than the brick does.
  const sillMesh = box(WINDOW.w + 0.5, 0.13, 0.42, trimMat);
  sillMesh.position.set(WINDOW.x, WINDOW.y - WINDOW.h / 2 - 0.06, 1.28);
  sillMesh.rotation.x = -0.05;
  frame.add(sillMesh);
  group.add(frame);

  /*
    The sash is up, and that is the whole reason there is a way in.

    A closed window means going through glass, which either looks like going
    through glass — a reflection, a refraction, a moment of nothing — or looks
    like a mistake. A raised lower sash is a rectangle of air with a room behind
    it, and it is what an apartment on a warm afternoon looks like anyway.
  */
  const glassMat = new THREE.MeshStandardMaterial({
    color: 0x223037, roughness: 0.18, metalness: 0.1,
    transparent: true, opacity: 0.55,
  });
  const upper = box(WINDOW.w - 0.06, WINDOW.h / 2 - 0.12, 0.05, glassMat);
  upper.position.set(WINDOW.x, WINDOW.y + WINDOW.h / 4 + 0.08, 1.14);
  group.add(upper);
  const rail = box(WINDOW.w, 0.11, 0.14, trimMat);
  rail.position.set(WINDOW.x, WINDOW.y + 0.02, 1.14);
  group.add(rail);

  // The room, as a box open towards the window. Back wall furthest from the
  // street, so the desk under the window has the wall behind the camera.
  const room = new THREE.Group();
  room.position.z = 1.2 - ROOM.d / 2;
  group.add(room);

  const wallMat = new THREE.MeshStandardMaterial({ color: 0xcfc4b4, roughness: 0.95 });
  const floorMat = new THREE.MeshStandardMaterial({ color: 0x6b4a30, roughness: 0.8 });
  const insideBrick = new THREE.MeshStandardMaterial({
    map: brick({ base: "#7d4634", seed: 19 }), roughness: 0.95,
  });

  const back = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.h), insideBrick);
  back.position.z = -ROOM.d / 2;
  room.add(back);
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.d), wallMat);
  ceiling.rotation.x = Math.PI / 2;
  ceiling.position.y = ROOM.h / 2;
  room.add(ceiling);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.w, ROOM.d), floorMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -ROOM.h / 2;
  room.add(ground);
  for (const side of [-1, 1]) {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(ROOM.d, ROOM.h), wallMat);
    wall.rotation.y = side * -Math.PI / 2;
    wall.position.x = side * ROOM.w / 2;
    room.add(wall);
  }

  /*
    The desk sits under the window with the laptop facing back at it, which is
    the one piece of blocking the whole shot depends on: the camera comes in
    through the window and the screen is what it arrives at.
  */
  const deskMat = new THREE.MeshStandardMaterial({ color: 0x8a6a4a, roughness: 0.6 });
  const desk = box(2.0, 0.06, 0.75, deskMat);
  desk.position.set(0.15, WINDOW.y - WINDOW.h / 2 - 0.35 - (1.2 - ROOM.d / 2 - room.position.z), ROOM.d / 2 - 0.55);
  desk.position.y = -0.62;
  room.add(desk);
  for (const dx of [-0.9, 0.9]) {
    const leg = box(0.06, 0.7, 0.06, deskMat);
    leg.position.set(0.15 + dx, -0.98, ROOM.d / 2 - 0.55);
    room.add(leg);
  }

  const shellMat = new THREE.MeshStandardMaterial({
    color: 0xb9bcc0, roughness: 0.35, metalness: 0.7,
  });
  /*
    The screen is black and stays black.

    The interface fades up inside this rectangle and then the rectangle scales
    off the edges of frame, so nothing ever has to line up. Anything drawn on it
    here is something the interface has to cover.
  */
  const screenMat = new THREE.MeshStandardMaterial({
    color: 0x08090b, roughness: 0.25, metalness: 0.2,
  });
  const laptop = new THREE.Group();
  const base = box(0.34, 0.014, 0.24, shellMat);
  laptop.add(base);
  const lid = box(0.34, 0.225, 0.012, shellMat);
  lid.position.set(0, 0.108, -0.115);
  lid.rotation.x = -0.20;
  laptop.add(lid);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.305, 0.195), screenMat);
  screen.position.set(0, 0.108, -0.108);
  screen.rotation.x = -0.20;
  laptop.add(screen);
  laptop.position.set(0.15, -0.585, ROOM.d / 2 - 0.6);
  laptop.rotation.y = Math.PI;          // facing the window, and the camera
  room.add(laptop);
  group.userData.screen = screen;

  // The things that make a room somebody's rather than a set.
  const bottle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.037, 0.037, 0.24, 20),
    new THREE.MeshStandardMaterial({ color: 0x2f6d63, roughness: 0.3, metalness: 0.6 }));
  bottle.position.set(-0.42, -0.47, ROOM.d / 2 - 0.62);
  room.add(bottle);
  const mug = new THREE.Mesh(
    new THREE.CylinderGeometry(0.043, 0.038, 0.095, 18),
    new THREE.MeshStandardMaterial({ color: 0xd8d2c6, roughness: 0.7 }));
  mug.position.set(0.72, -0.545, ROOM.d / 2 - 0.68);
  room.add(mug);
  const books = new THREE.Group();
  const spines = [0x7a2f2f, 0x2c3f63, 0xd9c48a];
  spines.forEach((c, i) => {
    const b = box(0.21, 0.042, 0.29,
      new THREE.MeshStandardMaterial({ color: c, roughness: 0.8 }));
    b.position.set(-0.72, -0.568 + i * 0.045, ROOM.d / 2 - 0.66);
    b.rotation.y = 0.06 * (i - 1);
    books.add(b);
  });
  room.add(books);

  /*
    A banner and posters, as colour and shape.

    No lettering anywhere. A wall of invented type is the single clearest tell
    that a picture was made rather than taken, and it is worse here than in a
    generated frame because there is no excuse for it: the banner reads as Rice
    from its colours and its proportions, and the posters are allowed to be
    posters without being about anything.
  */
  const banner = new THREE.Mesh(new THREE.PlaneGeometry(1.25, 0.62),
    new THREE.MeshStandardMaterial({ color: 0x00205b, roughness: 0.85 }));
  banner.position.set(-0.15, 0.42, -ROOM.d / 2 + 0.02);
  room.add(banner);
  const bannerBand = new THREE.Mesh(new THREE.PlaneGeometry(1.25, 0.1),
    new THREE.MeshStandardMaterial({ color: 0xc1c6c8, roughness: 0.85 }));
  bannerBand.position.set(-0.15, 0.30, -ROOM.d / 2 + 0.03);
  room.add(bannerBand);
  const posters = [
    [0.95, 0.30, 0.52, 0.72, 0x2b3a2f],
    [1.02, -0.34, 0.44, 0.60, 0x6a3a2c],
    [-1.15, 0.10, 0.40, 0.54, 0x3a3550],
  ];
  for (const [x, y, w, h, c] of posters) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshStandardMaterial({ color: c, roughness: 0.9 }));
    p.position.set(x, y, -ROOM.d / 2 + 0.02);
    room.add(p);
  }

  /*
    Light, and this is free because nothing in the city can see it.

    The tiles are MeshBasicMaterial and ignore every light in the scene, so a
    lamp put in here changes the room and changes nothing else. Two sources: the
    afternoon coming in over the camera's shoulder through the window, which is
    what makes the room read as continuous with the street outside, and a warm
    one deeper in so the back wall is not a silhouette.
  */
  const daylight = new THREE.DirectionalLight(0xfff2e0, 2.6);
  daylight.position.set(0.6, 0.8, 3);
  room.add(daylight);
  const lamp = new THREE.PointLight(0xffcf9a, 6, 7, 2);
  lamp.position.set(0.9, 0.35, ROOM.d / 2 - 1.4);
  room.add(lamp);
  const fill = new THREE.AmbientLight(0x9fb0c4, 0.55);
  room.add(fill);

  return group;
}
