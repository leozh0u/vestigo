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

  `setLatLonToYUp` re-orients the whole tileset so that a chosen point sits at
  the origin with the sky pointing up the Y axis, which turns the problem back
  into the one everybody knows: a camera at some height above a place, looking
  at something.

  ## Cost

  Billed per session, and a session starts when the root tileset is requested.
  So the tiles are not loaded until the descent actually begins: a visitor who
  never presses anything costs nothing. That is also why the key is read at
  call time rather than at import.
*/
import * as THREE from "three";
import { TilesRenderer } from "3d-tiles-renderer";
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
    // ECEF into something a camera can be aimed in. See the note above.
    tiles.group.rotation.x = -Math.PI / 2;
    this.scene.add(tiles.group);

    // Daylight, because the tiles are photographs taken in daylight and lighting
    // them any other way fights the pixels rather than adding to them.
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    const sun = new THREE.DirectionalLight(0xfff4e0, 1.2);
    sun.position.set(1, 2, 1);
    this.scene.add(sun);

    this.tiles = tiles;
    await tiles.setLatLonToYUp(
      MANHATTAN.lat * THREE.MathUtils.DEG2RAD,
      MANHATTAN.lon * THREE.MathUtils.DEG2RAD,
    );
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
