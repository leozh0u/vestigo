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

/*
  How long the page takes to become the clip's first frame, and how long the
  clip then takes to replace it.

  The settle matches the strip's slide in style.css. They are the same movement
  seen from two sides — the photographs leaving and the planet taking the room
  back — and a difference between them would show as the globe arriving before
  or after the space it is arriving into.

  The fade is short because by the time it runs there is nothing to hide. It was
  780ms when it was covering a mismatch. Kept above zero rather than removed: a
  video element and a WebGL canvas do not agree to the last level on gamma, and
  a few frames of blend is enough for that never to be visible.
*/
const SETTLE = 820;
const FADE = 380;

const wait = (ms) => new Promise((done) => setTimeout(done, ms));

export class Opening {
  constructor({ onBegin, onFinish, onHandoff, onEnter } = {}) {
    this.onBegin = onBegin;
    this.onFinish = onFinish;
    this.onHandoff = onHandoff;
    this.onEnter = onEnter;
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
      const { src, open, screen, ui } = await res.json();
      if (typeof src !== "string" || !src) return null;
      /*
        The pose the clip opens on, the laptop screen's rectangle in its last
        frame, and what the globe was doing in the screenshot on that screen.
        Both ends of the clip, measured by the renders rather than typed here.
        An older manifest has none of them and the page falls back to a fade at
        each end, which is what this used to do everywhere.
      */
      return { src, open: open ?? null, screen: screen ?? null, ui: ui ?? null };
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
    /*
      Arrive at the clip's first frame, then start the clip.

      Pressing ENTER used to add a class, fade a video up and press play, all in
      the same frame. Three things then happened at once: the page cleared, the
      video's sphere started turning, and the fade ran across the middle of
      both. You could see two spheres at different rotations, different sizes
      and different brightnesses, one of them moving. That reads worse than a
      hard cut, because a cut at least only ever shows one wrong thing.

      So it is in order now. The page settles onto the pose the clip opens on —
      measured by the render, carried in the manifest, applied by main.js. The
      video is loaded in parallel and held on its first frame. Only when the
      page has arrived and that frame is decoded does the fade run, and only
      when the fade is over does anything move.

      By then the two images are the same image, so the fade has nothing to do
      and the motion starts from a still frame that was already on screen.
    */
    const found = await Opening.available();
    if (!found) {
      this.finish();
      return;
    }
    const { src, open, screen, ui } = found;
    this.screen = screen;
    this.ui = ui;

    document.documentElement.classList.add("entering");
    this.onEnter?.(open, SETTLE);
    this.root?.classList.add("opening-playing");

    /*
      The handoff at the far end.

      The clip ends on a laptop that already has this page on its screen, so the
      last move is not a fade from a video to an interface, it is the screen
      growing until it is the interface. The rectangle is measured, not typed:
      render-descent projects the screen's four corners through the camera that
      took the last frame and stitch-intro carries the result in the manifest,
      so re-rendering the shot moves the handoff with it.
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
      Both halves have to be ready, and they are ready at different times.

      The settle is a fixed length and the decode is not: on a warm cache the
      first frame is there before the click finishes, and on a cold one over a
      slow connection it is seconds away. Fading up a video element that has not
      decoded anything shows black, which is the one thing the whole arrangement
      exists to avoid.

      readyState 2 is HAVE_CURRENT_DATA — there is a frame for the current
      position. That is exactly the guarantee needed and no more; waiting for
      the whole file would hold a still page for no reason.
    */
    const decoded = video.readyState >= 2
      ? Promise.resolve()
      : new Promise((done) => {
          video.addEventListener("loadeddata", done, { once: true });
          video.addEventListener("error", done, { once: true });
        });
    await Promise.all([decoded, wait(SETTLE)]);
    if (this.finished) return;       // skipped while we were waiting

    video.classList.add("opening-video-in");
    await wait(FADE);
    if (this.finished) return;

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
    document.documentElement.classList.remove("entering");

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
