/*
  Deterministic playback, for rendering to frames.

  The page normally runs on requestAnimationFrame, which is the right thing for
  a visitor and the wrong thing for a recording. A real-time loop drops frames
  when a shader compiles or a texture uploads, runs at whatever rate the
  machine manages, and produces a different result every time.

  This exposes a `window.vestigoRender` that steps the whole scene by an exact
  amount and draws once. Nothing consults the clock. A frame that takes four
  seconds to produce is still one sixtieth of a second of footage, so the
  output is smooth by construction rather than by hoping: clunkiness is a
  real-time problem, and this stops being real-time.

  Loaded only when the URL carries ?render, so it costs a visitor nothing.
*/
/*
  How much brighter the footage is than the page, and it is a multiplier now.

  On screen the globe sits on a dark page and is read against it. In a video it
  fills the frame with nothing to compare against, and an exposure that looks
  moody in a browser window looks underlit at full bleed.

  This used to be an absolute 2.0, set here and again after every apply(). That
  was written against a day-lit planet. Against the night side it is nearly a
  stop over: the ocean lifts to grey and every city rolls off into
  white, so the one thing the shot is about disappears. A multiplier keeps
  whatever curve apply() decided and only lifts it.
*/
const RENDER_LIFT = 1.12;

export function installRenderMode({ globe, flight, machine, loadTrace, play }) {
  /*
    The intro's exposure, held between calls.

    render-intro.mjs calls set() and then step() on every frame, and step()
    recomputes the exposure from scratch: apply() writes the growth curve and
    the lift goes on top. So whatever set() had just done was undone a line
    later, and the shot stayed at its night exposure however the number was
    changed.

    That is the second time in this session an edit moved a measured value by
    exactly zero, and the second time it meant the code was being overwritten
    rather than being wrong. Both paths read the same variable now.
  */
  let introExposure = 1;

  const api = {
    ready: false,

    /* Put the scene in a known state. The same call gives the same picture
       every time, which is what makes a rerun produce identical footage. */
    async setup({ trace, width = 1920, height = 1080 } = {}) {
      globe.renderer.setPixelRatio(1);           // exact pixels, not the display's
      globe.renderer.setSize(width, height, false);
      globe.camera.aspect = width / height;
      globe.camera.updateProjectionMatrix();

      globe.spinning = false;
      globe.earth.rotation.set(0, -0.9, 0);
      globe.camera.position.set(0, 0.18, globe.baseDistance);
      globe.targetProgress = 0;
      globe.progress = 0;
      globe.apply(0);
      globe.renderer.toneMappingExposure *= RENDER_LIFT;

      if (trace) await loadTrace(trace);
      api.ready = true;
      return { width, height };
    },

    /* One frame of footage. `dt` is how much time the scene should believe has
       passed, not how much really has. */
    step(dt = 1 / 60) {
      globe.progress += (globe.targetProgress - globe.progress)
        * (1 - Math.pow(0.06, dt));
      globe.apply(globe.progress);
      // apply() sets exposure from the growth, so the lift has to be reapplied
      // after it or every frame falls back to the live page's level — and the
      // intro's lift with it, which is why this reads introExposure rather than
      // assuming set() has had the last word.
      globe.renderer.toneMappingExposure *= RENDER_LIFT * introExposure;
      globe.earth.rotation.y += dt * globe.spin;
      globe.halo.rotation.copy(globe.earth.rotation);
      globe.renderer.render(globe.scene, globe.camera);
    },

    /* Set the state directly, for scripted beats that do not come from a run. */
    set({ progress, rotationY, rotationX, cameraZ, cameraY, sun, exposure = 1 }) {
      if (progress !== undefined) {
        globe.targetProgress = progress;
        globe.progress = progress;
        globe.apply(progress);
      }
      if (rotationY !== undefined) globe.earth.rotation.y = rotationY;
      if (rotationX !== undefined) globe.earth.rotation.x = rotationX;
      if (cameraZ !== undefined) globe.camera.position.z = cameraZ;
      if (cameraY !== undefined) globe.camera.position.y = cameraY;
      // The intro swings the sun round as it dives, so the planet is in
      // daylight by the time it hands over to Google's tiles. See Globe.setSun.
      if (sun) globe.setSun(sun[0], sun[1], sun[2]);
      // apply() has already set the exposure from the growth, which is a night
      // curve. The intro lifts it as the sun comes round.
      introExposure = exposure;
      globe.renderer.toneMappingExposure *= RENDER_LIFT * introExposure;
    },

    /* Whether every texture has arrived. Rendering before they have gives a
       few seconds of grey sphere at the head of the footage, which is the
       classic way an offscreen render comes out wrong. */
    loaded() {
      const maps = [
        globe.material.map, globe.material.roughnessMap,
        globe.material.normalMap, globe.material.displacementMap,
        globe.uniforms.uNatural.value, globe.uniforms.uGrowthMap.value,
        globe.uniforms.uLand.value, globe.uniforms.uLights.value,
        globe.uniforms.uGlow.value,
      ];
      return maps.every((t) => t && t.image && t.image.width > 0);
    },
  };

  window.vestigoRender = api;
  return api;
}
