# The intro, and what is left to make

Three beats. Two are rendered from this repository and are finished; one has to
be generated. Nothing below is a preference — the division came out of measuring
what each tool can and cannot do, and every number here was measured rather than
chosen.

---

## Beat 1 — the Earth (7s) · rendered, done

    node scripts/render-intro.mjs --seconds 7 --fps 30

A machined metal sphere turning, which becomes a night Earth: continents rise,
basins sink, water fills them, the cities come on. Then the sun swings round to
daylight as the camera dives, and it hands over three thousand kilometres above
New York looking straight down.

Daylight at the handover is a compromise and worth naming. The globe on the site
stays night, which is the better picture, but Google publishes no imagery except
midday and the two halves have to be lit the same way at the join. So the sun
moves during the dive. The trade is one beat of the intro against a seam.

## Beat 2 — the descent (12s) · rendered, done

    node scripts/render-descent.mjs

Google's Photorealistic 3D Tiles — real captured geometry — from three thousand
kilometres down to seventeen metres, ending level with a fifth-floor window on a
red brick tenement on East 6th near Avenue B, twenty-eight metres out from it.

The whole fall is one camera through one dataset, because the tileset is global.
There is nothing joined in the middle of it.

Costs one Google session per render. Enterprise SKUs include a thousand events a
month, so this is free and so are a few hundred more of it.

---

## Beat 3 — through the window (about 5s) · generated, not started

The one beat no code here can make, and the reason is measured rather than
assumed.

Eighteen candidate endings were rendered across six blocks to find where the
photogrammetry gives out, and then the block around the ending was searched
properly: a grid of standing positions at seventeen metres, keeping only those
with nine metres clear around them, then the nearest building front from each.

**Below about thirty metres of stand-off there is nothing to work with.** At
seventeen metres up and twelve metres out, the scan has no windows in it at all
— the wall comes back as a smooth pale blob, because the imagery is flown and
there was never a clean line of sight down a narrow street. From about thirty
metres the tenements return: window reveals, fire escapes, courses in the brick.

That is exactly where the descent now stops, and it is why the last few metres
are not photography's to do.

### What to condition on

    ffmpeg -sseof -0.05 -i media/descent.mp4 -frames:v 1 media/last-frame.png

That frame is the first frame of the generated clip, and it is not negotiable.
Conditioning on a description instead of on the actual frame is how a join ends
up at a different temperature, a different sharpness and a different time of
day, all at once, in a shot whose entire point is that it has no cuts.

### The move

One continuous push from where the descent stops: forward across the gap,
towards one window on the fifth floor, through the raised sash, and into the
room, settling on a desk with a laptop on it. No cut, no change of lens, no
change of speed at the window.

### The room

> Interior of a small student apartment in New York, seen from just inside a
> raised sash window in daylight. A wooden desk against the wall under the
> window with an open laptop on it, screen completely dark and switched off,
> facing the camera, occupying the central third of the frame. Beside it a steel
> water bottle covered in stickers, a stack of textbooks, a mug, loose paper, a
> desk lamp. Above the desk a Rice University banner in blue and grey pinned to
> exposed brick, a periodic table poster, two film posters, index cards and
> photographs stuck up unevenly. An unmade bed edge in shadow at the left. Dust
> in the air, shallow depth of field, film grain. Photorealistic. No people, no
> text on the laptop screen, nothing legible on the posters.

**Three things it does not work without:**

1. **The laptop screen dark and empty.** Anything on it fights the interface
   that fades up over it. Say it twice if the model puts a wallpaper on it
   anyway.
2. **Centred and roughly level**, filling 55 to 70% of the frame width. The
   interface appears inside that rectangle.
3. **Nothing legible.** A model asked for posters will invent lettering, and
   invented lettering is the single clearest tell in a generated frame. The Rice
   banner is the exception and should read as colour and shape, not as a
   wordmark.

Detail is what makes an interior read as somebody's rather than as a set. The
water bottle, the loose paper and the unevenly stuck index cards do more work
than the furniture does.

### After it comes back

It goes through the same grade as the footage before it is joined, or it will
sit at a different temperature and sharpness and the join will be the most
obvious thing in the intro. Match it the way the handover was matched: measure
the last real frame and the first generated one, and correct until they agree.
`scripts/match-plate.mjs` is the pattern — histogram matching between two frames
of the same thing, fitted rather than eyeballed, composed over two passes.

---

## Beat 4 — the handoff · CSS, done

Already in `opening.js`. The interface fades up inside the laptop bezel and the
bezel scales up and off the edges, so nothing has to line up: the UI appears
inside a rectangle this code controls. A straight cut would need a pixel-perfect
match against a generated frame, which is hard to produce and obvious when it is
close but wrong.

---

## Stitching

Drop the generated clip at `site/media/room.mp4`, then:

    cd site && node scripts/stitch-intro.mjs
    node scripts/check-intro.mjs public/opening/intro-*.mp4

`stitch-intro` joins whatever exists, hashes the output by content and writes the
manifest the page reads. `check-intro` is the gate: it looks for empty frames,
single-frame discontinuities, a stalled camera, and a run much slower than the
runs either side of it. All four exist because all four shipped at some point.

---

## The whole thing, at a glance

| | length | made by | done |
|---|---|---|---|
| Earth | 7s | this repo | yes |
| descent | 12s | Google's tiles, this repo | yes |
| through the window | ~5s | generated | prompts above |
| handoff | — | CSS | yes |

Nineteen seconds is long for something nobody asked for, so the skip is on
screen from the first frame and the whole thing is optional: if the manifest is
missing, the page starts on the globe and says nothing about it.
