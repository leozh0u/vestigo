# The three clips to generate

The Earth beat is rendered from the site's own scene by
`scripts/render-intro.mjs`, so it needs nothing. These three are the parts no
code can produce: photogrammetry stops at rooftops, so there is no dataset with
a Manhattan apartment interior in it.

Generate in **Higgsfield**, **Kling** or **Veo**. Higgsfield has named camera
moves, which is what these shots are made of.

**16:9, 24fps, no text, no people, no music, no camera shake.** Locked,
deliberate moves. Handheld reads as a stock clip.

---

## Clip 1 — descent into Manhattan (6s)

Picks up where the Earth beat leaves off: high over the US eastern seaboard,
already moving down.

> Continuous aerial descent from very high altitude toward Manhattan at
> twilight. Begin above thin cloud with the coastline and the Hudson visible
> far below, push down through the cloud layer, and settle into the avenues
> between skyscrapers as the city lights come on. Camera moves forward and
> down in one unbroken motion, no cuts, no orbiting. Photorealistic aerial
> cinematography, long lens, atmospheric haze, blue hour.

**Ends on:** street level between buildings, moving forward.

---

## Clip 2 — the walk-up and the window (5s)

> Slow upward tilt along the face of a pre-war New York walk-up apartment
> building at dusk. Red brick, black iron fire escape zigzagging up the
> facade, air conditioning units in the windows. The camera rises past two
> floors and settles on one lit window with the sash raised, a warm interior
> glow behind it. Ends with the window occupying most of the frame.
> Photorealistic, shallow depth of field, no people.

**Ends on:** the window filling roughly 70% of the frame. That is where the
next cut hides.

---

## Clip 3 — through the window to the desk (6s)

The one that matters. Generate this **last**, once the real UI exists, so the
screen is framed the way the handoff needs.

> Slow dolly through an open window into a dim New York apartment at night.
> The camera passes the sill and glides low across the room, past a plant and
> a bookshelf in silhouette, and settles facing a desk with a laptop open on
> it. The laptop screen is dark and slightly reflective and grows to fill the
> centre of the frame as the camera closes. Warm lamp light from the left,
> cool street light through the window behind. Photorealistic interior
> cinematography, shallow depth of field, dust in the air, no people, no text
> on the screen.

**Three requirements, and the shot does not work without them:**

1. **The screen must be dark and empty.** Anything on it fights the UI that
   fades up over it.
2. **It must end centred and roughly level**, filling 55 to 70% of the frame
   width. The interface appears inside that rectangle.
3. **Hold the final framing for half a second.** That still frame is what the
   UI arrives over, and a camera still drifting when the handoff starts makes
   the interface look like it is sliding off a desk.

---

## Stitching

Save the three as `clip1.mp4`, `clip2.mp4`, `clip3.mp4` in `site/public/opening/`,
then:

    cd site && node scripts/stitch-intro.mjs

That joins them to the rendered Earth beat with short cross-dissolves at the
seams and writes `public/opening/intro.mp4`, which is what the page plays.

The dissolves are the point. Each seam sits where one thing fills the frame —
cloud, then building face, then window — so there is nothing on screen for the
eye to compare across the join.
