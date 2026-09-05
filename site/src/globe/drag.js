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

export class Drag {
  constructor(globe, element) {
    this.globe = globe;
    this.element = element;
    this.dragging = false;
    this.last = { x: 0, y: 0 };
    this.velocity = { x: 0, y: 0 };
    this.pointer = null;

    // Pointer events rather than mouse events: one set of handlers covers a
    // mouse, a trackpad and a finger, and setPointerCapture keeps the drag
    // alive when the pointer leaves the element mid-gesture.
    element.addEventListener("pointerdown", this.down);
    element.addEventListener("pointermove", this.move);
    element.addEventListener("pointerup", this.up);
    element.addEventListener("pointercancel", this.up);
  }

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
    if (event.target.closest?.("button, input, a, .receipt")) return;
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
    if (this.dragging || flying) return;
    const { x, y } = this.velocity;
    if (Math.abs(x) < 1e-4 && Math.abs(y) < 1e-4) return;
    this.apply(x, y);
    this.velocity.x *= DAMPING;
    this.velocity.y *= DAMPING;
  }

  dispose() {
    const e = this.element;
    e.removeEventListener("pointerdown", this.down);
    e.removeEventListener("pointermove", this.move);
    e.removeEventListener("pointerup", this.up);
    e.removeEventListener("pointercancel", this.up);
  }
}
