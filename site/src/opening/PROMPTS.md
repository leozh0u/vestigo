# The intro, and what makes each part of it

Four beats. Two are rendered from this repository and need nothing; one has to
be generated; the last is CSS.

Nothing here is a preference. The division came out of measuring what each tool
can actually do, and the measurements are in `PROGRESS.md`.

---

## Beat 1 — the Earth (6s) · rendered, done

`node scripts/render-intro.mjs --seconds 6 --fps 30`

Machined metal turning into a night Earth: continents rise, basins sink, water
fills them, and the cities come on. Ends closing on the eastern seaboard of the
United States, which is where the descent picks up.

Comes out of the site's own scene, driven frame by frame rather than by the
clock, so it is smooth by construction rather than by hoping.

---

## Beat 2 — the descent (7s) · rendered, needs a look

`node scripts/render-descent.mjs --seconds 7 --fps 30`

Google's Photorealistic 3D Tiles: the real East Village, real captured
geometry, graded to the twenty minutes after sunset because Google publishes no
other time of day. From 3,400 m down to about 80, ending on a corridor of
facades with the skyline behind them.

**It stops above the roofline, and that is the finding.** Eighteen candidate
endings were rendered across six blocks at 9, 14 and 20 metres to see where the
photogrammetry gives out. At 14 m — level with a fourth-floor window, which is
where the shot was supposed to land — the brick drips, the windows are smears,
and there is no readable fire escape on any block. It is flown imagery: facades
are reconstructed from oblique passes and there is a height below which there is
nothing to reconstruct them from.

So the last hundred feet are not photography's to do.

Costs one Google session per render. Enterprise SKUs include a thousand a
month, so this is free and so are a hundred more of it.

---

## Beat 3 — the walk-up and the room (5s) · generated

The one beat no code here can make. There is no photogrammetry of the inside of
an apartment and, at street level, not much of the outside of one either.

Generate as **two stills** and animate between them, rather than as a clip.
Every model worth using takes a start frame and an end frame, so supplying both
means the seams are pinned to images that can be checked rather than to
whatever the model decided the middle looked like.

### 3a — the walk-up, from across the street

> Pre-war New York tenement walk-up seen from across a narrow street at blue
> hour, twenty minutes after sunset. Six storeys of dark red brick, black iron
> fire escape zigzagging down the facade, air conditioning units in two of the
> windows. One window on the fourth floor is lit warm from inside, sash raised
> a few inches, everything else dark. Deep blue sky with a thin orange band low
> behind the roofline. Wet asphalt below holding one streetlight reflection.
> Photorealistic, shot on 35mm, slight lens compression, no people, no text, no
> signage.

**Has to hold:** the lit window in the upper third, and no other light source
competing with it. That window is where the camera goes next.

### 3b — the room, from the window

> Interior of a small student apartment in New York at night, seen from just
> inside a sash window. A wooden desk against the wall under the window with an
> open laptop on it, screen completely dark and switched off, facing the
> camera, occupying the central third of the frame. Beside it a steel water
> bottle with stickers on it, a stack of textbooks, a mug, loose paper, a
> desk lamp switched on and pointing at the wall. Above the desk a Rice
> University banner in blue and grey pinned to exposed brick, a periodic table
> poster, two film posters, a string of small warm fairy lights along the top of
> the wall, index cards and photographs stuck up unevenly. An unmade bed edge in
> shadow at the left. Warm lamp light from the right, cool blue street light
> falling through the window behind the camera. Dust in the air, shallow depth
> of field, film grain, anamorphic. Photorealistic. No people, no text on the
> laptop screen, nothing legible on the posters.

**Three things this shot does not work without:**

1. **The laptop screen dark and empty.** Anything on it fights the interface
   that fades up over it. Say it twice in the prompt if the model puts a
   wallpaper on it anyway.
2. **Centred and roughly level**, filling 55 to 70% of the frame width. The
   interface appears inside that rectangle.
3. **Nothing legible.** A model asked for posters will invent lettering, and
   invented lettering is the single clearest tell in a generated frame. The
   Rice banner is the one exception and should be colour and shape rather than
   a wordmark.

Detail is what makes an interior read as somebody's rather than as a set. The
water bottle, the loose paper and the unevenly stuck index cards are doing more
work than the furniture.

---

## Beat 4 — the handoff · CSS, done

Already in `opening.js`. The interface fades up inside the laptop bezel and the
bezel scales up and off the edges, so nothing ever has to line up: the UI
appears inside a rectangle this code controls.

A straight cut would need a pixel-perfect match against a generated frame,
which is hard to produce and obvious when it is close but wrong.

---

## Stitching

Save the generated clip as `clip3.mp4` in `site/media/`, then:

    cd site && node scripts/stitch-intro.mjs

That joins the beats with short cross-dissolves and writes
`public/opening/intro.mp4`, which is what the page plays.

The dissolves are the point. Each seam sits where one thing fills the frame —
cloud, then a building face, then a window — so there is nothing on screen for
the eye to compare across the join.

---

## The whole thing, at a glance

| | length | made by | done |
|---|---|---|---|
| Earth | 6s | this repo | yes |
| descent | 7s | Google's tiles, this repo | rendering |
| walk-up and room | 5s | generated, 2 stills | prompts above |
| handoff | — | CSS | yes |

Eighteen seconds is long for something a visitor did not ask for, so the skip
is on screen from the first frame and the whole thing is optional: if
`intro.mp4` is missing the page starts on the globe and says nothing about it.
