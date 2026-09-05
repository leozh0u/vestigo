/*
  The globe.

  Three.js vocabulary, which is the whole of what you need to read this file:

    Scene     the world. Everything visible is added to it.
    Camera    where you look from, and how wide the view is.
    Mesh      one object: a geometry (its shape) and a material (its surface).
    Renderer  draws the scene from the camera, once per frame.

  ## The two Earths

  The page has to go from machined metal to a living planet without the swap
  being visible. Materials cannot cross-fade between two completely different
  surfaces on their own, so there are two spheres: metal at radius 1, nature a
  hair larger at 1.001, and the second fades in over the first.

  A hair larger, not the same size. Two surfaces at identical radius fight over
  which is in front, pixel by pixel, and the result flickers as the sphere
  turns. That artifact has a name, z-fighting, and the fix is always to give
  one of them somewhere else to be.

  ## Why metal needs surroundings

  Metal has almost no colour of its own. What you see in chrome is the room.
  A metallic material with nothing to reflect renders as a black ball, which is
  exactly what this file did on its first run. The environment map below is a
  studio painted in code: bright above, dark below, two hard softboxes whose
  edges become the highlight that rolls across the surface.
*/
import * as THREE from "three";

/*
  Where the sun is, and it is behind the planet.

  This was the single thing keeping the globe from reading as Earth. The sun
  sat at (2.4, 1.0, 2.6) — the same side as the camera, which is at z = 3.55.
  So the face you were looking at was the day face, fully lit, and NASA's city
  lights were all on the hemisphere pointing away from you. The night texture
  was loaded, sampled and working; it was simply aimed at nobody.

  Behind and to the left instead. The visible disc is mostly night, with the
  terminator running down the left limb and a thin crescent of daylight beyond
  it, which is what the planet looks like from orbit on the dark side and what
  makes the lights mean anything.

  One vector, used three times: the key light's position, the shader's idea of
  which half is dark, and the atmosphere's idea of which limb is bright. They
  were three separate numbers before and there is no version of this where they
  should disagree.
*/
const SUN = new THREE.Vector3(-2.35, 0.62, -1.85).normalize();

/*
  The living Earth is NASA's, not mine.

  The procedural map was drawn from coastline polygons: latitude bands for
  climate, noise for terrain, a rule about how far inland the deserts start.
  It was a diagram of Earth, and no amount of tuning gets a diagram to the
  point where somebody says it looks real, because what they compare it
  against is a photograph.

  Blue Marble Next Generation is that photograph: a cloud-free true-colour
  composite of the whole planet at 500 m per pixel. Black Marble is the night
  lights. Both public domain, fetched by scripts/fetch_earth_imagery.py.

  The metal half stays procedural, because that one is not trying to be real.
*/
const TEXTURES = {
  metal: "/textures/globe-metal.png",
  natural: "/textures/earth-day.jpg",
  land: "/textures/globe-land.png",
  growth: "/textures/globe-growth.png",
  relief: "/textures/globe-relief.png",
  lights: "/textures/earth-night.jpg",
  // The same lights, blurred. See the glow note in the shader below.
  glow: "/textures/earth-glow.jpg",
  clouds: "/textures/globe-clouds.png",
  rough: "/textures/globe-rough.png",
  normal: "/textures/globe-normal.png",
};

export class Globe {
  constructor(canvas) {
    this.canvas = canvas;
    this.progress = 0;
    // Where the run says it has got to, as opposed to where the surface has
    // got to. See setProgress and ease.
    this.targetProgress = 0;
    this.spin = 0.045;
    // The flight turns this off. An idle rotation and a directed one fight
    // each other, and the fight looks like a stutter.
    this.spinning = true;

    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, alpha: true,
    });
    // Capped at 2. A 3x display renders nine times the pixels of a 1x one for
    // a difference nobody can see, and this page has to open quickly on a
    // laptop somebody else owns.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.45;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    this.camera.position.set(0, 0, 3.55);
    // Lifted, so the sphere sits above the controls instead of behind them.
    this.camera.position.y = 0.18;

    this.scene.environment = this.buildEnvironment();

    // Key light from behind and left. Metal reads as metal because of the
    // bright edge on its silhouette, which an environment map alone will not
    // give you.
    this.rim = new THREE.DirectionalLight(0xdCE9FF, 3.1);
    this.rim.position.set(-3.2, 1.4, -1.8);
    this.scene.add(this.rim);
    /*
      The key light, and it doubles as the sun glint on the ocean.

      At 1.5 the glint was a soft white blob covering most of the North
      Atlantic. A real glint is small and hard: the sun is half a degree wide
      seen from Earth, so what it makes on water is a tight spot, not a wash.
      Lower intensity with a rougher sea is what tightens it.
    */
    this.key = new THREE.DirectionalLight(0xfff4e2, 0.85);
    this.key.position.copy(SUN).multiplyScalar(4);
    this.scene.add(this.key);
    /*
      Ambient, and it has to leave.

      Metal barely notices it: at metalness 0.95 there is almost no diffuse
      term for an ambient light to land on, and the environment map does that
      surface's work. Once the world comes alive metalness drops to near zero,
      diffuse takes over, and 0.95 of uniform blue-grey floods the night side
      into a flat wash — a planet lit from nowhere, which is the look of a
      model rather than of a photograph.

      So it fades out with growth. Not to zero: there is moonlight and airglow
      on a real night side, and pure black reads as a hole cut in the frame.
    */
    this.ambient = new THREE.AmbientLight(0x5c6b80, 0.95);
    this.scene.add(this.ambient);

    const loader = new THREE.TextureLoader();
    const load = (url, srgb = true) => {
      const t = loader.load(url);
      if (srgb) t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      return t;
    };

    /*
      One sphere, not two.

      The first version cross-faded a metal sphere into an Earth sphere. That
      works and it looks like a dissolve, which is the wrong idea: the planet
      should come alive, not be swapped for a different planet.

      So the two surfaces live on one material and a shader decides, per pixel,
      which one is showing. `globe-growth.png` gives every pixel a moment
      between 0 and 1; the uniform `uGrowth` is the clock. A pixel is alive
      once the clock passes its moment, with a soft band at the boundary so the
      edge reads as spreading rather than as a wipe.

      The map is ordered so land greens in patches that widen and join, the way
      moss does, while the sea fills from the deep basins in towards the
      coastline. Both effects come out of the same two lines below because the
      ordering was done when the texture was written.

      onBeforeCompile is three.js's supported way in: it hands you the standard
      material's shader source before it is compiled, so the physically based
      lighting, the environment map and the tone mapping all keep working and
      only the surface colour is replaced.
    */
    this.uniforms = {
      uGrowth: { value: 0 },
      uNatural: { value: load(TEXTURES.natural) },
      uGrowthMap: { value: load(TEXTURES.growth, false) },
      uLand: { value: load(TEXTURES.land, false) },
      uLights: { value: load(TEXTURES.lights, false) },
      uGlow: { value: load(TEXTURES.glow, false) },
      // How much of the night look is in force. Ties the darkening of the
      // night side to the same clock as everything else, so metal is never
      // half-nocturnal.
      uNight: { value: 0 },
      // Which way the sun is, in world space. The shader needs it to know
      // which half of the planet is dark, and lights only belong on the dark
      // half. Kept in step with the key light in render().
      uSun: { value: SUN.clone() },
    };

    this.material = new THREE.MeshStandardMaterial({
      map: load(TEXTURES.metal),
      /*
        The two maps that stop this reading as plastic.

        A uniform roughness gives a uniform sheen, and a uniform sheen is what
        plastic looks like: one soft highlight, identical everywhere, sliding
        over a shape that has no surface. The roughness map varies it per pixel
        with a grain stretched around the sphere, so the reflection is sharp in
        some places and smeared in others and the boundary reads as machining.

        The normal map tilts each pixel by a fraction of a degree. That is
        enough to make the highlight travel unevenly as the globe turns, and
        uneven highlight travel is most of what separates metal from a grey
        ball. Neither is visible on its own; together they are the difference.
      */
      roughnessMap: load(TEXTURES.rough, false),
      normalMap: load(TEXTURES.normal, false),
      // Halved. The normal map is machining marks, which belong on tungsten
      // and not on an ocean, and there is no way to fade a normal map per
      // pixel from inside the standard material. Lowering it costs the metal
      // a little bite and stops the living Earth being visibly grooved.
      normalScale: new THREE.Vector2(0.28, 0.28),
      /*
        Displacement, not just a normal map, and the difference matters here.

        A normal map fakes the lighting of relief and leaves the silhouette
        flat, which is right for machining marks and wrong for continents. This
        has to show on the limb of the sphere, because the limb is where the
        eye checks whether a surface is real, and it is what makes water
        filling the oceans mean anything: the sea arrives in a basin that is
        already there rather than being a colour applied to a region.

        Small, and smaller than the first attempt. 0.02 of a unit radius is
        about 130 km of exaggeration at Earth scale: absurd geographically and
        about right visually. At 0.035 the coastlines tore into a visible
        staircase, because the amplitude was large enough for the mesh to show
        where one vertex ended and the next began.
      */
      displacementMap: load(TEXTURES.relief, false),
      displacementScale: 0.02,
      displacementBias: -0.007,
      metalness: 0.95,
      // The map supplies the variation, so the base is a multiplier and stays
      // at 1. Setting both fights: the map would be scaled down into a narrow
      // band and the variation would disappear.
      roughness: 1.0,
      envMapIntensity: 2.6,
    });

    this.material.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, this.uniforms);
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", `
          #include <common>
          uniform float uGrowth;
          uniform sampler2D uNatural;
          uniform sampler2D uGrowthMap;
          uniform sampler2D uLand;
          uniform sampler2D uLights;
          uniform sampler2D uGlow;
          uniform float uNight;
          uniform vec3 uSun;
          varying vec2 vGlobeUv;
          varying vec3 vGlobeNormal;
        `)
        // The colour is decided here, where diffuseColor exists.
        .replace("#include <map_fragment>", `
          #include <map_fragment>
          float vMoment = texture2D(uGrowthMap, vGlobeUv).r;
          float vLand = texture2D(uLand, vGlobeUv).r;
          // The clock runs slightly past 1, so the last pixels finish rather
          // than being left one frame short of alive.
          float vClock = uGrowth * 1.12;
          // A soft band at the advancing front: narrow enough to read as a
          // front, wide enough not to alias into a jagged line.
          float vAlive = smoothstep(vMoment - 0.09, vMoment + 0.09, vClock);
          float vWet = (1.0 - vLand) * vAlive;
          vec4 vLiving = texture2D(uNatural, vGlobeUv);
          /*
            Blue Marble is a daylight photograph of every part of the planet at
            once, which is convenient and is not a thing you can ever see. The
            lighting handles most of the correction — the sun is behind, so the
            face you are looking at gets almost no direct light — but the
            daytime albedo is still there underneath, and a fully dark ocean
            that is nonetheless the colour of a lit ocean reads as grey plastic.

            So the night side loses most of its colour and keeps a little, cold.
            The little that is kept is not decoration: cloud and ice do pick up
            moonlight, and a night side at zero is a hole rather than a planet.
          */
          float vDark = smoothstep(0.26, -0.34, dot(normalize(vGlobeNormal), uSun)) * uNight;
          vec3 vNightAlbedo = mix(vLiving.rgb, vec3(0.026, 0.034, 0.052),
                                  0.94 * vDark);
          diffuseColor.rgb = mix(diffuseColor.rgb, vNightAlbedo, vAlive);
        `)
        /*
          The surface properties are decided in their own chunks, further down,
          because that is where three.js declares them. Writing to
          roughnessFactor next to the colour fails to compile: at that point in
          the generated shader the variable does not exist yet. The values
          computed above are still in scope here, since it is all one function.

          Once a pixel is alive it stops behaving like metal, and the two
          halves part company: land goes matte, sea stays glossy. That
          difference is the strongest single cue that a sphere is wet in some
          places and dry in others.
        */
        .replace("#include <roughnessmap_fragment>", `
          #include <roughnessmap_fragment>
          // Until a pixel is alive, roughnessFactor is whatever the metal's
          // roughness map said, which is the machining. Only once it comes
          // alive does it become land or water.
          // 0.34 for water, not 0.14. At 0.14 the sea was a mirror and the
          // anisotropic grain from the metal's roughness map showed straight
          // through it as bright streaks running around the globe: the planet
          // came alive still wearing its machining. Ocean seen from orbit is
          // not a mirror at this scale.
          // 0.58 for water, up from 0.46. Rougher water spreads the sun's
          // reflection over more of the surface and so makes it dimmer
          // everywhere, which is what stops the grazing light along the
          // terminator collecting into a single hard sheet.
          roughnessFactor = mix(roughnessFactor, mix(0.92, 0.58, vWet), vAlive);
        `)
        .replace("#include <metalnessmap_fragment>", `
          #include <metalnessmap_fragment>
          metalnessFactor = mix(metalnessFactor, mix(0.02, 0.12, vWet), vAlive);
        `)
        /*
          City lights, added at the very end.

          A planet with a dark half and nothing on it reads as a model of a
          planet. The lights are the clearest signal the thing is inhabited,
          and the detail people check without knowing they are checking it.

          Added after tone mapping rather than mixed into the surface colour,
          because these emit light rather than reflect it: a lit window does
          not get darker when the sun goes down, which is what folding them
          into the albedo would do.

          The night term is one where the surface faces away from the sun, and the
          smoothstep makes a soft terminator instead of a hard line across the
          globe. They fade in with the world, so metal has no cities on it.
        */
        .replace("#include <tonemapping_fragment>", `
          /*
            The night side.

            The night term is one where the surface faces away from the sun. The
            smoothstep either side of zero makes a terminator with width to it
            rather than a hard line drawn across the planet: the real one is a
            band a few hundred kilometres across where the sun is setting, and
            a hard edge is the first thing that gives away a sphere with a
            texture on it.
          */
          float night = smoothstep(0.26, -0.34, dot(normalize(vGlobeNormal), uSun));

          /*
            Two samples of the same mosaic, and the second one is the whole
            trick.

            The first, lamps, is Black Marble as it ships: pin-sharp points, one per
            settlement. On its own that reads as pixels rather than as light,
            because light seen through fifty kilometres of air does not stop at
            the edge of the city. It scatters into a halo, and the halo is what
            your eye reads as brightness.

            The usual way to get that is a bloom pass over the finished frame.
            This canvas has to stay transparent — the drifting field of
            readings sits behind it — and every screen-space bloom writes an
            opaque alpha over the whole rectangle, so the planet would arrive
            with a black box around it.

            uGlow is the same mosaic blurred once, offline, by
            scripts/fetch_earth_imagery.py. Sharp core plus soft halo, no post
            pass, nothing to fight with the alpha, and it costs one texture
            read.
          */
          float lamps = texture2D(uLights, vGlobeUv).r;
          float halo  = texture2D(uGlow, vGlobeUv).r;
          // No squaring any more. It was there to suppress the mosaic's
          // land-and-ocean base layer, which put a tan wash over the Sahara and
          // the Amazon, and that layer is now cut away in
          // scripts/fetch_earth_imagery.py where it can be cut cleanly. Holding
          // the curve down as well took out every town below a capital city.
          float cores = lamps;
          // Sodium, not white. Street lighting is warm and satellite mosaics
          // record it that way; a white city is the tell of a synthetic map.
          vec3 warm = vec3(1.00, 0.86, 0.60);
          vec3 lit  = warm * cores * 3.1 + warm * halo * halo * 1.15;
          gl_FragColor.rgb += lit * night * vAlive;
          #include <tonemapping_fragment>
        `);

      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", `
          #include <common>
          varying vec2 vGlobeUv;
          varying vec3 vGlobeNormal;
        `)
        .replace("#include <uv_vertex>", `
          #include <uv_vertex>
          vGlobeUv = uv;
        `)
        .replace("#include <defaultnormal_vertex>", `
          #include <defaultnormal_vertex>
          vGlobeNormal = normalize(mat3(modelMatrix) * objectNormal);
        `);
    };

    this.earth = new THREE.Mesh(
      /*
        160, and this is the one place the vertex count earns itself.

        A displacement map moves vertices, so continents can only be as
        detailed as the mesh under them: at 96 segments the coastlines came out
        as a polygon. The earlier cut to 96 was made when nothing was displaced
        and every feature was painted, where segments bought only a smoother
        outline.

        Cost is a fixed vertex load once per frame, which is not what made this
        page slow. That was four backdrop-filter blurs reading the framebuffer
        back and a hundred animated text nodes; both are gone.
      */
      new THREE.SphereGeometry(1, 160, 160),
      this.material,
    );
    this.scene.add(this.earth);
    // Kept as an alias: the flight and the drag were written against
    // `metal`, and one sphere now serves both roles.
    this.metal = this.earth;

    /*
      Atmosphere.

      The first version was a plain coloured sphere five percent larger than
      the planet, rendered from the inside and added. That does not read as
      atmosphere: because the colour is uniform, you see the shell's own
      silhouette, so the planet gets a distinct blue ring around it with a
      visible gap between the ring and the ground. It looks like a sticker.

      Air does not work that way. Looking straight down you see through very
      little of it and it is nearly invisible; looking at the limb your line of
      sight passes through hundreds of kilometres of it and it piles up into a
      bright band. So the brightness has to depend on how edge-on the surface
      is, which is a Fresnel term: one minus the dot product of the view
      direction and the normal.

      Closer, too. 1.5% rather than 5%, because the real atmosphere is a
      hundred kilometres on a six thousand kilometre planet and the shell only
      needs to be thick enough to hold the gradient.

      ## The version that was wrong anyway

      Even as a Fresnel term this drew an even blue ring all the way round the
      disc, and an even ring is the thing that made the planet look drawn. Air
      is not lit from inside. It is lit by the sun, so the band is bright where
      the sun is coming round the limb and it is very nearly nothing on the far
      side of the night. A photograph from the station at night has a hard
      orange-into-blue line along one edge and darkness everywhere else.

      So the same sun that decides where the cities are also decides where this
      is, the exponent went from four to seven to pull it off the disc and onto
      the edge, and the strength went to about a fifth. What is left is a line
      rather than a halo.
    */
    this.halo = new THREE.Mesh(
      new THREE.SphereGeometry(1.015, 96, 96),
      new THREE.ShaderMaterial({
        uniforms: {
          uOpacity: { value: 0 },
          // Cool for the band itself, warm for the few degrees right at the
          // terminator where the light is coming through the most air. That
          // gradient, sunrise orange into upper-atmosphere blue, is the part
          // of a limb shot people recognise without being able to name.
          uColor: { value: new THREE.Color(0x6fb4e8) },
          uDawn: { value: new THREE.Color(0xff9a55) },
          uSun: { value: SUN.clone() },
        },
        vertexShader: `
          varying vec3 vNormalW;
          varying vec3 vViewW;
          void main() {
            vec4 world = modelMatrix * vec4(position, 1.0);
            vNormalW = normalize(mat3(modelMatrix) * normal);
            vViewW = normalize(cameraPosition - world.xyz);
            gl_Position = projectionMatrix * viewMatrix * world;
          }`,
        fragmentShader: `
          uniform float uOpacity;
          uniform vec3 uColor;
          uniform vec3 uDawn;
          uniform vec3 uSun;
          varying vec3 vNormalW;
          varying vec3 vViewW;
          void main() {
            vec3 n = normalize(vNormalW);
            // Zero looking straight down, one at the limb. The seventh power
            // keeps it off the disc: a lower exponent hazes the whole planet,
            // which is what the ring around the globe was.
            float rim = 1.0 - abs(dot(n, normalize(vViewW)));
            float glow = pow(clamp(rim, 0.0, 1.0), 7.0);
            // Air is lit by the sun, so the band exists where the sun does.
            // A floor of 0.06 rather than zero, because scattering carries a
            // little light around the limb and a band that stops dead looks
            // like a shape rather than like atmosphere.
            float sun = dot(n, normalize(uSun));
            float facing = max(smoothstep(-0.45, 0.35, sun), 0.06);
            // Sunrise orange only in the few degrees either side of the
            // terminator, blue everywhere the sun is properly up.
            vec3 tint = mix(uDawn, uColor, smoothstep(-0.05, 0.45, sun));
            gl_FragColor = vec4(tint, glow * facing * uOpacity);
          }`,
        transparent: true,
        side: THREE.BackSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.scene.add(this.halo);

    this.markers = new THREE.Group();
    this.earth.add(this.markers);

    this.resize();
    this._onResize = () => this.resize();
    window.addEventListener("resize", this._onResize);
  }

  buildEnvironment() {
    // A studio in code. The first version was a smooth dark gradient and the
    // sphere rendered as a black ball: dark surroundings give you a dark
    // sphere whatever the material says. What makes chrome read as chrome is
    // contrast in what it reflects, so there are hard bright shapes here and
    // their edges are the highlights you see on the surface.
    const w = 1024, h = 512;
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");

    // Bright. A fully metallic surface shows only what it reflects, so the
    // brightness of this image is the brightness of the sphere: the base
    // colour of the texture barely contributes at metalness 1. Two earlier
    // attempts made the texture lighter and the ball stayed dark, because the
    // texture was never the thing being looked at.
    const sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0.00, "#c8d4e4");
    sky.addColorStop(0.34, "#8d9cb0");
    sky.addColorStop(0.50, "#3a444f");
    sky.addColorStop(0.62, "#141920");
    sky.addColorStop(1.00, "#070a0e");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);

    const box = (x, y, bw, bh, alpha) => {
      const g = ctx.createRadialGradient(x, y, 0, x, y, Math.max(bw, bh));
      g.addColorStop(0, `rgba(228,238,255,${alpha})`);
      g.addColorStop(1, "rgba(228,238,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(x - bw, y - bh, bw * 2, bh * 2);
    };
    box(w * 0.20, h * 0.26, w * 0.19, h * 0.28, 1.0);
    box(w * 0.74, h * 0.36, w * 0.13, h * 0.19, 0.7);
    box(w * 0.48, h * 0.14, w * 0.24, h * 0.12, 0.5);

    const texture = new THREE.CanvasTexture(canvas);
    texture.mapping = THREE.EquirectangularReflectionMapping;
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }

  /*
    Where the run has got to. Not where the surface has got to.

    The player reports progress once per step, so this arrives as about
    twenty-seven discrete jumps held four hundred milliseconds each. Applied
    straight to the shader that is a staircase, and it looked like one: the
    world lurched forward and stopped, lurched and stopped.

    So this sets a target and `ease` walks the surface towards it every frame.
    The run stays in charge of how far the world has come, and the frame loop
    is in charge of how it gets there, which is the split that was missing.
  */
  setProgress(t) {
    this.targetProgress = Math.min(1, Math.max(0, t));
  }

  /*
    One frame of catching up.

    Exponential rather than linear: the distance remaining is cut by a fixed
    fraction each second, so it moves quickly when it is far behind and settles
    softly. Framerate-independent, because the fraction is raised to the power
    of the elapsed time rather than applied once per frame; done the naive way
    the world grows faster on a fast machine.
  */
  ease(dt) {
    const remaining = this.targetProgress - this.progress;
    if (Math.abs(remaining) < 0.0005) {
      this.progress = this.targetProgress;
    } else {
      this.progress += remaining * (1 - Math.pow(0.06, dt));
    }
    this.apply(this.progress);
  }

  apply(k) {
    const eased = k * k * (3 - 2 * k);          // smoothstep

    this.uniforms.uGrowth.value = eased;
    this.uniforms.uNight.value = eased;
    // 0.34, down from 1.5. See the atmosphere note above: what is wanted is a
    // line along one limb, not a ring around the planet.
    this.halo.material.uniforms.uOpacity.value = 0.34 * eased;
    /*
      The lighting changes character as the world arrives.

      Metal wants a studio: a hard rim behind it to draw its silhouette and
      enough ambient to keep it off black. A night Earth wants none of that. It
      wants one sun, behind, and nothing else, so that the only bright things on
      the visible face are the cities.

      Fading between the two is why the ambient and rim lights are held on the
      instance rather than dropped into the scene and forgotten.
    */
    this.ambient.intensity = 0.95 * (1 - eased) + 0.05 * eased;
    this.rim.intensity = 3.1 * (1 - eased) + 0.12 * eased;
    // Sunlight proper, once there is a planet for it to fall on. It lights the
    // crescent past the terminator and nothing else.
    /*
      1.55, and it was 2.75 for one render.

      The sun is half a degree wide seen from Earth, so what it makes on water
      is a small hard spot. At grazing incidence along the terminator a bright
      key spreads that spot into a band down the whole limb, and a white band
      down the limb of a mostly dark planet does not read as sunrise. It reads
      as the polished metal this surface used to be.
    */
    this.key.intensity = 0.85 + 0.70 * eased;
    // The reflections fade as the surface stops being metal. Without this the
    // sea keeps a chrome sheen and the planet reads as painted metal rather
    // than as water.
    /*
      The environment map goes away almost entirely.

      It is a studio: a bright sky and three hard-edged softboxes, built so
      tungsten reads as tungsten. An ocean reflecting that studio picks up the
      softbox edges as bright bands running around the globe, which is exactly
      what it did once the satellite imagery went in. Real ocean from orbit has
      one sun glint, not stripes.

      Held at 0.06 rather than zero so water keeps some sky in it. The
      directional lights supply the glint, and one moving highlight is what a
      sea looks like from space.
    */
    // 0.02, not 0.06. On a day side 0.06 of a studio is a hint of sky in the
    // water. On a night side it is the studio's softbox, dragged out along the
    // terminator into a chrome smear a thousand kilometres wide, and it was
    // the last thing on the sphere that still looked machined.
    this.material.envMapIntensity = 2.6 * (1 - eased) + 0.02 * eased;

    /*
      The machining marks go with it, and this was the actual cause of the
      bands across the Atlantic.

      The normal map is an anisotropic grain, grooves running around the
      sphere, and it is what makes tungsten look turned rather than moulded.
      It was still applying at full strength once the satellite imagery
      arrived, so the directional lights raked across those grooves and drew
      bright stripes over the ocean. Fading the environment map did nothing,
      because the environment map was not what was doing it.

      normalScale is a material uniform rather than a per-pixel value, so it
      cannot be faded only over water from out here. It does not need to be:
      by the time the world is alive there is no metal left for it to serve.
    */
    this.material.normalScale.setScalar(0.28 * (1 - eased));
    /*
      Exposure comes down hard, and this is the difference between a night
      side and a dim day side.

      1.45 is a studio exposure: it exists to keep tungsten off black. Held
      there over a night Earth, ACES lifts the near-black ocean into visible
      grey and rolls the brightest cities off into flat white, so you get a
      grey planet with white smears. Down at 0.86 the ocean stays where it
      belongs and the cities have somewhere to go.
    */
    this.renderer.toneMappingExposure = 1.45 - 0.59 * eased;
    // It wakes up as it works out where it is.
    this.spin = 0.045 + 0.03 * eased;
  }

  /*
    Latitude and longitude to a point on the sphere.

    Longitude is negated because the texture and the maths wind opposite ways,
    which is the usual reason a marker lands in the mirror image of where it
    belongs. Check it against a city you know the first time you use it.
  */
  static toVector(lat, lon, radius = 1) {
    const phi = (90 - lat) * (Math.PI / 180);
    const theta = (lon + 180) * (Math.PI / 180);
    return new THREE.Vector3(
      -radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.sin(theta),
    );
  }

  mark(lat, lon, { color = 0x6ee7a8, size = 0.014 } = {}) {
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(size, 12, 12),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 }),
    );
    dot.position.copy(Globe.toVector(lat, lon, 1.01));
    this.markers.add(dot);
    return dot;
  }

  clearMarkers() {
    for (const child of [...this.markers.children]) {
      child.geometry.dispose();
      child.material.dispose();
      this.markers.remove(child);
    }
  }

  resize() {
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  render(dt) {
    // Growth is eased here rather than being set by the run, so the twenty-odd
    // discrete steps the player reports become a curve. Without this call the
    // world never changes at all, which is what it did: the method existed and
    // nothing invoked it.
    this.ease(dt);
    if (this.spinning) this.metal.rotation.y += dt * this.spin;
    // The spheres are one object as far as a viewer is concerned, so the
    // others copy the first rather than being animated alongside it. Two
    // things animated separately eventually disagree.
    this.halo.rotation.copy(this.earth.rotation);
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    window.removeEventListener("resize", this._onResize);
    this.clearMarkers();
    this.earth.geometry.dispose();
    this.material.dispose();
    this.halo.geometry.dispose();
    this.halo.material.dispose();
    this.renderer.dispose();
  }
}
