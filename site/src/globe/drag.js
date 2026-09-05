/*
  Spinning the globe by hand.

  Deliberately not OrbitControls, three.js's stock camera controller. That
  moves the camera around the scene, and everything else here is built on the
  opposite arrangement: the camera stays put and the planet turns, which is
  what keeps the lighting where it was designed and makes the poles ordinary.
  Dropping in a controller that fights that would undo the flight in camera.js.

  So this rotates the object, in the two axes that mean something on a sphere.

  ## Momentum

  A drag that stops dead the instant the pointer lifts feels like a control.
  One that carries and slows feels like an object with weight, and it costs
  four lines: remember the last movement, keep applying it, multiply it down
  each frame. The 0.94 below is the whole physics.
*/
const DAMPING = 0.94;
const SENSITIVITY = 0.005;
const MAX_TILT = 1.05;          // stop short of looking straight down a pole

/*
  How close and how far the wheel is allowed to take the camera.

  As multiples of the idle distance rather than as absolute units, because the
  idle distance is itself a multiple of the aspect fit — a phone held upright
  sits the camera much further back and a fixed pair of numbers would let it
  zoom to somewhere the planet does not fill the frame at all.

  The near end stops where camera.js stops: past about half the idle distance
  the horizon leaves the frame and the surface becomes a flat wash, and there is
  no more detail in a 5400-pixel texture to reward going closer.
*/
const NEAREST = 0.52;
const FURTHEST = 1.9;
// Per notch. A trackpad sends many small deltas and a mouse wheel sends few
// large ones, so the delta is what varies and this is only the scale.
const ZOOM_RATE = 0.0016;
const ZOOM_DAMPING = 0.86;

export class Drag {
  constructor(globe, element) {
    this.globe = globe;
    this.element = element;
    this.dragging = false;
    this.last = { x: 0, y: 0 };
    this.velocity = { x: 0, y: 0 };
    // Carried and damped like the spin, so a flick of the wheel coasts to a
    // stop rather than stepping.
    this.zoomVelocity = 0;
    this.pointer = null;

    // Pointer events rather than mouse events: one set of handlers covers a
    // mouse, a trackpad and a finger, and setPointerCapture keeps the drag
    // alive when the pointer leaves the element mid-gesture.
    element.addEventListener("pointerdown", this.down);
    element.addEventListener("pointermove", this.move);
    element.addEventListener("pointerup", this.up);
    element.addEventListener("pointercancel", this.up);

    /*
      Wheel, trackpad and pinch, all through one handler.

      A two-finger swipe on a trackpad arrives as a wheel event, and so does a
      pinch on a trackpad or a touchscreen: the browser reports it as a wheel
      with ctrlKey set. So one listener covers the mouse, the two-finger swipe
      and the pinch, and the only difference is that a pinch needs a larger
      multiplier because its deltas are small.

      Not passive, because this has to preventDefault. Without that, a
      two-finger swipe over the page scrolls it — and this page cannot scroll,
      so on a Mac it rubber-bands the whole window instead, which looks like the
      site coming loose.
    */
    element.addEventListener("wheel", this.wheel, { passive: false });
  }

  wheel = (event) => {
    // Same rule as the drag: a gesture that starts on a control belongs to it.
    if (event.target.closest?.("button, input, a, .receipt, .examples, .machinery")) return;
    event.preventDefault();
    // A pinch reports as a wheel with ctrlKey. Its deltas are much smaller than
    // a scroll's, so it needs more gain to travel the same distance.
    const gain = event.ctrlKey ? 3.4 : 1;
    this.zoomVelocity += event.deltaY * ZOOM_RATE * gain;
  };

  down = (event) => {
    if (event.button !== 0) return;
    /*
      Ignore anything that starts on a control.

      This listens on the whole page, because the canvas has pointer-events
      turned off so the UI above it stays clickable. The cost is that a press
      on a button reaches here first, and setPointerCapture below then takes
      the pointer for the drag, so the button never gets its click. Every
      example silently stopped working and the page just sat there.

      `closest` walks up from whatever was pressed, so a press anywhere inside
      a control is a press on that control.
    */
    if (event.target.closest?.("button, input, a, .receipt, .examples")) return;
    this.dragging = true;
    this.pointer = event.pointerId;
    this.last = { x: event.clientX, y: event.clientY };
    this.velocity = { x: 0, y: 0 };
    this.element.setPointerCapture(event.pointerId);
    this.element.style.cursor = "grabbing";
    // A hand-turned globe should stay where it is put, so the idle rotation
    // stops for good on first touch rather than resuming and undoing the work.
    this.globe.spinning = false;
  };

  move = (event) => {
    if (!this.dragging || event.pointerId !== this.pointer) return;
    const dx = event.clientX - this.last.x;
    const dy = event.clientY - this.last.y;
    this.last = { x: event.clientX, y: event.clientY };
    this.velocity = { x: dx * SENSITIVITY, y: dy * SENSITIVITY };
    this.apply(this.velocity.x, this.velocity.y);
  };

  up = (event) => {
    if (event.pointerId !== this.pointer) return;
    this.dragging = false;
    this.pointer = null;
    this.element.style.cursor = "grab";
  };

  apply(dx, dy) {
    const r = this.globe.metal.rotation;
    r.y += dx;
    // Clamped, because past vertical the sphere is being viewed down its own
    // axis and the drag inverts, which feels broken even though it is correct.
    r.x = Math.max(-MAX_TILT, Math.min(MAX_TILT, r.x + dy));
  }

  /* Called from the one frame loop in main.js. Skipped while a flight is
     running, so a directed move and a coasting drag cannot fight. */
  update(flying) {
    if (flying) {
      // A flight owns the camera. Anything the wheel had built up would fight
      // it, and the fight looks like a stutter.
      this.zoomVelocity = 0;
      return;
    }
    this.zoom();
    if (this.dragging) return;
    const { x, y } = this.velocity;
    if (Math.abs(x) < 1e-4 && Math.abs(y) < 1e-4) return;
    this.apply(x, y);
    this.velocity.x *= DAMPING;
    this.velocity.y *= DAMPING;
  }

  /*
    One frame of zoom.

    Multiplicative rather than additive: a fixed number of units per notch moves
    a long way when the camera is close and barely at all when it is far, so the
    control changes meaning depending on where you already are. Scaling the
    distance instead makes one notch cover the same *proportion* everywhere,
    which is what the hand expects.
  */
  zoom() {
    if (Math.abs(this.zoomVelocity) < 1e-4) {
      this.zoomVelocity = 0;
      return;
    }
    const globe = this.globe;
    const idle = globe.idleDistance;
    const next = globe.camera.position.z * (1 + this.zoomVelocity);
    globe.camera.position.z = Math.max(idle * NEAREST, Math.min(idle * FURTHEST, next));
    this.zoomVelocity *= ZOOM_DAMPING;
  }

  dispose() {
    const e = this.element;
    e.removeEventListener("pointerdown", this.down);
    e.removeEventListener("pointermove", this.move);
    e.removeEventListener("pointerup", this.up);
    e.removeEventListener("pointercancel", this.up);
    e.removeEventListener("wheel", this.wheel);
  }
}
