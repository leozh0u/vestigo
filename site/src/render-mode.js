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
export function installRenderMode({ globe, flight, machine, loadTrace, play }) {
  const api = {
    ready: false,

    /* Put the scene in a known state. The same call gives the same picture
       every time, which is what makes a rerun produce identical footage. */
    async setup({ trace, width = 1920, height = 1080 } = {}) {
      globe.renderer.setPixelRatio(1);           // exact pixels, not the display's
      /*
        Brighter than the live page.

        On screen the globe sits on a dark page and is read against it. In a
        video it fills the frame with nothing to compare against, and the same
        exposure that looks moody in a browser window looks underlit at full
        bleed. The first probe came out almost black.
      */
      globe.renderer.toneMappingExposure = 2.0;
      globe.renderer.setSize(width, height, false);
      globe.camera.aspect = width / height;
      globe.camera.updateProjectionMatrix();

      globe.spinning = false;
      globe.earth.rotation.set(0, -0.9, 0);
      globe.camera.position.set(0, 0.18, 3.55);
      globe.targetProgress = 0;
      globe.progress = 0;
      globe.apply(0);

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
      // apply() sets exposure from the growth, so the render's own brightness
      // has to be restored after it or every frame goes back to the live
      // page's level.
      globe.renderer.toneMappingExposure = 2.0 - 0.25 * globe.progress;
      globe.earth.rotation.y += dt * globe.spin;
      globe.halo.rotation.copy(globe.earth.rotation);
      globe.renderer.render(globe.scene, globe.camera);
    },

    /* Set the state directly, for scripted beats that do not come from a run. */
    set({ progress, rotationY, rotationX, cameraZ, cameraY }) {
      if (progress !== undefined) {
        globe.targetProgress = progress;
        globe.progress = progress;
        globe.apply(progress);
      }
      if (rotationY !== undefined) globe.earth.rotation.y = rotationY;
      if (rotationX !== undefined) globe.earth.rotation.x = rotationX;
      if (cameraZ !== undefined) globe.camera.position.z = cameraZ;
      if (cameraY !== undefined) globe.camera.position.y = cameraY;
      globe.renderer.toneMappingExposure = 2.0 - 0.25 * globe.progress;
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
      ];
      return maps.every((t) => t && t.image && t.image.width > 0);
    },
  };

  window.vestigoRender = api;
  return api;
}
