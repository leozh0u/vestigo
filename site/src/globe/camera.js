/*
  The flight.

  Two things happen at once, and the whole feel depends on them being out of
  phase with each other:

    the globe turns   so the target rotates around to face the viewer
    the camera dollies out, then in

  Out first, then in, is the shape a GTA character switch makes: up and away,
  across, then down into the new place. A camera that simply pushed in while
  the globe turned would let the target slide across the frame, and the move
  would read as a pan. Pulling back first puts the rotation at a distance where
  it looks like the planet turning rather than the camera chasing.

  ## Turning the globe instead of orbiting the camera

  The obvious implementation moves the camera around the sphere to sit above
  the target. That needs the up vector handled at the poles, where every
  orbital scheme goes wrong, and it puts the lighting somewhere different for
  every answer.

  Rotating the globe so the target faces a fixed camera avoids all of it: the
  lighting stays where it was designed, the poles are ordinary, and the maths
  is two angles.

  ## Stopping distance is the argument

  How close it gets is set by the level of the answer, not by an answer having
  been found. A point claim lands on the street. A country claim stops in orbit
  and stays there. The camera refusing to descend is this project's thesis as a
  camera move, which is why this file has a table in it rather than a single
  "zoom in" constant.
*/
/*
  Distance from the centre of a sphere of radius 1, so 1.0 is the surface.

  These were originally set much tighter, and the tightest flew the camera to
  within a fifth of a radius of the ground. The globe then filled the whole
  frame as a flat green wash: the texture is 4096 pixels around the equator, so
  there is nothing there to look at up close. The limit is not the camera, it
  is that this planet has no detail below roughly a hundred kilometres.

  A real descent to a street needs real data underneath it, which means
  photogrammetry tiles rather than a texture. Until then these stop at the
  closest distance where the sphere still reads as a planet: past about 1.9 the
  horizon leaves the frame, the surface becomes a flat wash, and the page loses
  the one thing it had. The difference between levels is carried by how much of
  the planet stays in view, which is a smaller range than it sounds and still
  reads clearly.
*/
const ALTITUDE = {
  point: 1.98,
  district: 2.08,
  city: 2.22,
  region: 2.5,
  country: 2.8,
  continent: 3.2,
};
const IDLE_ALTITUDE = 3.55;
const APEX = 4.6;             // how far back it pulls before coming in
const APEX_AT = 0.33;         // most of the move is the descent

// Long enough to read as deliberate, short enough that nobody leaves.
const DURATION = 3800;
const RETURN = 1400;

const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

export class Flight {
  constructor(globe) {
    this.globe = globe;
    this.active = null;
  }

  /*
    Where the globe must be rotated so that (lat, lon) faces the camera.

    Longitude turns it about the vertical axis; latitude tips it. The tilt is
    damped and capped, because taking a polar answer literally puts the camera
    over the top of the sphere looking down a pole, which reads as a diagram
    rather than a place.
  */
  static orientation(lat, lon) {
    const y = -(lon * Math.PI) / 180 - Math.PI / 2;
    const x = Math.max(-0.62, Math.min(0.62, ((lat * Math.PI) / 180) * 0.7));
    return { x, y };
  }

  /* Rotations are angles: 350 degrees and -10 degrees are the same place.
     Without this the globe takes the long way round on most flights. */
  static shortest(from, to) {
    const TAU = Math.PI * 2;
    let delta = (to - from) % TAU;
    if (delta > Math.PI) delta -= TAU;
    if (delta < -Math.PI) delta += TAU;
    return from + delta;
  }

  to(lat, lon, level, { onDone } = {}) {
    this.cancel();
    const globe = this.globe;
    const target = Flight.orientation(lat, lon);
    const start = {
      x: globe.metal.rotation.x,
      y: globe.metal.rotation.y,
      z: globe.camera.position.z,
    };
    const end = {
      x: target.x,
      y: Flight.shortest(globe.metal.rotation.y, target.y),
      z: ALTITUDE[level] ?? IDLE_ALTITUDE,
    };

    globe.spinning = false;      // an idle rotation would fight this one
    const began = performance.now();

    this.active = (now) => {
      const t = Math.min(1, (now - began) / DURATION);

      // The turn leads and settles early, so the planet has arrived before the
      // camera finishes coming down. Landing on a still target is what makes
      // the end read as a stop rather than a fade.
      const turn = easeOut(Math.min(1, t / 0.75));
      globe.metal.rotation.y = start.y + (end.y - start.y) * turn;
      globe.metal.rotation.x = start.x + (end.x - start.x) * turn;

      globe.camera.position.z = t < APEX_AT
        ? start.z + (APEX - start.z) * easeInOut(t / APEX_AT)
        : APEX + (end.z - APEX) * easeInOut((t - APEX_AT) / (1 - APEX_AT));

      if (t >= 1) {
        this.active = null;
        globe.spinning = true;
        globe.spin = 0.010;        // barely turning, so the answer stays put
        onDone?.();
      }
    };
  }

  home({ onDone } = {}) {
    this.cancel();
    const globe = this.globe;
    const start = { x: globe.metal.rotation.x, z: globe.camera.position.z };
    const began = performance.now();
    this.active = (now) => {
      const t = Math.min(1, (now - began) / RETURN);
      const e = easeInOut(t);
      globe.metal.rotation.x = start.x * (1 - e);
      globe.camera.position.z = start.z + (IDLE_ALTITUDE - start.z) * e;
      if (t >= 1) {
        this.active = null;
        globe.spinning = true;
        globe.spin = 0.045;
        onDone?.();
      }
    };
  }

  cancel() { this.active = null; }

  /* Driven from the single frame loop in main.js, so nothing here runs on its
     own timer and drifts out of step with the render. */
  update(now) { this.active?.(now); }
}
