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

    // Daylight, because the tiles are photographs taken in daylight and lighting
    // them any other way fights the pixels rather than adding to them.
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const sun = new THREE.DirectionalLight(0xfff4e0, 1.2);
    sun.position.set(1, 2, 1);
    this.scene.add(sun);

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
  place(t) {
    const e = t < 0.5 ? 4 * t ** 3 : 1 - Math.pow(-2 * t + 2, 3) / 2;
    const height = 4200 + (180 - 4200) * e;
    const back = 3000 + (240 - 3000) * e;
    this.camera.position.set(0, height, back);
    // The aim rises as the camera falls, so the shot tilts from looking down
    // at a city to looking up at a building without a separate move.
    this.camera.lookAt(0, 0 + 120 * e, 0);
    this.camera.updateMatrixWorld();
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

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.tiles?.dispose();
  }
}
