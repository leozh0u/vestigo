/*
  What the offscreen renderers bundle.

  esbuild needs a single entry point and the renderers need three as well as the
  scene, so this hands both out on one object. It exists only for the bundle
  step; nothing the site serves imports it.
*/
import * as THREE from "three";
import { Manhattan, MANHATTAN } from "../src/globe/manhattan.js";
import { buildFacade, WINDOW, PROUD } from "../src/globe/room.js";

export { THREE, Manhattan, MANHATTAN, buildFacade, WINDOW, PROUD };
