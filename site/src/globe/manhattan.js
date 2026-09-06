/*
  The descent: real Manhattan, streamed as photogrammetry.

  This is the piece the globe cannot do. Its textures are 2048 pixels around
  the equator, so there is nothing to look at below roughly a hundred
  kilometres, and no camera work invents detail that is not in the data. The
  globe's own flight stops in orbit for that reason.

  Google's Photorealistic 3D Tiles are the data: actual scanned geometry of
  real cities, served as the open 3D Tiles standard. NASA JPL's renderer
  streams them into an ordinary three.js scene, which means this can share the
  same renderer and the same camera as the globe and the join between them is a
  camera move rather than a cut.

  ## Coordinates

  The tiles live in ECEF, an earth-centred frame in metres where the origin is
  the middle of the planet and nothing is conveniently oriented. Working in it
  directly means every position is a seven-digit number and every "up" is a
  different direction.

  The fix is to put the *whole tileset* where the chosen point lands at the
  origin, by building the frame for that latitude and longitude and inverting
  it. `WGS84_ELLIPSOID.getObjectFrame` gives the matrix that would place an
  object at a point on the globe; applying its inverse to the tiles brings that
  point to the origin instead, with the sky up the Y axis. That turns the
  problem back into the one everybody knows: a camera at some height above a
  place, looking at something.

  A first version called `tiles.setLatLonToYUp`, which is an API this library
  used to have and does not. It was written from memory rather than from the
  package, and it failed on the first live run.

  ## Cost

  Billed per session, and a session starts when the root tileset is requested.
  So the tiles are not loaded until the descent actually begins: a visitor who
  never presses anything costs nothing. That is also why the key is read at
  call time rather than at import.
*/
import * as THREE from "three";
import { TilesRenderer, WGS84_ELLIPSOID } from "3d-tiles-renderer";
import { GoogleCloudAuthPlugin, TilesFadePlugin } from "3d-tiles-renderer/plugins";
import { HANDOVER, fallHeight } from "./handover.js";
import { PLATE_LUT } from "./plate-lut.js";
import { buildFacade, PROUD } from "./room.js";

// Lower Manhattan, looking north up the island. Chosen because the skyline
// reads as New York from almost any angle here, which a residential street
// further uptown would not.
export const MANHATTAN = { lat: 40.7061, lon: -74.0087 };

/*
  Defocus at the handover, as a fraction of frame width.

  A fraction and not a count of pixels, which is how it was written first and is
  a trap this project walked straight into. The probe renders at 960 wide and
  the real render at 1920, so the same pixel radius was twice as strong in the
  thing being measured as in the thing being shipped. The number was tuned on
  the probe, looked right, and went out at half strength.

  Set by matching mean absolute Laplacian — plainly, how much fine detail a
  frame holds — against the globe's own value at the moment it hands over.
*/
const SOFT = 5 / 1920;

/*
  Where the descent stops, found by scripts/probe-window.mjs rather than chosen.

  The shot has to end level with a window on an upper floor of a tenement, and
  none of the three numbers that requires can be read off a latitude and a
  longitude. The target point turns out to be *inside* a building at that
  height, with a wall 2.1 m away on almost every bearing, so falling to the
  origin and turning gives a camera in a wall.

  So the block was searched: a grid of positions at seventeen metres, discarding
  anywhere with less than nine metres clear around it, then the nearest building
  front on each. The first search asked for a front between twelve and thirty
  metres and every result was unusable — at that range Google's scan has no
  windows in it at all, only a smooth pale blob, because it never had a clean
  line of sight down a narrow street. From about thirty metres the tenements
  come back: window reveals, fire escapes, the courses in the brick.

  Seventeen metres is a fifth-floor window in a six-storey walk-up, which is
  what this block is made of.
*/
const END = {
  /*
    Where the shot finishes, measured by scripts/probe-opening.mjs and written
    down rather than recomputed.

    The window goes on the flattest brick the survey could find at fifth-floor
    height — 67 mm of roughness across a two-metre patch, against several
    hundred elsewhere on the same wall — so the patch sits down on the scan
    instead of hovering over a bulge. Not on one of the dark rectangles in the
    imagery: those are painted on, and a built window over a painted one is two
    windows in the same place.

    x and z are absolute in the tileset's frame, which does not move. The height
    is metres above the street, because the street is the thing this shot is
    written relative to and it is measured every run.
  */
  x: -23.67,
  z: 6.07,
  height: 16.0,
  // The wall's outward normal, from the average of sixty-odd near-vertical face
  // normals, flattened to plumb.
  normal: [-0.5953, 0, 0.8035],
  // The brick, sampled off the scanned wall around the window with the darkest
  // fifth thrown away — the painted-on windows are part of that wall and
  // averaging them in makes the patch too dark.
  brick: "#b37359",
  // Metres from the window plane: where the push begins, and where it ends.
  // Negative because it ends inside — the camera goes through the window and
  // settles at the desk, where a person would sit.
  standoff: 14,
  arrive: -1.13,
};

/*
  The tone curve as a texture rather than as an array uniform.

  A uniform array of 96 floats is within every limit that matters, but sampling
  it needs a dynamic index into an array, which is exactly the construct older
  GLSL compilers refuse or unroll badly. A 64-wide RGB texture with linear
  filtering is one fetch per channel, interpolates between entries for free, and
  cannot be miscompiled.
*/
function plateLut() {
  const n = PLATE_LUT.r.length;
  const data = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) {
    data[i * 4 + 0] = Math.round(255 * PLATE_LUT.r[i]);
    data[i * 4 + 1] = Math.round(255 * PLATE_LUT.g[i]);
    data[i * 4 + 2] = Math.round(255 * PLATE_LUT.b[i]);
    data[i * 4 + 3] = 255;
  }
  const tex = new THREE.DataTexture(data, n, 1, THREE.RGBAFormat);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  return tex;
}

// The street, or zero while it is still unknown. render() needs it to hang the
// cloud deck at a fixed height above the ground rather than above the ellipsoid.
const floorOf = (m) => m.groundLevel() ?? 0;

export class Manhattan {
  constructor(renderer, camera) {
    this.renderer = renderer;
    this.camera = camera;
    this.scene = new THREE.Scene();
    this.tiles = null;
    this.ready = false;
  }

  /* Nothing is requested until this is called, because requesting the root
     tileset is what starts a billed session. */
  /*
    `fade` is on for a visitor and off for a render.

    TilesFadePlugin dissolves one level of detail into the next so a building
    does not appear whole in front of the camera. It does that with a dithered
    alpha — a checkerboard of pixels that switches over during the fade — which
    is the right trick live, where it lasts 400 ms and reads as softness.

    Offscreen it is only damage. Every frame waits until nothing is downloading
    or parsing before it is photographed, so there is no pop-in to hide, and
    each frame catches whatever dither pattern happened to be mid-transition: a
    stipple over the whole city that changes shape frame to frame. It is the
    most conspicuous artifact in the footage, and it is guarding against a
    problem the renderer has already solved.
  */
  /*
    `errorTarget` is how much screen-space error a tile is allowed before a
    finer one is fetched, in pixels. Google's auth plugin sets it to 20, which
    is right for a visitor on a phone and much too coarse for a render.

    It is what the buildings glitching is. Twenty pixels of allowed error means
    each level of detail is held until it is quite wrong, so when the next one
    arrives it arrives as a large change: measured on the descent, the frame
    gained twenty per cent of its fine detail and three or four levels of
    brightness inside a tenth of a second, several times on the way down. There
    is no fade to hide it — TilesFadePlugin is off for renders, because its
    dithered alpha stipples every settled frame — and there should not need to
    be. A pop that has to be hidden is a pop that was allowed to get too big.

    At four the tileset is close to its best everywhere, so the switches happen
    higher up the tree and each one moves the picture much less. It costs
    download time, which offline is the cheapest thing there is.
  */
  async load({ fade = true, errorTarget = fade ? null : 4 } = {}) {
    const key = import.meta.env.VITE_GOOGLE_MAPS_KEY;
    if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");

    const tiles = new TilesRenderer();
    tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: key }));
    // Tiles pop in as they arrive otherwise, and a building appearing whole in
    // front of the camera is the one thing that says "streaming" out loud.
    if (fade) tiles.registerPlugin(new TilesFadePlugin({ fadeDuration: 400 }));

    // After the plugin, not before: GoogleCloudAuthPlugin sets this itself when
    // it is registered, so anything set earlier is silently replaced.
    if (errorTarget !== null) tiles.errorTarget = errorTarget;
    // Kept, because render() tightens it further near the ground. See there.
    this.errorTarget = errorTarget;

    tiles.setCamera(this.camera);
    tiles.setResolutionFromRenderer(this.camera, this.renderer);
    this.scene.add(tiles.group);

    /*
      Full daylight, and the lights are here only because the loader expects
      them to be. The tiles come back as MeshBasicMaterial, which is unlit by
      definition: it shows the texture and ignores every light in the scene.
      That is correct for photogrammetry — the photograph already contains its
      own lighting — and it is why an earlier attempt to make this scene look
      like evening by adding lights changed nothing at all.

      The time of day is decided in the grade instead. See buildGrade below.
    */
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.6));

    this.scene.add(this.buildSky());

    // The deck the camera falls through. Positioned and faded from altitude in
    // render(), because where the ground is is not known yet.
    this.clouds = this.buildClouds();
    this.scene.add(this.clouds);

    /*
      Bring Manhattan to the origin.

      getObjectFrame builds the matrix that places something at a point on the
      ellipsoid, facing along the local horizon. Inverting it and applying that
      to the tileset moves the world instead of the object, so the chosen
      coordinate ends up at (0, 0, 0) with up along Y.

      Radians, not degrees: everything in this library's geodesy is radians and
      passing degrees puts you several planets away without an error.
    */
    const frame = new THREE.Matrix4();
    WGS84_ELLIPSOID.getObjectFrame(
      MANHATTAN.lat * THREE.MathUtils.DEG2RAD,
      MANHATTAN.lon * THREE.MathUtils.DEG2RAD,
      0, 0, 0, 0, frame,
    );
    tiles.group.matrix.copy(frame).invert();
    tiles.group.matrix.decompose(
      tiles.group.position, tiles.group.quaternion, tiles.group.scale);
    tiles.group.updateMatrixWorld(true);

    /*
      Blue Marble, on the same ellipsoid, in front of the tiles.

      This is the last of the seam and the only part that could not be corrected
      by grading, because it is not a difference in tone, it is a difference in
      what the two datasets contain. On the globe the Great Lakes are almost
      black; on Google's coarse plate they are the same pale lavender as the
      continental shelf, because that plate paints every body of water alike.
      Across the join they went from black to white, in the middle of frame,
      and no curve fixes that: a tone curve maps levels, and these are two
      different pictures of the same lakes. Fitting one only moves the problem,
      since the tiles' lakes sit at the same brightness as their shelf and any
      curve that darkens one darkens the other.

      So the tiles do not have to be the picture at the top of the descent. The
      camera is three thousand kilometres up, where what Google serves is not
      photography either — it is a painted plate with bathymetry on it. Putting
      NASA's imagery on the ellipsoid, in the same frame, and fading it out as
      the camera falls means the handover frame is the *same image* on both
      sides of it, and the difference the eye was catching has nowhere left to
      be. What was a hard swap over three frames becomes lakes and shelf slowly
      resolving into photographs over the two seconds after, which is what
      arriving somewhere looks like.

      Built as a lat-lon grid in earth-centred coordinates rather than as a
      SphereGeometry that then gets rotated into place. A sphere in Three has
      its pole on Y and this frame has it on Z, the texture winds one way and
      the maths the other, and every one of those is a chance to end up with a
      mirrored planet. Written out, each vertex is a latitude and a longitude
      put through the standard ellipsoid formula and given the equirectangular
      texture coordinate that belongs to it, and there is nothing left to get
      backwards.
    */
    this.plate = await this.buildPlate(frame);
    this.scene.add(this.plate);

    /*
      Which way is north, measured rather than assumed.

      The camera at the top of the descent looks straight down, and a camera
      looking straight down has no opinion about which way up the picture is.
      Three resolves that roll from `camera.up`, and the default (0, 1, 0) is
      parallel to the view direction, so the answer came from the thousandth-of-
      an-altitude nudge that exists only to stop the gimbal. It came out as
      south.

      That is the whole seam. The globe hands over with north at the top of the
      frame and the tiles picked it up with north at the bottom, so the dissolve
      was rotating the Earth 180 degrees over half a second between two
      otherwise identical pictures. Rotate the descent's first frame by a half
      turn and it is the globe's last frame: same lakes, same coastline, same
      scale. Nothing was wrong with the position, the altitude or the field of
      view, all of which had been measured. The roll had not been.

      So take a point a little way north on the ellipsoid, bring it through the
      same inverse frame the tileset went through, and keep the horizontal part.
      Measured from the geodesy rather than written down, because the sign
      conventions in a local frame are exactly the kind of thing that is
      remembered wrong.
    */
    const northOf = new THREE.Vector3();
    WGS84_ELLIPSOID.getCartographicToPosition(
      (MANHATTAN.lat + 0.05) * THREE.MathUtils.DEG2RAD,
      MANHATTAN.lon * THREE.MathUtils.DEG2RAD,
      0, northOf,
    );
    northOf.applyMatrix4(tiles.group.matrix);
    this.north = new THREE.Vector3(northOf.x, 0, northOf.z).normalize();

    this.tiles = tiles;
    this.ready = true;
    // Not known until geometry has arrived, and not trusted until it has all
    // arrived. See groundLevel().
    this.ground = null;
    this.groundSettled = false;
    return this;
  }

  /*
    How far below the origin the street is, measured.

    getObjectFrame puts the *ellipsoid* surface at the origin, and the ellipsoid
    is a smooth mathematical figure that the actual ground is nowhere exactly
    on. In Manhattan the geoid sits about 33 m below the ellipsoid and the
    street about 10 m above sea level, so y = 0 is roughly 16 m up in the air.

    That is a small number and it invalidated everything. A camera placed at
    y = 11 believing it was at a third-floor window was at 27 m, which is above
    the roofline of the tenements it was supposed to be looking at, and the
    whole first sweep of candidate endings came back as bird's-eye views over
    rooftops. Nothing was wrong with the framing code; the floor was in the
    wrong place.

    Measured rather than written down, because it is different everywhere and a
    constant here would be a trap for the next location.

    Returns null until enough geometry has loaded to hit. Callers should fall
    back to 0 and re-ask, rather than treating the first answer as final.
  */
  groundLevel() {
    if (!this.tiles) return null;
    /*
      Do not keep an answer measured against half a tileset.

      The renderer serves coarse tiles first and refines them, and the coarse
      terrain for Manhattan sits well below the street. Caching the first
      non-null reading therefore locked in a ground level from geometry that was
      about to be replaced, and every frame after it put the camera under the
      road — the same black frames as before, from a different cause.

      So the reading is only kept once nothing is in flight. Until then it is
      re-measured on each call, which costs one raycast and is what the caller
      is asking for anyway.
    */
    const stats = this.tiles.stats ?? {};
    /*
      Settled is not enough. It has to be settled *and* close.

      The tileset settles at every altitude — it finishes fetching whatever the
      current error target asks for and then reports nothing in flight, three
      thousand kilometres up as much as thirty metres up. Caching on that alone
      locks in a ground level measured against whatever coarse geometry happened
      to be loaded at the top of the descent, and a coarse tile is a flat
      triangle across a curved surface, so it sits below the real ground by an
      amount that depends only on how big it is.

      Rejecting the wild readings was not the fix, only half of it. A chord sag
      of seventeen kilometres is obvious and now gets thrown out; a sag of three
      hundred metres passes every plausibility test there is and is just as
      wrong. It put the whole ending three hundred metres in the air, which is
      why a shot that was supposed to stop level with a fifth-floor window
      finished on the Manhattan skyline instead — and why the previous ending,
      nominally eighty metres up, was reading as a few hundred.

      So the answer is only kept once the camera is inside five kilometres,
      where the tiles under it are fine enough for the measurement to mean
      something. Above that it is re-measured each call and used as an estimate,
      which is all it is needed for: at three thousand kilometres, being a few
      hundred metres out about where the ground is changes nothing in frame.
    */
    /*
      Five hundred metres, not five thousand.

      At five kilometres the tiles under the camera are still coarse enough that
      the answer moved between runs: four separate probes of the same block
      reported the street at -18.1, -23.6, -25.8 and -29.5 metres, and the whole
      ending is written relative to it. Eleven metres of disagreement is half a
      window. At five hundred the fine levels are loaded and the reading repeats.
    */
    const settled = !stats.downloading && !stats.parsing
      && this.camera.position.y < 500;
    if (this.ground !== null && this.groundSettled) return this.ground;
    /*
      From well above anything in the tileset, straight down through the origin,
      and the topmost hit is the one that counts.

      The first attempt took the *last* hit, on the theory that a building at
      the chosen point would put a roof in front of the ground. It does not
      work: the tileset keeps several levels of detail loaded at once and their
      geometry overlaps, so a cast through Manhattan returns the street at
      -16.5 and a coarser copy of the same terrain at -27.2. Taking the deepest
      put the camera ten metres under the road and every frame came back black
      with a strip of streetlights along the top edge.

      The chosen points sit in the middle of streets, so the topmost surface is
      the road.
    */
    /*
      And the topmost hit still has to be plausible ground.

      The coarsest levels approximate the planet with very large flat triangles,
      and a flat triangle across a curved surface sags. The sag is the sphere's
      own geometry — a chord nine hundred kilometres long sits about seventeen
      kilometres below the arc it replaces — so before the fine levels arrive,
      a cast straight down through Manhattan reports the ground at -16,843 m and
      means it.

      Taken at face value that puts the camera seventeen kilometres underground,
      which loads tiles for a camera underground, which never resolves into the
      fine levels that would have given the right answer. The measurement and
      the thing it depends on are in a loop.

      So a reading is only ground if it is within nine kilometres of the
      ellipsoid, which no street on Earth is not — the highest inhabited places
      are under five and the lowest dry land is under half of one — and a coarse
      chord sag is far outside. Anything else is treated as "not yet", the same
      as no hit at all, and re-measured next call.
    */
    const PLAUSIBLE = 9000;
    const ray = new THREE.Raycaster(
      new THREE.Vector3(0, 6000, 0), new THREE.Vector3(0, -1, 0), 0, 30000);
    const hits = ray.intersectObject(this.tiles.group, true);
    const ground = hits.find((h) => Math.abs(h.point.y) < PLAUSIBLE);
    if (!ground) return null;

    /*
      And it has to say the same thing twice before it is believed.

      Plausible is a weak test. A reading of 241 m passes it and is still
      nonsense over Manhattan — it is a roof, or a coarse tile that happened to
      be the topmost thing along the ray at that moment. What separates a real
      measurement from a passing one is that the real one does not move: the
      street is where it is, and once the fine tiles are under the camera two
      consecutive readings agree to the centimetre.

      Half a metre of tolerance, which is far tighter than the eleven metres of
      disagreement this was producing and far looser than the noise between two
      settled frames.
    */
    const y = ground.point.y;
    const agrees = this.lastGround !== undefined && Math.abs(y - this.lastGround) < 0.5;
    this.lastGround = y;
    this.ground = y;
    this.groundSettled = settled && agrees;
    return this.ground;
  }

  /*
    Where the camera is during the descent, as a fraction of the beat.

    Metres above the chosen point, easing in so it arrives among the buildings
    rather than at them. It ends low and close, looking slightly up, which is
    the framing the next clip has to pick up from: a window, seen from the
    street.
  */
  /*
    One move, from orbit to a window, with nothing joined to anything.

    This used to be the bottom half of a two-shot intro: a rendered globe, a
    cross-dissolve, then a descent that began at 3,400 m. The dissolve was the
    problem. Two shots of the same city from different distances and different
    angles do not become one shot by fading between them; they read as two
    shots with a fade, which is what a cut is.

    The fix is that there was never any need for two. Google's Photorealistic 3D
    Tiles are a global dataset: the same tileset that has the fire escapes has
    the eastern seaboard from six hundred kilometres up, and it refines
    continuously between them. Measured, not assumed —
    scripts/probe-altitude.mjs renders one frame per altitude from 600 km to
    2 km and they all come back.

    So the whole descent is one camera falling through one dataset. There is no
    seam because there is nothing to seam.

    ## Two moves, and only two

    **The fall**, which is exponential.

    This is the part that has to be right or nothing else matters. A camera
    descending linearly from 600 km spends the first half of the shot appearing
    not to move — dropping 300 km when you are 600 km up changes the picture
    barely at all — and then covers the last kilometre in three frames. What
    reads as a steady zoom is a constant *ratio* per second, so the altitude is
    interpolated in log space. Every second of the shot roughly halves the
    height, all the way down, which is why a Google Earth zoom feels even.

    **The tilt**, which happens once, at the end, and only then.

    Straight down for the whole descent, then a single pan up onto a building
    front. The version before this had three eases with different start and end
    points, and the camera went up, then down, then up again: three overlapping
    moves read as a wobble, not as choreography. One move that starts at 0.80
    and finishes at 1.0 cannot do that.
  */
  place(t, endHeight = END.height) {
    /*
      Heights are metres above the street, not above the origin. See
      groundLevel: over Manhattan the ellipsoid surface is about twenty-four
      metres above the road, and taking the origin for the ground put every
      framing eight floors too high.
    */
    const floor = this.groundLevel() ?? 0;
    const clamp01 = (x) => Math.max(0, Math.min(1, x));
    const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };

    /*
      The shot is a fall and then a push, and they do not overlap.

      The fall keeps its own twelve seconds, ending level with a fifth-floor
      window; the two seconds after it are a horizontal flight at that window.
      Splitting them is what lets the camera turn only once it is *there*, which
      is the thing a descent onto a place has to do and which the old ending —
      turning at two hundred metres and arriving at a panorama — did not.

      Keeping the fall's length fixed while the shot grew also means the rate it
      hands over to at the top is unchanged, so the globe's dive did not have to
      be retuned again.
    */
    const HOLD = HANDOVER.fallSeconds / HANDOVER.seconds;
    const fallT = clamp01(t / HOLD);
    const height = fallHeight(fallT, endHeight);

    const normal = new THREE.Vector3(...END.normal).normalize();
    // The window's plane is the front face of the patch, which stands proud of
    // the scanned wall. Everything below is measured from that plane.
    const plane = new THREE.Vector3(END.x, floor + END.height, END.z)
      .addScaledVector(normal, PROUD);

    /*
      The facade goes in as soon as the ground is known, and not before.

      It is placed relative to the street rather than at an absolute height, so
      the patch and the camera derive from the same measurement and cannot drift
      apart if the ground reads differently. Until the tiles under the camera
      are fine enough for that reading to be trusted there is nothing to place
      it against, and there is also nothing close enough to see it.
    */
    if (!this.facade && this.groundSettled) {
      this.facade = buildFacade({
        centre: new THREE.Vector3(END.x, floor + END.height, END.z),
        normal, colour: END.brick,
        // Set by the render script from media/ui.png. See capture-ui.mjs.
        screenImage: this.screenImage ?? null,
      });
      /*
        Its own scene, drawn after the city with the depth buffer cleared
        between them.

        The patch stands 1.3 m proud of the wall it is on, which is enough to
        clear that wall's own bumps and nothing like enough to clear the
        building on the other side of the gap: measured on the approach, at ten
        metres out the frame was entirely somebody else's brick and the patch
        was not in it at all. Standing it further out is not an answer — the
        obstruction is eleven metres away, and a patch eleven metres off a wall
        is a slab hanging in the air.

        Depth is the wrong tool here. What this wants is a second pass: the city
        first, then the depth cleared, then the patch, which puts it in front of
        everything while keeping its own internal depth so the reveal still sits
        behind the frame and the recess behind that. The fade then works as a
        plain cross-dissolve over whatever the scan happens to show.
      */
      this.facadeScene = new THREE.Scene();
      this.facadeScene.add(this.facade);
    }

    /*
      Through the window and on to the desk, decelerating into it.

      Not log-spaced, which is right for a fall and impossible here: the fall
      never reaches the ground, and this ends on the far side of the thing it is
      approaching, so the distance passes through zero and a logarithm has
      nothing to say about it.

      Eased out instead. Physical speed falls away towards the end, which is
      what keeps *apparent* speed roughly even — the closer the camera is to
      something, the faster the same metre per second looks. It should arrive
      rather than stop, and the frame before the interface takes over should
      already be still.
    */
    const push = clamp01((t - HOLD) / (1 - HOLD));
    const glide = 1 - Math.pow(1 - push, 2.1);
    const distance = END.standoff + (END.arrive - END.standoff) * glide;

    // Straight down onto the standoff for the whole fall, then in along the
    // wall's normal. The height is the fall's until the fall is over, and the
    // window's after, and at the moment they change hands they are the same.
    /*
      And it drops half a metre on the way in, because the sash is up.

      The way through a sash window is the lower half of it: the upper sash is
      still glazed and the rail between them sits across the middle. Flying at
      the window's centre flies at the rail, which is painted trim and the
      brightest thing on the whole facade — measured, the last frame came back
      at 62 when the two before it were at 28.

      So the camera settles into the middle of the open gap as it arrives, which
      is also what going in through a window looks like.
    */
    /*
      And it drops as it goes in, because the sash is up and the desk is below.

      The way through a sash window is its lower half: the upper sash is still
      glazed and the rail sits across the middle. Flying at the window's centre
      flies at the rail, which is painted trim and the brightest thing on the
      facade — measured, the last frame came back at 62 when the two before it
      were at 28.

      One curve does both jobs. On the same easing as the push, the drop reaches
      0.49 m at the moment the camera crosses the window plane, which is the
      middle of the open gap, and 0.55 m by the desk, which is where somebody
      sitting at it would have their eyes.
    */
    const above = push > 0
      ? floor + END.height - 0.55 * glide
      : floor + height;
    this.camera.position.copy(plane)
      .addScaledVector(normal, push > 0 ? distance : END.standoff)
      .setY(above);

    /*
      Two rotations, and they have to happen in this order.

      The first is roll, while the camera is still pointing straight down. It
      starts with north at the top of frame, because that is what the globe
      hands over, and ends with the wall's own direction there. That is the only
      orientation a pitch is roll-free from: a camera whose target is already on
      the frame's axis merely raises it to the middle, and one whose target is
      not has to twist as well.
    */
    const turn = smooth((t - 0.26) / 0.34);
    const heading = this.north
      ? this.north.clone().lerp(normal.clone().negate(), turn).normalize()
      : normal.clone().negate();

    /*
      The second is pitch, and it finishes exactly when the fall does — so the
      camera comes level with the window at the moment it stops descending, and
      the push begins from a level shot. Not before: at fifty-five per cent of a
      logarithmic fall the camera is still two hundred metres up, which is what
      made the old ending read as a fly-over.
    */
    const tilt = smooth((t - HOLD * 0.78) / (HOLD * 0.22));
    const pitch = -Math.PI / 2 * (1 - tilt);

    /*
      Up, derived from the pitch rather than interpolated towards it.

      This was a straight lerp from the horizontal heading to world up, and half
      way through the turn that put the up vector exactly antiparallel to the
      view direction. lookAt takes the cross product of those two, and the cross
      product of opposite vectors is zero, so at that one frame the orientation
      came from whatever the library does when its arithmetic collapses: every
      frame through the swing pitched 1.87 degrees and that one pitched 2.09,
      with the next making up the difference. Perpendicular by construction here
      — the same two vectors, ninety degrees apart in the same plane.
    */
    this.camera.up.copy(heading).multiplyScalar(-Math.sin(pitch))
      .addScaledVector(new THREE.Vector3(0, 1, 0), Math.cos(pitch))
      .normalize();

    const dir = heading.clone().multiplyScalar(Math.cos(pitch))
      .addScaledVector(new THREE.Vector3(0, 1, 0), Math.sin(pitch));
    /*
      Aim straight in until the room, then settle onto the screen.

      Held level for the first half of the push so the window stays square in
      frame while the camera flies at it — a shot that starts tilting towards
      its subject before it is through the opening looks like it is avoiding the
      frame. The last half brings the screen to the middle.
    */
    /*
      Settled over the last two fifths of the push in *time*, not in distance.

      Keyed to distance it happened almost at once: the push eases out, so
      three quarters of the metres are behind it by the half way mark and a
      settle keyed to that was complete before the camera reached the window.
      Time is what the eye is watching.
    */
    const settle = smooth(clamp01((push - 0.6) / 0.4));
    if (this.facade && settle > 0) {
      /*
        Square on to the screen by the end, not just pointed at it.

        The lid leans back about ten degrees, so a camera that arrives along the
        wall's normal sees the screen as a trapezium — and the handoff scales
        that rectangle up to fill the frame, which only works if it is a
        rectangle. Easing the position onto the screen's own axis over the last
        half of the push costs nothing in the move and leaves the last frame
        square.
      */
      const screen = this.facade.userData.screenWorld();
      const facing = this.facade.userData.screenNormal();
      const squareOn = screen.clone().addScaledVector(facing, 0.38);
      this.camera.position.lerp(squareOn, settle);
      const ahead = this.camera.position.clone().addScaledVector(dir, 4);
      this.camera.lookAt(ahead.lerp(screen, settle));
    } else {
      this.camera.lookAt(this.camera.position.clone().addScaledVector(dir, 4));
    }

    /*
      What the camera is flying at, so render() can put the near plane in front
      of it. A fiftieth of the altitude is right all the way down a descent and
      catastrophic in the last half second of this one, where the window is a
      quarter of a metre away and the altitude is sixteen metres.
    */
    /*
      The city stops being drawn once the patch covers the frame.

      The patch stands 1.3 m proud of the scanned wall, and the scan is bumpy by
      two or three metres over this facade — so scanned geometry pokes through
      it, and the approach came back as a screen full of melted brick with the
      patch nowhere in it. Standing the patch further out only trades that for a
      slab floating in front of a building.

      There is nothing to reconcile, because there is nothing to see. At
      fourteen metres the frame is 19 m wide and 11 m tall and the patch is 30
      by 22: it already covers everything, and every metre closer it covers more.
      Hiding the tiles under it changes no pixel and removes the whole class of
      problem.
    */
    /*
      The patch dissolves in over the photographed brick, and the city stops
      being drawn once it is opaque.

      Swapping outright at the moment the patch covers the frame was the first
      version, and it changes the character of the picture in one frame: melted
      photographic brick becomes clean even brick, which reads as a cut even
      though nothing moved. Faded in, the two are the same wall in the same
      colour — the sampled one — and what the eye sees is detail arriving, which
      is what has been happening for the whole descent anyway.

      Opaque by six metres. The margin matters: at fourteen metres the frame is
      nineteen across and the patch is thirty, so there is nothing behind it to
      lose once it is opaque.
    */
    /*
      From eighteen metres to ten.

      Two constraints pulling opposite ways. Starting too early shows eight
      translucent windows hanging in front of a building, because the patch is
      part-opaque over brick that does not line up with it — the first version
      began at fourteen metres and was already fourteen per cent on. Starting
      too late leaves the shot on melted scan for a second longer than it needs
      to be, and that is now the worst-looking moment in the whole intro: the
      contact sheet has one frame of dripping brick in it and it is the frame
      before this takes over.

      Eighteen is as early as the patch can cover the frame, so the fade can
      start there and be done at ten, and there is nothing part-opaque over
      anything that is still in shot.
    */
    const cover = clamp01((18 - distance) / 8);
    if (this.facade) {
      const shown = push > 0 ? smooth(cover) : 0;
      for (const m of this.facade.userData.fading) m.opacity = shown;
      this.facade.visible = shown > 0.002;
    }


    // Near from what the camera is about to be close to — the window on the way
    // in, then the screen, which it finishes 0.6 m from. The altitude-based
    // floor of five metres would clip both out of existence.
    this.nearHint = push > 0 ? Math.max(0.015, Math.abs(distance) * 0.05) : null;
    this.camera.updateMatrixWorld();
  }

  /*
    The Blue Marble plate. See where it is added, in load().

    Async because the texture has to be on the GPU before the first frame is
    photographed. Offscreen there is no second chance: the render loop waits for
    tiles, not for images, so a texture still in flight is a black sphere over
    the whole frame and the first frames go out that way.
  */
  async buildPlate(frame) {
    const A = 6378137;                 // WGS84 semi-major axis, metres
    const B = 6356752.314245;          // semi-minor
    const E2 = 1 - (B * B) / (A * A);  // first eccentricity squared
    const LON = 256;
    const LAT = 128;

    const position = [];
    const uv = [];
    for (let j = 0; j <= LAT; j++) {
      const lat = (-90 + (180 * j) / LAT) * THREE.MathUtils.DEG2RAD;
      const sin = Math.sin(lat);
      const cos = Math.cos(lat);
      // Radius of curvature in the prime vertical: the ellipsoid's answer to
      // "how far out is the surface at this latitude".
      const n = A / Math.sqrt(1 - E2 * sin * sin);
      for (let i = 0; i <= LON; i++) {
        const lon = (-180 + (360 * i) / LON) * THREE.MathUtils.DEG2RAD;
        position.push(n * cos * Math.cos(lon), n * cos * Math.sin(lon),
                      n * (1 - E2) * sin);
        // Equirectangular: u eastward from the antimeridian, v northward from
        // the south pole, which is what flipY on a loaded image already gives.
        uv.push(i / LON, j / LAT);
      }
    }
    const index = [];
    for (let j = 0; j < LAT; j++) {
      for (let i = 0; i < LON; i++) {
        const a = j * (LON + 1) + i;
        const b = a + 1;
        const c = a + LON + 1;
        const d = c + 1;
        index.push(a, b, c, b, d, c);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geometry.setIndex(index);

    const map = await new Promise((res, rej) => {
      new THREE.TextureLoader().load("/textures/earth-day.jpg", res, undefined, rej);
    });
    map.colorSpace = THREE.SRGBColorSpace;
    map.anisotropy = this.renderer.capabilities.getMaxAnisotropy();

    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      map,
      transparent: true,
      opacity: 0,
      // Over the tiles rather than fighting them for depth. The two surfaces
      // are the same surface, to within the difference between an ellipsoid and
      // the ground, so any depth test between them is a coin toss per pixel and
      // shows as speckle.
      depthTest: false,
      depthWrite: false,
    }));
    mesh.renderOrder = 10;
    mesh.frustumCulled = false;
    // Into the same frame the tileset was moved into, so the two coincide.
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(frame).invert();
    return mesh;
  }

  /*
    A deck of cloud to fall through, at two kilometres.

    The oldest fix in the trade for this shot, and the one thing that was
    missing. A descent from orbit to a street crosses an enormous range of
    imagery quality — sharp from space, mush by the time the camera is among
    buildings — and no amount of matching hides where that turns over, because
    it is not a seam, it is a gradient the eye follows all the way down. What
    hides it is going through weather: cloud takes the frame for half a second,
    and what comes out the other side is simply what is there.

    It is also the single largest thing this shot was missing on its own terms.
    Every real descent has weather in it and this one fell through nothing.

    Built as a stack of planes rather than as volume. Volumetric cloud is a
    ray-march that would dominate the frame budget of a render already limited
    by tile streaming, and it is not needed: several layers of soft noise at
    slightly different heights and drifts, passed through rather than looked
    at, read as cloud because the camera is inside them for a moment and the
    parallax between layers is real.
  */
  buildClouds() {
    const group = new THREE.Group();
    const LAYERS = 5;
    // Wide enough that the edge is never in frame at the altitude it is met.
    const SIZE = 26000;

    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1024;
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, 1024, 1024);
    let seed = 11;
    const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    /*
      Blobs at several scales, which is the cheapest thing that reads as cloud.

      A single scale of noise reads as fog or as static. Cloud has structure at
      every size at once — a few large masses, more medium ones, a scatter of
      small — so the same drawing is done three times at three sizes and three
      densities.
    */
    for (const [count, size, alpha] of [[13, 300, 0.52], [38, 128, 0.34], [95, 50, 0.2]]) {
      for (let i = 0; i < count; i++) {
        const x = rand() * 1024;
        const y = rand() * 1024;
        const r = size * (0.5 + rand());
        const blob = g.createRadialGradient(x, y, 0, x, y, r);
        blob.addColorStop(0, `rgba(255,255,255,${alpha})`);
        blob.addColorStop(0.55, `rgba(255,255,255,${alpha * 0.45})`);
        blob.addColorStop(1, "rgba(255,255,255,0)");
        g.fillStyle = blob;
        g.fillRect(x - r, y - r, r * 2, r * 2);
      }
    }
    /*
      Cut the veil out, and keep the masses.

      Soft blobs drawn over each other never reach zero: whatever the alpha of
      each, the gaps between them fill in, and seven layers of that sum to an
      even wash over the whole frame — which is fog. Cloud is the opposite. It
      is lumps with clear air between them, and the clear air is what makes the
      lumps read as objects with a shape rather than as dirt on the lens.

      So the alpha is thresholded after drawing: anything under a third goes to
      nothing at all, and what is left is stretched back out to full. It costs
      one pass over a megapixel at load and it is the difference between weather
      and haze.
    */
    const px = g.getImageData(0, 0, 1024, 1024);
    const a = px.data;
    for (let i = 3; i < a.length; i += 4) {
      const v = a[i] / 255;
      a[i] = Math.max(0, Math.min(1, (v - 0.32) / 0.5)) ** 1.15 * 255;
    }
    g.putImageData(px, 0, 0);

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.colorSpace = THREE.SRGBColorSpace;

    for (let i = 0; i < LAYERS; i++) {
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(SIZE, SIZE),
        new THREE.MeshBasicMaterial({
          map: tex, transparent: true, opacity: 0,
          depthWrite: false,
          // Seen from below as much as from above, because the camera goes
          // through them.
          side: THREE.DoubleSide,
        }));
      plane.material.map = tex.clone();
      plane.material.map.needsUpdate = true;
      // Each layer sees the texture at its own scale and offset, so the stack
      // does not read as one picture repeated seven times.
      /*
        The repeat is what sets how big a cloud is, and it was three times too
        low.

        The plane is twenty-six kilometres across. At a repeat of 2.2 one tile
        covers twelve kilometres, so the largest blobs in it came out three and
        a half kilometres wide and the camera met one of them as a flat wash
        over the whole frame — fog, not weather. At 6.5 a tile is four
        kilometres and the same blob is about a kilometre, which is the size a
        cumulus actually is.
      */
      const repeat = 6.5 + i * 0.6;
      plane.material.map.repeat.set(repeat, repeat);
      plane.material.map.offset.set(i * 0.37, i * 0.61);
      plane.rotation.x = -Math.PI / 2;
      plane.renderOrder = 5;
      plane.frustumCulled = false;
      group.add(plane);
    }
    group.userData.layers = LAYERS;
    return group;
  }

  /*
    The sky, which the tileset does not come with.

    Photogrammetry is ground and buildings. Above the horizon there is nothing,
    so the frame is pure black up there and the city sits on the edge of a
    hole. A dome large enough to be outside anything the camera will visit,
    drawn from the inside, with the gradient of the twenty minutes after sunset:
    deep blue overhead falling through slate to a narrow warm band where the sun
    has just gone.

    Basic material and no depth write, so it never occludes a building and
    never has to be lit.
  */
  buildSky() {
    const sky = new THREE.Mesh(
      new THREE.SphereGeometry(60000, 32, 24),
      new THREE.ShaderMaterial({
        uniforms: {
          // Late afternoon rather than twenty minutes after sunset. The sky
          // has to belong to the same hour as the ground, and the ground is
          // Google's, which is always the middle of a clear day.
          uHigh:   { value: new THREE.Color(0x2c5f95) },   // overhead
          uMid:    { value: new THREE.Color(0x76a6cf) },
          uLow:    { value: new THREE.Color(0xc3d2e0) },   // haze at the horizon
          uGlow:   { value: new THREE.Color(0xe8c9a4) },   // low sun, not sunset
          uSunDir: { value: new THREE.Vector3(-0.72, 0.05, -0.69).normalize() },
        },
        vertexShader: `
          varying vec3 vDir;
          void main() {
            vDir = normalize(position);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: `
          uniform vec3 uHigh, uMid, uLow, uGlow, uSunDir;
          varying vec3 vDir;
          void main() {
            vec3 d = normalize(vDir);
            // Height above the horizon, 0 at it and 1 straight up.
            float up = clamp(d.y, 0.0, 1.0);
            vec3 col = mix(uLow, uMid, smoothstep(0.0, 0.22, up));
            col = mix(col, uHigh, smoothstep(0.18, 0.75, up));
            /*
              The afterglow, and it belongs in one place rather than all round.
              Twenty minutes after sunset the western horizon is orange over
              maybe sixty degrees and the eastern one is already blue. A band
              round the whole sky is the tell of a gradient rather than a sky.
            */
            float toward = max(0.0, dot(d, normalize(uSunDir)));
            // Wider across the horizon and much shallower above it. The first
            // version used a third power against a 30-degree falloff, which
            // put a saturated red block in one corner of the frame rather than
            // a band along the skyline.
            float band = pow(toward, 1.8) * (1.0 - smoothstep(0.0, 0.13, up));
            col = mix(col, uGlow, band * 0.55);
            // Below the horizon it goes to ground haze rather than to nothing,
            // so the seam where the tiles end is a fog bank and not an edge.
            col = mix(col, uLow * 0.45, smoothstep(0.0, -0.10, d.y));
            gl_FragColor = vec4(col, 1.0);
          }`,
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
      }),
    );
    sky.renderOrder = -1;
    // Kept, because render() has to switch it off once the camera climbs above
    // it. See the note there.
    this.sky = sky;
    return sky;
  }

  update() {
    if (!this.ready) return;
    this.tiles.setResolutionFromRenderer(this.camera, this.renderer);
    this.tiles.update();
  }

  /* How much of what the camera can see has actually arrived. The descent
     should not start until most of it has, or the opening is a flight through
     a half-built city. */
  loaded() {
    if (!this.ready) return 0;
    const { downloading, parsing } = this.tiles.stats ?? {};
    return downloading === 0 && parsing === 0 ? 1 : 0;
  }

  /*
    Turning midday into the twenty minutes after sunset.

    Google captures its photorealistic tiles in bright daylight and publishes
    no other version, so the time of day has to be a grade rather than a light.
    Every attempt to do it with lights failed for a reason worth writing down:
    the tiles arrive as MeshBasicMaterial, which ignores lighting entirely, so
    a scene full of carefully placed evening lights renders exactly the same as
    an empty one.

    A grade is honest about what it is. Four things, and each one is a specific
    observation about what the eye uses to date a photograph:

    1. **Exposure**, obviously, but not evenly. Highlights fall further than
       shadows at dusk, because the sun has gone and what is left is a broad
       dim sky: the contrast between a lit face and a shaded one collapses.
    2. **Colour separation.** Shadows go blue and what light remains goes warm.
       A flat overall blue tint reads as a filter; the split reads as evening.
    3. **Aerial perspective.** Distance haze is what makes a city look like a
       city rather than a model, and it is stronger at dusk than at noon. Done
       from depth, so it thickens with real distance rather than with height in
       frame — a vertical gradient gets it wrong the moment the camera tilts.
    4. **Vignette**, gently, because a lens does that and the absence of it is
       one of the things that makes rendered footage look rendered.
  */
  buildGrade() {
    this.target = new THREE.WebGLRenderTarget(1, 1, {
      // Depth read back as a texture, for the haze. Without it the fog has to
      // be faked off screen position and tilts with the camera.
      depthTexture: new THREE.DepthTexture(1, 1),
      type: THREE.HalfFloatType,
    });

    this.grade = new THREE.ShaderMaterial({
      uniforms: {
        uScene: { value: this.target.texture },
        uDepth: { value: this.target.depthTexture },
        uNear:  { value: this.camera.near },
        uFar:   { value: this.camera.far },
        // How far the grade has come. 0 is the untouched daylight capture,
        // which is what the probe renders and what makes a comparison possible.
        uAmount: { value: 1 },
        // The colour distance dissolves into. It has to be what the sky is
        // doing near the horizon, or the skyline fades towards one colour in
        // front of a different one and the join shows as a line.
        uHaze:  { value: new THREE.Color(0x9fb4c9) },
        /*
          How far light travels before the air has swallowed it, in metres, and
          it cannot be a constant.

          900 was measured against a shot standing in a street, where the far
          end of Manhattan is a couple of kilometres off and should wash out.
          The same number over the top of the descent put the camera 3,400 m up
          looking at ground 4,300 m away: every pixel in frame was past the
          horizon of the haze, the whole city dissolved into one flat blue, and
          the first half of the render came back an empty rectangle. It looked
          exactly like the tiles had failed to load. They had not.

          Set from the camera's height in render(), because that is what decides
          it: the higher you are, the less air sits between you and what you are
          looking at per metre of distance.
        */
        uFog:   { value: 900 },
        /*
          An extra lift for the coarse levels of detail.

          Google's imagery gets darker the further out you go: the tiles served
          at three thousand kilometres are a different, older, dimmer source
          than the ones served over a street, and the same grade over both puts
          the top of the descent two thirds of a stop under the bottom.

          It matters because of what the top of the descent hands over from.
          Measured at the seam: the globe's last frame is 63 and the tiles' first
          was 40, and a join between two frames of the same place at the same
          altitude in different exposures is a cut however well they are framed.
        */
        uLift:  { value: 1 },
        /*
          How hard to bend the tiles towards the plate the globe hands over.

          One at the top of the descent, nothing by the time the camera is
          inside the atmosphere. What it corrects is not an error in Google's
          data, it is a difference in what the two sources *are*. The globe is
          NASA's Blue Marble on a sphere, where open ocean is a near-neutral
          navy: measured over the Atlantic at the seam, r 32 g 33 b 42, which is
          a saturation of ten. Google's coarse levels serve a flat bathymetry
          plate instead, and the same water there is 12, 24, 76 — a saturation
          of sixty-four, six times as much, and a blue channel nearly doubled.

          Two frames of the same coastline at the same altitude in the same
          light, one of them slate and the other cobalt. Once the roll was fixed
          and the geography lined up, that was the whole of what was left to see
          at the join, and no length of dissolve hides a hue step; it just gives
          the eye longer to watch it happen.

          It also happens that the flat blue is the less convincing of the two.
          Real orbital photography of open ocean is dark and almost colourless
          at this scale. So this is not damage done to Google's imagery for the
          sake of a match, it is a correction that the top of the descent wanted
          anyway, and it is gone by the time there is any real ground to look
          at.
        */
        /*
          Inside the cloud, as a screen-wide wash.

          The deck is built from planes and planes cannot be gone *through*. At
          two kilometres the camera is among them and looking straight down at a
          patch of texture a hundred metres across, which is almost always a gap
          — so the frame came out clear at exactly the moment it should have
          been white. A volume would fix it and would also dominate the frame
          budget of a render already limited by tile streaming.

          What passing through cloud looks like is a whiteout, and a whiteout is
          one number. The planes do the approach and the departure, where they
          are seen from outside and read as a deck; this does the half second
          inside, where nothing is visible at all.

          It is also the seam that this whole descent needed. Every crossing
          from good imagery to bad happens somewhere, and hiding it inside
          weather is the oldest fix there is for this shot.
        */
        uCloud: { value: 0 },
        uPlate: { value: 0 },
        /*
          How far out of focus the coarse tiles are, in pixels, and why a zoom
          that has already been matched four ways still reads as a cut.

          The two halves are not the same kind of picture. The globe is NASA's
          Blue Marble, 3,600 pixels wide for the whole planet, so at the
          handover the frame is showing about four hundred texture pixels
          stretched across 1,920 — soft, and nothing can make it otherwise.
          Google's tiles at the same altitude are photographs.

          Measured on the stitched file as mean absolute Laplacian, which is a
          plain way of asking how much fine detail a frame contains: the globe
          holds a steady 8, the dissolve drops it to 5 because averaging two
          not-quite-aligned images destroys local contrast, and the tiles come
          in at 10 and climb to 12. Mush, then a two-and-a-half-fold snap into
          sharpness, inside four tenths of a second. Position, colour and speed
          were all matched by then. Texture was not, and it is the loudest of
          the four.

          So the tiles arrive at the globe's resolution and sharpen as they
          fall. That is not a fudge to hide a join: it is what a descent through
          an atmosphere looks like, and it means detail *arrives* over the length
          of the zoom rather than all at once in one frame near the top.
        */
        uSoft:  { value: 0 },
        /*
          How hard to pull the tiles' tones onto the globe's, and why this is a
          curve and not a few multipliers.

          It was multipliers first: split water from land on whether blue is the
          dominant channel, then desaturate one and warm the other, to ratios
          measured off the globe's last frame. That matched the *averages* and
          the join still read as two shots, because the thing giving it away is
          not an average.

          Blue Marble and Google's coarse plate draw water in opposite
          directions. On the globe the Great Lakes are almost black and the
          continental shelf is a pale band. On the plate every body of water is
          the same light lavender, lakes included, so across the seam the Great
          Lakes go from black to white. They are large, they are in the middle
          of frame, and no pair of multipliers fixes that: it needs bright water
          pulled down while bright land is left alone, which is a different
          answer at different input levels. That is a tone curve.

          So the curve is fitted rather than written: match the cumulative
          histogram of the tiles' handover frame to the globe's, per channel,
          which lands every level where the globe puts it — lakes, shelf, deep
          ocean, forest and cloud all at once. Generated by
          scripts/match-plate.mjs into plate-lut.js, and regenerated whenever
          either half of the handover changes.
        */
        uMatch: { value: 0 },
        /*
          How much of what is on screen is Google's imagery, as against NASA's
          plate sitting over it.

          Everything in this grade that depends on how bright a pixel already is
          — the highlight roll-off, the shadow gamma, the lift for the dim
          coarse levels, the cool-to-warm split — exists to make photogrammetry
          read as a photograph at dusk. None of it is wanted over the plate,
          which is a finished picture already, and worse, all of it is
          *unfixable* over the plate: those terms key off luminance rather than
          off each channel separately, so they reorder colours in a way no
          per-channel curve can undo. That is why the tone match kept landing
          the frame's average exactly right and its bright shelf water forty
          levels out in red.

          So the grade fades in as the plate fades out, and the curve is left
          with a straightforward per-channel job it can actually do.
        */
        uShow:  { value: 1 },
        uLut:   { value: plateLut() },
        uTexel: { value: new THREE.Vector2(1 / 1920, 1 / 1080) },
        uShade: { value: new THREE.Color(0x2c3f63) },   // kept for reference
        uWarm:  { value: new THREE.Color(0xffc07a) },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
      fragmentShader: `
        uniform sampler2D uScene;
        uniform sampler2D uDepth;
        uniform float uNear, uFar, uAmount, uFog, uLift, uPlate, uSoft, uMatch, uShow, uCloud;
        uniform sampler2D uLut;
        uniform vec2 uTexel;
        uniform vec3 uHaze, uShade, uWarm;
        varying vec2 vUv;

        // Metres from the camera. The depth buffer stores a nonlinear value,
        // and reading it as if it were linear puts every building at the far
        // plane, which is the mistake that killed the first attempt at this.
        float distanceAt(float d) {
          float ndc = d * 2.0 - 1.0;
          return (2.0 * uNear * uFar) / (uFar + uNear - ndc * (uFar - uNear));
        }

        /*
          Defocus by explicit taps rather than by a mipmap bias.

          A bias is one fetch and would be prefiltered properly, but it depends
          on mipmaps actually being generated for a half-float render target,
          and if they quietly are not the blur silently does nothing. This
          project has had three separate bugs whose only symptom was a measured
          number failing to move, and a fourth is not wanted. Forty-nine taps
          cannot fail quietly, and this runs offline where the cost is nothing.
        */
        vec3 soft(vec2 uv) {
          if (uSoft < 0.01) return texture2D(uScene, uv).rgb;
          vec3 sum = vec3(0.0);
          float wsum = 0.0;
          for (int y = -3; y <= 3; y++) {
            for (int x = -3; x <= 3; x++) {
              vec2 d = vec2(float(x), float(y));
              float w = exp(-dot(d, d) * 0.22);
              sum += texture2D(uScene, uv + d * (uSoft / 3.0) * uTexel).rgb * w;
              wsum += w;
            }
          }
          return sum / wsum;
        }

        void main() {
          vec3 day = soft(vUv);
          vec3 c = day;
          float d = texture2D(uDepth, vUv).x;

          /*
            The sky is already the right time of day, so it is not graded.

            It comes from buildSky, which paints dusk directly. Running it
            through the same curve as the photography darkened it to almost
            black and then the haze term — which reads maximum at the far plane
            — flattened whatever survived into one grey. The first version of
            this looked like a city at the bottom of a well.
          */
          /*
            Sky by distance, not by a raw depth value.

            A raw depth of 0.9999 is only "the far plane" when near and far are
            the ones this was written against. Flying into a window needs a near
            plane of a few centimetres, and against a hundred-kilometre far plane
            that pushes ordinary geometry past it — every building in the middle
            distance would take the sky path and come out ungraded.

            Half the far plane is the sky dome and nothing else: the dome sits at
            sixty kilometres, the city ends a couple of kilometres out, and
            anything that rendered nothing at all comes back at exactly far.
          */
          if (distanceAt(d) > uFar * 0.5) { gl_FragColor = vec4(day, 1.0); return; }

          // Luminance, Rec. 709. Both the exposure roll-off and the colour
          // split are decided by how bright a pixel already is.
          float l = dot(c, vec3(0.2126, 0.7152, 0.0722));

          // Highlights fall further than shadows: the sun has gone and the sky
          // is doing all the work, so the difference between a lit face and a
          // shaded one collapses.
          /*
            Barely darkened at all now.

            The whole grade was built to turn midday into night, back when the
            intro had to match a night Earth. It does not any more: the planet
            on the site stays NASA's night imagery and the intro is daylight,
            which is the trade Google's data forces and the one Leo took.

            So this stops pretending. A touch off the highlights, nothing off
            the shadows, and what is left of the grade is the colour separation
            and the haze — the two parts that make a photograph read as a
            photograph rather than as a texture. At 0.86/0.46 the same footage
            came back looking like a night flight over an unlit city.
          */
          /*
            Every luminance-dependent part of this grade is gated on how much of
            Google's imagery is actually on screen. See uShow.
          */
          c *= mix(1.0, mix(1.02, 0.86, smoothstep(0.15, 0.85, l)), uShow);

          /*
            Lift the shadows, because the satellite imagery is very dark and
            the exposure curve above cannot help it.

            That curve takes light off the highlights, which is right for a
            frame with a sky in it and does nothing for one that has no
            highlights at all. From six hundred kilometres the land is dense
            forest and dark cities against a bright ocean, and it came back
            reading almost black beside water that was fine.

            A gamma on the dark end instead: pixels near zero move a long way,
            pixels near one barely move. That is what opens shadow detail
            without flattening anything that was already bright.
          */
          // Not gated: a gamma is per-channel and a lift is a multiply, and a
          // per-channel curve composes with both exactly. Gating them only made
          // the plate very dark and left the curve to undo it, which quantised
          // to sixty-four entries turned into a step: everything above level 65
          // crushed to one value.
          c = pow(clamp(c, 0.0, 1.0), vec3(0.78));
          c *= uLift;

          /*
            Shadows blue, highlights warm.

            As *tints* whose channels average one, not as multiplications by a
            dark colour. Multiplying by uShade darkened the shadows a second
            time on top of the exposure above, and the two compounded into
            almost nothing. A tint moves the hue and leaves the brightness where
            the exposure put it, which is what a grade is supposed to do.
          */
          // Halved towards neutral. At full strength this was doing the work of
          // a time-of-day change; over daylight imagery it only has to suggest
          // late afternoon, and a strong split over a bright frame reads as a
          // filter rather than as light.
          vec3 cool = vec3(0.88, 0.95, 1.12);
          vec3 warm = vec3(1.11, 1.01, 0.89);
          c *= mix(vec3(1.0), mix(cool, warm, smoothstep(0.10, 0.52, l)), uShow);

          /*
            Aerial perspective, from real distance.

            1200 m is about the depth of Manhattan seen from the East Village,
            so the far skyline washes into the sky and the block in front of the
            camera does not. Off screen position instead of depth this tilts
            with the camera and stops being distance at all.
          */
          /*
            900 m, and the mix goes to 0.97 rather than 0.78.

            At 1200 and 0.78 the tileset's own far edge stayed visible: the
            lowest level of detail is a flat strip and it sat along the horizon
            as a bright line, which is the join between having data and not
            having any. Thickening the haze until distance dissolves completely
            hides that seam and is what the air actually does at dusk anyway.
          */
          float fog = 1.0 - exp(-distanceAt(d) / uFog);
          c = mix(c, uHaze, clamp(fog, 0.0, 1.0) * 0.97);

          // A little lift, because air scatters and a true black at dusk is a
          // hole rather than a shadow.
          c += vec3(0.004, 0.006, 0.011);

          /*
            The vignette waits until there is a city to put it on.

            Measured across the join, corner brightness against centre: the
            globe hands over at 0.93 and the tiles took it at 0.79. A vignette
            appearing over a quarter of a second is a lens changing in the
            middle of a continuous shot. It belongs to the street-level end of
            the descent, where it is doing something, so it fades in with
            everything else.
          */
          // Inside the deck. See uCloud. Before the vignette, because a lens
          // still darkens its corners when the frame is full of cloud.
          if (uCloud > 0.0) {
            c = mix(c, vec3(0.86, 0.88, 0.92), uCloud);
          }

          float r = distance(vUv, vec2(0.5)) * 1.42;
          c *= 1.0 - 0.16 * (1.0 - uPlate) * pow(clamp(r, 0.0, 1.0), 2.4);

          /*
            Meet the globe, by tone curve rather than by multipliers. See uMatch.
          */
          if (uMatch > 0.0) {
            vec3 q = clamp(c, 0.0, 1.0);
            vec3 matched = vec3(
              texture2D(uLut, vec2(q.r, 0.5)).r,
              texture2D(uLut, vec2(q.g, 0.5)).g,
              texture2D(uLut, vec2(q.b, 0.5)).b);
            c = mix(c, matched, uMatch);
          }

          gl_FragColor = vec4(mix(day, c, uAmount), 1.0);
        }`,
      depthTest: false,
      depthWrite: false,
    });

    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.grade);
    this.quad.frustumCulled = false;
    this.gradeScene = new THREE.Scene();
    this.gradeScene.add(this.quad);
    this.gradeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  }

  render() {
    if (!this.grade) this.buildGrade();

    // The target has to match the canvas, and the canvas changes size. Asked
    // for every frame rather than on a resize event, because this also runs
    // offscreen where there is no window to fire one.
    const size = this.renderer.getSize(new THREE.Vector2());
    const dpr = this.renderer.getPixelRatio();
    const w = Math.max(1, Math.round(size.x * dpr));
    const h = Math.max(1, Math.round(size.y * dpr));
    if (this.target.width !== w || this.target.height !== h) {
      this.target.setSize(w, h);
    }
    const above = Math.max(0, this.camera.position.y - (this.groundLevel() ?? 0));

    /*
      Above sixty kilometres there is no sky, because there is no air.

      The dome has a radius of 60 km, which is generous for an atmosphere and
      nothing at all next to a descent that begins at six hundred. Climbing
      past it put the camera *outside* its own sky looking at the back of it,
      and the Earth — correctly — was on the far side. The opening frames came
      back as a small dark circle on black: not a planet, a sphere seen from
      outside with the planet hidden inside it.

      Which is also the physically right answer. At six hundred kilometres you
      are above the atmosphere and the background is space. So the dome is
      simply switched off once the camera is higher than it is, and switched
      back on during the descent, at which point it is the sky again.
    */
    /*
      Tighter still in the last hundred metres.

      A level of detail swapping three thousand kilometres up moves the picture
      by very little, because everything is far away. The same swap twenty
      metres from a tenement moves a wall. Measured on the finished descent, one
      frame near the end changed by sixty-five against a run of twenty either
      side, and re-shooting it produced the same sixty-five twice, so it is a
      real swap and not a frame caught mid-load.

      Four everywhere and two in close, which is roughly the last second and a
      half. Only for renders: the value is null for a visitor, where Google's
      own twenty is right and the bandwidth is somebody's phone.
    */
    if (this.errorTarget && this.tiles) {
      this.tiles.errorTarget = above < 500
        ? Math.min(2, this.errorTarget) : this.errorTarget;
    }

    /*
      The deck sits at two kilometres and is only there while the camera is near
      it.

      Two kilometres because that is where the imagery starts to give out — the
      cloud arrives exactly where the picture would otherwise be visibly getting
      worse, which is the whole point of it. The layers are spread over four
      hundred metres so passing through takes a moment rather than a frame.

      Faded in from above and out from below, over a band wide enough that it
      arrives as weather rather than as an object switching on. Below the deck
      it is behind the camera and off.
    */
    if (this.clouds) {
      const DECK = 2000;
      const SPREAD = 420;
      const layers = this.clouds.userData.layers;
      this.clouds.position.y = floorOf(this) + DECK;
      const band = Math.abs(above - DECK);
      const near = 1 - Math.min(1, band / 2100);
      const shown = near * near * (3 - 2 * near);
      this.clouds.visible = shown > 0.004;
      /*
        The whiteout, over four hundred metres either side of the deck.

        At this point in the fall the camera covers about a kilometre a second,
        so that band is a little over half a second of being inside it — long
        enough to be weather and not so long that the shot goes away.

        Not quite to white. A frame that reaches pure white reads as a cut to
        white, which is the one thing this intro does not have anywhere else.
      */
      const inside = 1 - Math.min(1, band / 400);
      this.grade.uniforms.uCloud.value = 0.93 * inside * inside * (3 - 2 * inside);

      this.clouds.children.forEach((plane, i) => {
        plane.position.y = (i - (layers - 1) / 2) * (SPREAD / layers);
        /*
          Thinner near the middle of the stack.

          The camera passes through the middle, and a layer at full opacity a
          few metres from the lens is a white frame. Weighted so the outside of
          the deck is what is seen from a distance and the inside is barely
          there, which is also what flying into cloud actually looks like.
        */
        const edge = Math.abs(i - (layers - 1) / 2) / ((layers - 1) / 2);
        plane.material.opacity = shown * (0.14 + 0.46 * edge);
      });
    }

    if (this.sky) this.sky.visible = above < 55000;

    /*
      Near and far, from altitude, and this is not a nicety.

      The camera was fixed at near 8, far 40,000,000 — the far plane has to
      clear the planet at the top of the move — which is a ratio of five million
      to one. A depth buffer cannot hold that. Every pixel quantised to 1.0, and
      the grade reads depth to decide what is sky:

          if (d >= 0.9999) { output the frame ungraded; return; }

      So at altitude *every* pixel took the sky path. The whole grade was
      silently off for the first half of the descent, which is why changing the
      exposure curve and then adding a gamma moved the measured brightness of
      those frames by nothing at all — twice, to the same decimal.

      Both planes scale with height instead. Near is a fiftieth of the altitude,
      far is twenty times it: about a thousand to one throughout, which a depth
      buffer holds comfortably. The floors matter at the bottom of the move,
      where the camera is eighty metres up and still needs to see a skyline
      twenty kilometres away.
    */
    /*
      Near from whichever is closer: the ground, or whatever the camera is
      flying at.

      A fiftieth of the altitude is right all the way down a descent and wrong
      in the last two seconds of this one, where the camera ends a quarter of a
      metre from a window and the floor of five metres would clip it out of
      existence. place() leaves the distance to what it is approaching in
      nearHint when there is one.
    */
    const near = Math.max(0.03, Math.min(above * 0.02, this.nearHint ?? Infinity));
    const far = Math.max(100000, above * 20);
    if (this.camera.near !== near || this.camera.far !== far) {
      this.camera.near = near;
      this.camera.far = far;
      this.camera.updateProjectionMatrix();
    }

    this.grade.uniforms.uNear.value = this.camera.near;
    this.grade.uniforms.uFar.value = this.camera.far;
    /*
      Haze distance from altitude.

      Roughly: standing in a street the far skyline should be gone, and from
      three kilometres up the city below should not be. Height above the ground
      is the one number separating those two cases, and it is already known.

      Floored at 600 so a camera on the pavement still gets aerial perspective,
      capped so the opening frames do not lose it altogether.
    */
    /*
      The cap has to clear the whole descent, not just the bottom of it.

      24,000 m was set when this shot began at 3,400. From six hundred
      kilometres the ground is six hundred kilometres away, which against a
      24 km haze horizon is twenty-five e-foldings: every pixel in frame goes to
      solid fog and the planet disappears into a flat rectangle. Four million
      metres is past anything this camera can be, so at altitude the haze does
      what it should, which is almost nothing.
    */
    /*
      Twenty times the altitude, not 1.6, and capped far higher.

      Aerial perspective is air between the camera and the subject, and from
      space there is almost none: the atmosphere is a shell a hundred kilometres
      deep and a camera three thousand kilometres up is outside it looking
      through it edge-on, not along it.

      At 1.6 the haze horizon was four thousand kilometres while the real
      horizon was six, so 79% of everything past the middle distance washed to
      one blue. Next to the globe's last frame — which has no haze at all, being
      a texture on a sphere — it read as a completely different altitude. The
      seam looked like a jump in scale and was a jump in atmosphere.

      Twenty puts the haze horizon at sixty thousand kilometres from space,
      which is effectively none, and still leaves about two kilometres of it at
      the bottom of the descent where a city street needs it.
    */
    this.grade.uniforms.uFog.value = Math.min(2e8, 600 + above * 20);
    // Full strength from about a hundred kilometres up, off by the time the
    // camera is among the buildings, where the imagery needs no help.
    const t = Math.min(1, Math.max(0, (above - 20000) / (600000 - 20000)));
    this.grade.uniforms.uLift.value = 1 + 0.62 * (t * t * (3 - 2 * t));
    /*
      Full at the handover, gone before the ground means anything.

      Wide on purpose. The fall is logarithmic, so 1,500 km to 200 km goes by in
      a little over a second, and a colour correction that switched off inside
      that would be a second seam put in to hide the first one. Spread across
      the whole band it reads as the air thickening, which at those altitudes is
      what is actually happening.
    */
    /*
      Faded in log space, because the fall is logarithmic.

      Linearly from 1,500 km to 200 km it was gone almost immediately: the
      camera passes 400 km about a second after the handover, and measured there
      the correction was down to nine per cent while the raw imagery had got
      *more* saturated, not less. So the ocean went muted, then vivid, inside a
      second — a colour move put in to hide a seam, creating a second one a beat
      later.

      A constant ratio per second is what the descent does, so the fade has to
      be a constant fraction per halving of altitude too. Full at three thousand
      kilometres, about two thirds at four hundred, a fifth at a hundred, and
      nothing by thirty, which is where the imagery starts being photographs of
      places rather than a plate.
    */
    const LOW = 30000;
    const p = Math.min(1, Math.max(0,
      Math.log(Math.max(above, LOW) / LOW) / Math.log(3000000 / LOW)));
    this.grade.uniforms.uPlate.value = p * p * (3 - 2 * p);
    /*
      The plate fades out between three thousand kilometres and three hundred,
      which is about two seconds of falling.

      Its own curve rather than uPlate's, because they are answering different
      questions. uPlate asks how much the *grade* still has to correct and runs
      all the way down to thirty kilometres. This asks how long NASA's imagery
      is a better picture than Google's, and the answer is: until Google's stops
      being a painted plate, which happens a good deal higher.

      Set before the defocus, not after, because the defocus reads it. It was
      the other way round for one edit, which cost nothing anywhere except on
      the single frame that matters: opacity starts at zero, so the first frame
      of the descent — the one the dissolve is pairing with the globe — read a
      plate that was not there yet and blurred itself at full strength.
    */
    const q = Math.min(1, Math.max(0,
      Math.log(Math.max(above, 300000) / 300000) / Math.log(3000000 / 300000)));
    if (this.plate) {
      this.plate.material.opacity = q * q * (3 - 2 * q);
      // Off rather than invisible, once it is contributing nothing. It covers
      // the whole frame with depth testing disabled, and a full-screen quad at
      // an opacity of nought point nought one is a cost with no picture in it.
      this.plate.visible = this.plate.material.opacity > 0.002;
    }

    /*
      Defocus only where Google's imagery is showing.

      This was tied to uPlate, from before the Blue Marble plate existed, when
      the frame at the handover *was* Google's tiles and had four times the fine
      detail of the globe. It does not any more: the plate is NASA's imagery at
      NASA's resolution, so blurring it makes the handover frame softer than the
      globe rather than equal to it, which is the same mismatch as before with
      the sign reversed. Measured on the difference between the two handover
      frames, it showed as a bright outline on every coastline — the signature
      of two images at different sharpness, not of two images in the wrong
      place, which is what it was mistaken for first.

      So it follows what the plate is *not* covering. Nothing at three thousand
      kilometres, where the picture is already the globe's picture; rising
      through the middle of the descent as the tiles come through underneath;
      gone by the time there is a city.
    */
    const showing = 1 - (this.plate ? this.plate.material.opacity : 0);
    this.grade.uniforms.uShow.value = showing;
    this.grade.uniforms.uSoft.value =
      SOFT * w * this.grade.uniforms.uPlate.value * showing;
    /*
      The tone curve follows the plate, not the altitude fade.

      It was fitted to put *NASA's plate* on the globe, and below three hundred
      kilometres there is no plate: what is on screen is Google's imagery, which
      the curve was never fitted for and which it would lift hard — level 65 to
      139 — for no reason. Tied to the plate it is full strength exactly where
      it was measured and gone exactly when the thing it corrects is gone.
    */
    this.grade.uniforms.uMatch.value = 1 - showing;
    this.grade.uniforms.uTexel.value.set(1 / w, 1 / h);

    this.renderer.setRenderTarget(this.target);
    this.renderer.render(this.scene, this.camera);
    // The patch, over the city, with its own depth. See where facadeScene is
    // built, in place().
    if (this.facadeScene && this.facade?.visible) {
      this.renderer.autoClear = false;
      this.renderer.clearDepth();
      this.renderer.render(this.facadeScene, this.camera);
      this.renderer.autoClear = true;
    }
    this.renderer.setRenderTarget(null);
    this.renderer.render(this.gradeScene, this.gradeCamera);
  }

  dispose() {
    this.tiles?.dispose();
    this.target?.dispose();
    this.grade?.dispose();
    this.quad?.geometry.dispose();
  }
}
