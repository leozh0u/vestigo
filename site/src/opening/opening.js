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
/*
  Where the intro is, asked rather than assumed.

  It used to be a constant, /opening/intro.mp4, and that was a mistake with a
  cost. Replacing the video did not change its URL, so a browser holding the old
  one went on playing the old one: a new cut shipped, the site served it, and
  the person it was made for saw the previous version and reported that nothing
  had changed. Twice, before anyone worked out it was a cache.

  stitch-intro.mjs names the file after a hash of its contents and writes this
  manifest beside it. The manifest is small and may be re-fetched freely; the
  video it points at is immutable and never needs to be.
*/
const MANIFEST = "/opening/intro.json";

export class Opening {
  constructor({ onBegin, onFinish, onHandoff } = {}) {
    this.onBegin = onBegin;
    this.onFinish = onFinish;
    this.onHandoff = onHandoff;
    this.root = null;
  }

  /*
    Is there a cinematic, and where?

    Returns its URL or null. A few hundred bytes of JSON rather than a HEAD
    against a video, and it answers both questions at once: whether there is one
    to play, and which build of it this is.

    no-store on the manifest specifically. It is the one thing here that has to
    be current, and it is small enough that not caching it costs nothing.
  */
  static async available() {
    try {
      const res = await fetch(MANIFEST, { cache: "no-store" });
      if (!res.ok) return null;
      const { src, screen, ui } = await res.json();
      if (typeof src !== "string" || !src) return null;
      // The laptop screen's rectangle in the last frame, and what the globe was
      // doing in the screenshot on it. Older manifests have neither and the
      // page falls back to a plain fade.
      return { src, screen: screen ?? null, ui: ui ?? null };
    } catch {
      return null;
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

    const found = await Opening.available();
    if (!found) {
      this.finish();
      return;
    }
    const { src, screen, ui } = found;
    this.screen = screen;
    this.ui = ui;

    /*
      The handoff.

      The clip ends on a laptop that already has this page on its screen. So the
      last move is not a fade from a video to an interface, it is the screen
      growing until it is the interface: the video is scaled about the centre of
      that rectangle until the rectangle fills the viewport, and by the time it
      does, what is under it is the same page at the same size.

      The rectangle is measured, not typed. render-descent projects the screen's
      four corners through the camera that took the last frame and stitch-intro
      carries the result in the manifest, so re-rendering the shot moves the
      handoff with it.
    */
    const video = document.createElement("video");
    video.className = "opening-video";
    video.src = src;
    video.muted = true;              // autoplay is blocked otherwise
    video.playsInline = true;
    video.preload = "auto";
    this.root.append(video);

    // A skip that is visible from the first frame. Somebody who has seen this
    // once and came back to show a colleague should not have to sit through it.
    this.root.querySelector(".opening-skip").classList.add("over-video");

    video.addEventListener("ended", () => { this.played = true; this.finish(); });
    // A clip that fails mid-play should not strand the visitor on a black
    // rectangle, so any error lands on the same exit as a normal end.
    video.addEventListener("error", () => this.finish());

    /*
      A refused play is not always a refusal.

      A browser blocking autoplay outright is a good reason to give up and show
      the page. A browser pausing "video-only background media to save power" is
      not: it happens when the tab is not on screen, and the visitor who comes
      back to it should find the intro rather than find it already skipped.
      Chrome reports both as an AbortError on the same promise.

      So one retry, when the page is next actually visible, and only then a
      fall-through to the page itself.
    */
    const start = async () => { await video.play(); };
    try {
      await start();
    } catch {
      if (document.visibilityState === "hidden") {
        const again = () => {
          document.removeEventListener("visibilitychange", again);
          start().catch(() => this.finish());
        };
        document.addEventListener("visibilitychange", again);
      } else {
        this.finish();
      }
    }
  }

  finish() {
    if (this.finished) return;       // ended and skipped can both arrive
    this.finished = true;

    /*
      Grow the screen into the page.

      Only when the clip ran to its end — a skip is somebody asking to be
      somewhere else, and should cut, not perform a flourish. And only when the
      manifest carried a rectangle: without one there is nothing to grow and the
      fade underneath is still correct.

      object-fit is cover, so the video is scaled to the larger of the two
      ratios and the overflow is cropped evenly. The rectangle arrives in frame
      coordinates and has to be moved into that cropped space before it means
      anything on screen, or the handoff lands off-centre on every window that
      is not exactly sixteen by nine.
    */
    /*
      Put the page where the picture of it was, before revealing it.

      The clip ends by growing a screenshot of this page until it fills the
      frame, and the page underneath is live — its planet is turning. Two
      images identical in every respect except that one of them is moving do not
      cross-dissolve; they show exactly where the join is, which is what made
      this read as an edit rather than as an arrival.

      So the globe is set to the state it was in when the screenshot was taken,
      and left still until the transition is over. See capture-ui.mjs.
    */
    this.onHandoff?.(this.ui);

    const video = this.root?.querySelector(".opening-video");
    const box = video?.getBoundingClientRect();
    /*
      And only when there is something to measure.

      A tab that has never been on screen lays nothing out: the element comes
      back zero by zero, the scale works out as a division by zero, and the
      browser drops the invalid transform without a word — the class goes on,
      the move does not happen, and nothing anywhere says why. The fade
      underneath is the right answer in that case and is already correct.
    */
    if (video && this.screen && this.played && box.width > 1 && box.height > 1) {
      const vw = video.videoWidth || 16;
      const vh = video.videoHeight || 9;
      const w = box.width;
      const h = box.height;
      const cover = Math.max(w / vw, h / vh);
      const shownW = vw * cover;
      const shownH = vh * cover;
      // Where the screen's centre lands inside the element, in per cent.
      const originX = ((this.screen.x * shownW) - (shownW - w) / 2) / w * 100;
      const originY = ((this.screen.y * shownH) - (shownH - h) / 2) / h * 100;
      /*
        Enough to take the rectangle out past both edges.

        In element pixels, not in fractions: the rectangle is a fraction of the
        *frame*, the frame has been scaled up by cover and cropped, and the two
        are only the same thing on a window that happens to match the video's
        ratio. Its on-screen size is its fraction times the shown size, and the
        scale is whatever makes that reach the element.
      */
      const grow = Math.max(w / (this.screen.w * shownW),
                            h / (this.screen.h * shownH)) * 1.04;
      if (Number.isFinite(grow) && Number.isFinite(originX) && Number.isFinite(originY)) {
        video.style.transformOrigin = `${originX}% ${originY}%`;
        video.style.transform = `scale(${grow.toFixed(3)})`;
        this.root.classList.add("opening-growing");
      }
    }

    this.root?.classList.add("opening-done");
    // Long enough for the fade in CSS, short enough not to feel like a wait.
    // Long enough for whichever transition is running, short enough not to wait.
    setTimeout(() => this.root?.remove(), 1200);
    this.onFinish?.();
  }
}
