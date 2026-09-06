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
  async load({ fade = true } = {}) {
    const key = import.meta.env.VITE_GOOGLE_MAPS_KEY;
    if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");

    const tiles = new TilesRenderer();
    tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: key }));
    // Tiles pop in as they arrive otherwise, and a building appearing whole in
    // front of the camera is the one thing that says "streaming" out loud.
    if (fade) tiles.registerPlugin(new TilesFadePlugin({ fadeDuration: 400 }));

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
    const settled = !stats.downloading && !stats.parsing;
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
    const ray = new THREE.Raycaster(
      new THREE.Vector3(0, 6000, 0), new THREE.Vector3(0, -1, 0), 0, 30000);
    const hits = ray.intersectObject(this.tiles.group, true);
    if (!hits.length) return null;
    this.ground = hits[0].point.y;
    this.groundSettled = settled;
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
  place(t, endHeight = 80) {
    /*
      Heights are metres above the street, not above the origin.

      getObjectFrame puts the ellipsoid surface at zero and over Manhattan the
      street is sixteen metres below it, so taking the origin for the ground put
      every framing nine floors too high. See groundLevel().

      Falls back to zero while the first tiles are still arriving, which only
      affects the opening frames — six hundred kilometres up, sixteen metres is
      not a rounding error, it is nothing at all.
    */
    const floor = this.groundLevel() ?? 0;

    const clamp01 = (x) => Math.max(0, Math.min(1, x));
    // Hermite, the same curve smoothstep uses: zero slope at both ends, so the
    // tilt begins and finishes without a corner.
    const smooth = (x) => { const c = clamp01(x); return c * c * (3 - 2 * c); };

    /*
      Log space, and eased out only.

      The log is what makes it read as a zoom rather than a fall: a constant
      ratio per second, so every second roughly halves the height all the way
      down. The easing on top of it decides whether that ratio is actually
      constant, and the first version got it wrong in a way that measurement
      caught and four frames on a contact sheet did not.

      It was ease-in-out. An ease-in has zero slope at zero, so over the opening
      frames the height changed by nothing: scripts/check-intro.mjs counted 34
      near-still frames — more than a second of a camera that is supposed to be
      falling from orbit doing nothing — and then the middle of the curve lurched
      at 8.4% a frame to catch up. Starting still and then rushing is precisely
      the "stopping" this shot is not allowed to do.

      A gentle ease-out instead. 3.45% a frame at the top, 2.89% in the middle,
      0.64% at the end: it moves from the first frame, the rate varies by three
      per cent across the whole descent, and it settles into the arrival rather
      than hitting it. Past about 1.6 the tail decelerates to a standstill and
      the stall comes back at the other end.
    */
    /*
      Three thousand kilometres, not six hundred.

      This is where the Earth beat hands over, and the two have to agree to the
      metre or the join is a jump. The globe dives to 1.47 Earth radii — the
      surface is 1, so that is 3,000 km — looking straight down at the same
      point, and this picks the fall up from there.

      Higher is also the only altitude the handover can work at. Blue Marble is
      7.4 km a pixel: at six hundred kilometres the globe is showing about
      fifty texture pixels across the frame, which no amount of matching makes
      look like a photograph. At three thousand it is showing three hundred,
      soft rather than absent, and a soft frame dissolving into a sharp one at
      identical framing reads as detail arriving.
    */
    // The curve itself lives in handover.js, because the globe's last quarter
    // second runs it too. Two copies of it drifted apart once already and the
    // symptom was the seam this whole rebuild was chasing.
    const height = fallHeight(t, endHeight);

    /*
      The last fifth of the shot, and nothing before it.

      Until 0.80 the camera is directly over the target looking straight down,
      which is what a descent from orbit looks like and what keeps the move
      legible while the ground is still a map. Then it swings back and out to
      about a street's width and the aim rises to fifty metres, so the shot
      finishes looking along a block at building fronts.
    */
    /*
      The tilt takes the last 45% rather than the last 20%.

      At 20% it is a ninety-degree swing in under two seconds, and
      check-intro.mjs measured the frame-to-frame change at four and a half
      times the run of the shot for a solid half-second — a pan fast enough to
      read as a whip. Nothing was wrong with it geometrically; it was hurried.

      Spread over 45% it overlaps most of the second half of the fall, which is
      also better than a pan that waits for the descent to finish and then
      happens: the camera straightens as it arrives rather than after.
    */
    const tilt = smooth((t - 0.55) / 0.45);

    // Not exactly zero before the tilt: a camera at precisely (0, h, 0) looking
    // at (0, 0, 0) is looking straight down its own up-vector, and lookAt has
    // no way to choose a roll. It gimbals, and the picture spins. A thousandth
    // of the altitude is enough to give it an answer and is invisible.
    const back = height * 0.001 + (95 - height * 0.001) * tilt;
    const side = height * 0.0004 + (34 - height * 0.0004) * tilt;

    this.camera.position.set(side, floor + height, back);
    /*
      Roll, stated instead of inferred. See the north vector in load().

      North at the top while the camera is over the target, swinging to sky at
      the top as it pitches up at the end. That lerp is not a stylistic choice;
      it is what a camera with a fixed heading does as it pitches from nadir to
      the horizon. The direction that was at the top of the frame goes on being
      at the top of the frame, and the sky arrives underneath it.
    */
    this.camera.up.copy(this.north ?? new THREE.Vector3(0, 0, 1))
      .lerp(new THREE.Vector3(0, 1, 0), tilt).normalize();
    this.camera.lookAt(0, floor + 50 * tilt, 0);
    this.camera.updateMatrixWorld();
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
        uniform float uNear, uFar, uAmount, uFog, uLift, uPlate, uSoft, uMatch;
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
          if (d >= 0.9999) { gl_FragColor = vec4(day, 1.0); return; }

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
          c *= mix(1.02, 0.86, smoothstep(0.15, 0.85, l));

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
          c *= mix(cool, warm, smoothstep(0.10, 0.52, l));

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
    const near = Math.max(5, above * 0.02);
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
      Defocus on the same log fade as the colour, for the same reason: the fall
      is logarithmic, so anything tied to altitude has to be.

      The radius is set from measurement, not from taste. See uSoft.
    */
    this.grade.uniforms.uSoft.value = SOFT * w * this.grade.uniforms.uPlate.value;
    this.grade.uniforms.uMatch.value = this.grade.uniforms.uPlate.value;
    this.grade.uniforms.uTexel.value.set(1 / w, 1 / h);

    this.renderer.setRenderTarget(this.target);
    this.renderer.render(this.scene, this.camera);
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
