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

// Lower Manhattan, looking north up the island. Chosen because the skyline
// reads as New York from almost any angle here, which a residential street
// further uptown would not.
export const MANHATTAN = { lat: 40.7061, lon: -74.0087 };

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
  async load() {
    const key = import.meta.env.VITE_GOOGLE_MAPS_KEY;
    if (!key) throw new Error("no VITE_GOOGLE_MAPS_KEY in site/.env.local");

    const tiles = new TilesRenderer();
    tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: key }));
    // Tiles pop in as they arrive otherwise, and a building appearing whole in
    // front of the camera is the one thing that says "streaming" out loud.
    tiles.registerPlugin(new TilesFadePlugin({ fadeDuration: 400 }));

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

    this.tiles = tiles;
    this.ready = true;
    return this;
  }

  /*
    Where the camera is during the descent, as a fraction of the beat.

    Metres above the chosen point, easing in so it arrives among the buildings
    rather than at them. It ends low and close, looking slightly up, which is
    the framing the next clip has to pick up from: a window, seen from the
    street.
  */
  place(t, endHeight = 58) {
    /*
      Three overlapping moves, and none of them start or stop together.

      **Falling.** Eased at both ends: it leaves the top of the shot slowly,
      because a cut that begins already at speed reads as a jump, and it arrives
      slowly, because the last thing before a cut has to be still.

      **Closing.** The camera does not drop straight down. It comes in on a
      slant, which is what turns a descent into an approach: falling vertically
      onto a city gives you a map that gets bigger, and coming in at an angle
      gives you buildings that pass.

      **Tilting.** The aim rises as the camera falls, from looking down at a
      grid of blocks to looking level along a street and then slightly up at
      the front of a building. That is one continuous move rather than a
      separate pan, so there is no moment where the shot changes its mind.

      They are offset from each other on purpose. Beats that begin and end
      together read as a slideshow.
    */
    const easeInOut = (x) => (x < 0.5 ? 4 * x ** 3 : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const easeOut = (x) => 1 - Math.pow(1 - x, 3);

    const fall = easeInOut(t);
    // Starts a fifth of the way in and finishes early, so the last stretch is
    // the camera settling rather than still travelling.
    const close = easeOut(Math.min(1, Math.max(0, (t - 0.18) / 0.74)));
    const tilt = easeInOut(Math.min(1, Math.max(0, (t - 0.34) / 0.66)));

    /*
      3400 m down to about 58.

      Not to street level, and this is a limit of the data rather than a
      choice. Google's photogrammetry is captured from the air, so facades are
      reconstructed from oblique passes and windows are inferred: it holds up
      beautifully from above and smears into wax somewhere under about forty
      metres. Ending at roughly a fifth floor is the lowest altitude where a
      pre-war walk-up still has a fire escape you can see rather than a brown
      stain where one should be.

      That is also why the next beat is generated rather than flown. There is
      no photogrammetry of the inside of an apartment, and there is not much of
      the outside of one either.
    */
    const height = 3400 + (endHeight - 3400) * fall;
    // How far back along the street. It ends about a road's width away, which
    // is what puts a whole building front in frame rather than one brick.
    const back = 2600 + (34 - 2600) * close;
    // And a little to one side, so the building is met at an angle. Straight
    // on is an elevation drawing.
    const side = 900 + (11 - 900) * close;

    this.camera.position.set(side, height, back);

    /*
      What it looks at, which rises faster than the camera falls.

      At the start it is the ground: the aim is the origin and the camera is
      three kilometres above it, so the shot looks steeply down. By the end the
      aim is 26 m up the face of a building while the camera is at 58, so the
      lens is barely tilted down at all and a fifth-floor window sits in the
      upper half of the frame. The tilt is the difference between those two,
      and it happens without a separate move.
    */
    this.camera.lookAt(0, 26 * tilt, 0);
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
          uHigh:   { value: new THREE.Color(0x0a1526) },   // overhead
          uMid:    { value: new THREE.Color(0x1d3149) },
          uLow:    { value: new THREE.Color(0x4a4a58) },   // haze at the horizon
          uGlow:   { value: new THREE.Color(0xb8703f) },   // where the sun went
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
        uHaze:  { value: new THREE.Color(0x2f3d52) },
        uShade: { value: new THREE.Color(0x2c3f63) },   // kept for reference
        uWarm:  { value: new THREE.Color(0xffc07a) },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
      fragmentShader: `
        uniform sampler2D uScene;
        uniform sampler2D uDepth;
        uniform float uNear, uFar, uAmount;
        uniform vec3 uHaze, uShade, uWarm;
        varying vec2 vUv;

        // Metres from the camera. The depth buffer stores a nonlinear value,
        // and reading it as if it were linear puts every building at the far
        // plane, which is the mistake that killed the first attempt at this.
        float distanceAt(float d) {
          float ndc = d * 2.0 - 1.0;
          return (2.0 * uNear * uFar) / (uFar + uNear - ndc * (uFar - uNear));
        }

        void main() {
          vec3 day = texture2D(uScene, vUv).rgb;
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
          c *= mix(0.66, 0.34, smoothstep(0.15, 0.85, l));

          /*
            Shadows blue, highlights warm.

            As *tints* whose channels average one, not as multiplications by a
            dark colour. Multiplying by uShade darkened the shadows a second
            time on top of the exposure above, and the two compounded into
            almost nothing. A tint moves the hue and leaves the brightness where
            the exposure put it, which is what a grade is supposed to do.
          */
          vec3 cool = vec3(0.74, 0.89, 1.28);
          vec3 warm = vec3(1.26, 1.02, 0.74);
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
          float fog = 1.0 - exp(-distanceAt(d) / 900.0);
          c = mix(c, uHaze, clamp(fog, 0.0, 1.0) * 0.97);

          // A little lift, because air scatters and a true black at dusk is a
          // hole rather than a shadow.
          c += vec3(0.010, 0.015, 0.026);

          float r = distance(vUv, vec2(0.5)) * 1.42;
          c *= 1.0 - 0.30 * pow(clamp(r, 0.0, 1.0), 2.4);

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
    this.grade.uniforms.uNear.value = this.camera.near;
    this.grade.uniforms.uFar.value = this.camera.far;

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
