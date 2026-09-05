/*
  The opening: an "activate" panel, then whatever cinematic is available.

  Written so the assets are optional. If the Manhattan tiles have no key and
  the interior clip is not on disk, this resolves immediately and the page
  starts on the globe. That is a deliberate default rather than a failure mode:
  the site has to work for somebody opening it thirty seconds before an
  interview, and a cinematic that will not load must never be the reason it
  does not.

  See README.md in this directory for what each half needs.
*/
// The stitched intro: the rendered Earth beat plus whatever generated clips
// exist, joined by scripts/stitch-intro.mjs. One file, so the page has one
// thing to load and one thing to skip.
const VIDEO = "/opening/intro.mp4";

export class Opening {
  constructor({ onBegin, onFinish }) {
    this.onBegin = onBegin;
    this.onFinish = onFinish;
    this.root = null;
  }

  /* Is there a cinematic to play? A HEAD request rather than loading the file,
     so a missing clip costs a few bytes instead of a download. */
  static async available() {
    try {
      const res = await fetch(VIDEO, { method: "HEAD" });
      return res.ok;
    } catch {
      return false;
    }
  }

  mount(parent = document.body) {
    const el = document.createElement("div");
    el.className = "opening";
    /*
      No headline and no explanatory paragraph.

      The first version led with "Where was this taken?" over "Most systems
      will tell you. This one tells you how much to believe the answer." Both
      are the house style of every AI product page of the last two years, and
      a sentence explaining what the page does is an admission that the page
      does not show it.

      What is here instead is a reading, in the same format the system emits:
      a coordinate, a level, a confidence. It states the thesis by being an
      example of it rather than by describing one. Somebody who does not read
      it still sees the shape of the answer this thing gives.

      The control says ENTER, not "Begin". Begin is a word from an onboarding
      flow.
    */
    el.innerHTML = `
      <div class="opening-inner">
        <div class="opening-reading">
          <span class="opening-coord">31.5885, 74.3106</span>
          <span class="opening-meta">POINT &middot; 0.98</span>
        </div>
        <div class="opening-reading opening-reading-dim">
          <span class="opening-coord">-33.45, -70.67</span>
          <span class="opening-meta">COUNTRY &middot; 0.61</span>
        </div>
        <div class="opening-reading opening-reading-dim">
          <span class="opening-coord">&mdash;&mdash;.&mdash;&mdash;, &mdash;&mdash;.&mdash;&mdash;</span>
          <span class="opening-meta">NO CLAIM</span>
        </div>
        <button class="opening-go" type="button">ENTER</button>
        <button class="opening-skip" type="button">skip</button>
      </div>`;
    parent.append(el);
    this.root = el;

    el.querySelector(".opening-go").addEventListener("click", () => this.begin());
    el.querySelector(".opening-skip").addEventListener("click", () => this.finish());
    return this;
  }

  async begin() {
    this.onBegin?.();
    this.root?.classList.add("opening-playing");

    if (!(await Opening.available())) {
      this.finish();
      return;
    }

    /*
      The handoff.

      The clip ends on a laptop with a dark screen. The interface fades up
      inside the bezel and the bezel then scales up and off the edges, so
      nothing ever has to line up: the UI appears inside a frame this code
      controls. A straight cut would need a pixel-perfect match against a
      generated frame, which is hard to produce and obvious when it is close
      but wrong.
    */
    const video = document.createElement("video");
    video.className = "opening-video";
    video.src = VIDEO;
    video.muted = true;              // autoplay is blocked otherwise
    video.playsInline = true;
    video.preload = "auto";
    this.root.append(video);

    // A skip that is visible from the first frame. Somebody who has seen this
    // once and came back to show a colleague should not have to sit through it.
    this.root.querySelector(".opening-skip").classList.add("over-video");

    video.addEventListener("ended", () => this.finish());
    // A clip that fails mid-play should not strand the visitor on a black
    // rectangle, so any error lands on the same exit as a normal end.
    video.addEventListener("error", () => this.finish());

    try {
      await video.play();
    } catch {
      this.finish();
    }
  }

  finish() {
    if (this.finished) return;       // ended and skipped can both arrive
    this.finished = true;
    this.root?.classList.add("opening-done");
    // Long enough for the fade in CSS, short enough not to feel like a wait.
    setTimeout(() => this.root?.remove(), 900);
    this.onFinish?.();
  }
}
