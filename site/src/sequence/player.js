/*
  Playing a trace.

  A trace is what the Python wrote: the ordered list of states a real board
  passed through. Every frame of the resolving state comes from here, which is
  why the animation is a recording rather than a dramatisation.

  ## Driven by frames, not timers

  The first version used setTimeout. It worked on screen and stalled anywhere
  the tab was not in front, because browsers throttle timers to roughly one a
  second in a background tab. An eleven-second sequence became half a minute,
  the run never reached its end, and the camera never flew. Nothing errored;
  it just quietly stopped being an animation.

  Running off the same requestAnimationFrame loop as everything else fixes it
  and is what the rest of this codebase already claimed to do. A background tab
  now pauses cleanly and resumes where it left off, which is the behaviour a
  viewer expects anyway.

  ## Timing

  Steps are not evenly spaced. A step that changes the answer holds longer than
  one that adds a line of evidence, because the eye needs longer on the moment
  that matters. HOLD is the only place that is decided.
*/
const HOLD = {
  evidence: 420,
  candidate: 260,
  constraint: 900,     // the region visibly shrinks; give it room
  claim: 700,
  refutation: 1200,    // the answer falls back a level. The point of the page.
  default: 400,
};

export class Player {
  constructor(trace, { onStep, onProgress, onDone }) {
    this.steps = trace?.steps ?? [];
    this.final = trace?.final ?? null;
    this.onStep = onStep;
    this.onProgress = onProgress;
    this.onDone = onDone;

    this.index = 0;
    this.elapsed = 0;
    this.done = false;
    this.cancelled = false;
    this.started = false;
  }

  /*
    One frame. `dt` is seconds since the last, already capped by the caller so
    a tab returning from the background does not skip half the sequence in a
    single step.
  */
  update(dt) {
    if (this.cancelled || this.done) return;

    if (!this.started) {
      this.started = true;
      this.show(0);
    }

    this.elapsed += dt * 1000;
    const step = this.steps[this.index];
    const hold = step ? (HOLD[step.kind] ?? HOLD.default) : 0;

    while (!this.done && this.elapsed >= hold) {
      this.elapsed -= hold;
      this.index += 1;
      if (this.index >= this.steps.length) {
        this.done = true;
        this.onDone?.(this.final);
        return;
      }
      this.show(this.index);
      // Recompute, since the next step may hold for a different length.
      const next = this.steps[this.index];
      if ((HOLD[next.kind] ?? HOLD.default) > this.elapsed) break;
    }
  }

  show(i) {
    const step = this.steps[i];
    if (!step) return;
    this.onStep?.(step, i);
    // Progress advances with the run rather than on a clock, so a short trace
    // brings the world alive as fully as a long one.
    this.onProgress?.((i + 1) / this.steps.length);
  }

  cancel() { this.cancelled = true; }
}
