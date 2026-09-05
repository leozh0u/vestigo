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

const TEXTURES = {
  metal: "/textures/globe-metal.png",
  natural: "/textures/globe-natural.png",
  land: "/textures/globe-land.png",
  growth: "/textures/globe-growth.png",
};

export class Globe {
  constructor(canvas) {
    this.canvas = canvas;
    this.progress = 0;
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
    const rim = new THREE.DirectionalLight(0xdCE9FF, 3.1);
    rim.position.set(-3.2, 1.4, -1.8);
    this.scene.add(rim);
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(2.4, 1.0, 2.6);
    this.scene.add(key);
    this.scene.add(new THREE.AmbientLight(0x4a5666, 0.55));

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
    };

    this.material = new THREE.MeshStandardMaterial({
      map: load(TEXTURES.metal),
      metalness: 0.86,
      roughness: 0.29,
      envMapIntensity: 2.2,
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
          varying vec2 vGlobeUv;
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
          diffuseColor.rgb = mix(diffuseColor.rgb, vLiving.rgb, vAlive);
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
          roughnessFactor = mix(roughnessFactor, mix(0.95, 0.14, vWet), vAlive);
        `)
        .replace("#include <metalnessmap_fragment>", `
          #include <metalnessmap_fragment>
          metalnessFactor = mix(metalnessFactor, mix(0.02, 0.12, vWet), vAlive);
        `);
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", `
          #include <common>
          varying vec2 vGlobeUv;
        `)
        .replace("#include <uv_vertex>", `
          #include <uv_vertex>
          vGlobeUv = uv;
        `);
    };

    this.earth = new THREE.Mesh(
      new THREE.SphereGeometry(1, 160, 160),
      this.material,
    );
    this.scene.add(this.earth);
    // Kept as an alias: the flight and the drag were written against
    // `metal`, and one sphere now serves both roles.
    this.metal = this.earth;

    // A thin shell of atmosphere. Rendered from the inside and added rather
    // than blended, so it reads as light scattering at the limb instead of a
    // coloured ring drawn on top.
    this.halo = new THREE.Mesh(
      new THREE.SphereGeometry(1.05, 64, 64),
      new THREE.MeshBasicMaterial({
        color: 0x3d84bd,
        transparent: true,
        opacity: 0,
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
    Dead metal to living planet, on one number.

    Every visual change rides on `progress`, which is why the look can be tuned
    by editing this method rather than by chasing four animations that each
    have to agree with the others.

    The fades are not linear. Nature arrives on a curve that holds back early
    and then commits, so the world stays metal while the evidence is still
    thin and turns over decisively once it is not.
  */
  setProgress(t) {
    this.progress = Math.min(1, Math.max(0, t));
    const k = this.progress;
    const eased = k * k * (3 - 2 * k);          // smoothstep

    this.uniforms.uGrowth.value = eased;
    this.halo.material.opacity = 0.42 * eased;
    // The reflections fade as the surface stops being metal. Without this the
    // sea keeps a chrome sheen and the whole planet reads as painted metal
    // rather than as water.
    this.material.envMapIntensity = 2.2 * (1 - 0.72 * eased);
    this.renderer.toneMappingExposure = 1.45 - 0.12 * eased;
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
