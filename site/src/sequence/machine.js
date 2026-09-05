/*
  The state machine.

  A page like this could be written with flags: isLoading, hasResult,
  isAnimating. The problem is that flags allow combinations that make no
  sense. isLoading and hasResult both true means a spinner over a finished
  answer, and nothing stops it happening except remembering to.

  A machine says: there is exactly one state at a time, and these are the only
  moves between them. The impossible combinations cannot be written down, so
  they cannot be reached.

    idle       nothing chosen yet
    submitted  an example picked, about to play
    resolving  the trace is playing, evidence arriving
    arrived    the answer is stated and the camera has stopped

  Moves are declared in one table below. Anything not in the table throws
  rather than being ignored, because a transition that silently does nothing
  is a bug you find later, in the browser, with no message.
*/
const MOVES = {
  idle: ["submitted"],
  submitted: ["resolving", "idle"],
  resolving: ["arrived", "idle"],
  arrived: ["idle"],
};

export class Machine {
  constructor(initial = "idle") {
    this.state = initial;
    this.listeners = new Set();
  }

  can(next) {
    return (MOVES[this.state] ?? []).includes(next);
  }

  go(next, detail = {}) {
    if (!this.can(next)) {
      throw new Error(`cannot go from ${this.state} to ${next}`);
    }
    const from = this.state;
    this.state = next;
    for (const fn of this.listeners) fn({ from, to: next, detail });
    return this;
  }

  onChange(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}
