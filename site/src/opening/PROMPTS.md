# The intro, and what is left to make

Four beats. Two are rendered from this repository and are finished, one is
generated, and the last is a push on a still. Nothing below is a preference —
the division came out of measuring what each tool can and cannot do, and every
number here was measured rather than chosen.

---

## Beat 1 — the Earth (5s) · rendered, done

    node scripts/render-intro.mjs

A machined metal sphere turning, which becomes a night Earth: continents rise,
basins sink, water fills them, the cities come on. Then the sun swings round to
daylight as the camera dives, and it hands over three thousand kilometres above
New York looking straight down.

Daylight at the handover is a compromise and worth naming. The globe on the site
stays night, which is the better picture, but Google publishes no imagery except
midday and the two halves have to be lit the same way at the join. So the sun
moves during the dive. The trade is one beat of the intro against a seam.

## Beat 2 — the descent (9.4s) · rendered, done

    node scripts/render-descent.mjs

Google's Photorealistic 3D Tiles — real captured geometry — from three thousand
kilometres down to a hundred and fifty metres over the Upper East Side, looking
almost straight down.

It used to end at seventeen metres, level with a fifth-floor window, and that
was wrong for a reason worth keeping written down. Sampled frame by frame off
the finished file: at two hundred metres looking down there are legible cars,
kerbs and rooftops; at a hundred and fourteen metres with the camera pitched
towards a wall it is dripping brick and smeared windows. **The altitude was not
what broke it. The angle was.** Google reconstructs from aerial photography, so
it has many views of every roof and few of any wall, and every degree the camera
turns off vertical trades a surface it has data for against one it does not.

So the shot stays near-vertical, stops at a hundred and fifty metres, and hands
over. Costs one Google session per render.

The last bright frame is written to `media/keyframe-01-aerial.png` and is the
first keyframe of everything below.

---

## Beats 3 and 4 — into the room

Below a hundred and fifty metres there is no photography to fly through, so the
rest is built out of stills. Two generated images pin the ends of two generated
moves, and the final push onto the laptop is rendered here, where it can be
exact.

    keyframe 1  (real)       aerial, 150 m, near-vertical, late afternoon
      |  generated move A     the dive continues, swings level at a window
    keyframe 2  (generated)  outside a fifth-floor window, square on
      |  generated move B     through the opening, into the room
    keyframe 3  (generated)  inside, the desk on the far wall
      |  rendered push        scripts/render-room.mjs
    the interface

Every image is generated one at a time, with the previous one attached, so the
light, the brick and the room carry forward instead of being described twice and
coming back different.

### The room, fixed once so every image agrees

A small fifth-floor studio in a pre-war red brick walk-up on the Upper East
Side. About three and a half metres wide and four and a half deep. Late
afternoon, the sun low and warm and coming in through the one window.

The geometry matters more than the decor, and there is only one rule: **the desk
stands against the wall directly opposite the window, and the laptop faces the
window.** So a camera that comes in through the opening is looking straight at
the screen, square on, with the light behind it. Any other arrangement and the
last move arrives at the laptop from an angle, which the handoff cannot use —
the page grows that screen rectangle until it fills the viewport, and a
trapezium does not grow into a rectangle.

- **Window.** Tall double-hung sash, white paint chipped at the sill, six panes
  over one. The lower sash raised about sixty centimetres. A black iron fire
  escape outside it. A sheer curtain pushed to the left.
- **Walls.** Off-white plaster, uneven, warm in the low sun. A hairline crack
  running down from the ceiling on the left. Four or five postcards and a
  printed photograph taped above the desk, no readable text.
- **Floor.** Dark stained oak parquet, scuffed, a flat grey rug under the desk.
- **Desk.** Light birch, plain, about a hundred and twenty centimetres wide,
  pushed against the far wall under the postcards.
- **On the desk.** A fourteen-inch space-grey laptop, open, screen off and
  completely black. A white ceramic mug to its right. A stack of three books to
  its left with a spiral notebook and a pen on top. A small brass desk lamp,
  switched off. A white charging cable trailing off the back edge. Over-ear
  headphones lying flat.
- **Chair.** A plain wooden chair pushed back from the desk, a dark jacket over
  the back of it.
- **The rest of the room.** A single bed along the right wall with a navy duvet,
  unmade. A half-full bookshelf on the left. A pair of trainers by the door. A
  small plant on the window sill.
- **How messy.** Lived in, not squalid. The bed unmade, papers on the desk, a
  mug that has been there a while. Nothing on the floor except the trainers.

---

### Image 1 — outside the window

Attach `media/keyframe-01-aerial.png`. Ask for the largest size available.

> Continue this shot. A photograph taken from the air, hovering just outside a
> fifth-floor window of a red brick pre-war walk-up on the Upper East Side of
> Manhattan, late afternoon, the sun low and warm and coming from the left. The
> camera is level with the window and square on to it, about two metres out, so
> the window fills most of the frame. A black iron fire escape crosses the lower
> left. The window is a tall white double-hung sash, six panes over one, paint
> chipped at the sill, and its lower half is raised about sixty centimetres. A
> sheer curtain is pushed to one side. Through the opening the room beyond is
> dim and only half readable: a plain birch desk against the far wall with an
> open laptop on it, its screen off and black, and postcards taped to the wall
> above. Weathered red brick and pale mortar around the window. Realistic
> photograph, 35mm lens, sharp, no text anywhere, no people, no logos.
> Landscape, 16:9.

### Image 2 — inside, from the window

Attach image 1. This one is also the plate the final push is rendered from, so
it has to be right, and it has to be big.

> Continue this shot, now inside the room. A photograph taken from just inside
> the window of a small fifth-floor studio apartment on the Upper East Side,
> looking straight across the room at the far wall. Late afternoon, the low sun
> coming in from behind the camera and falling warm across the room. The room is
> about three and a half metres wide and four and a half deep, with off-white
> uneven plaster walls and dark stained oak parquet.
>
> Against the far wall, directly opposite the camera and roughly centred in the
> frame, stands a plain light birch desk about a hundred and twenty centimetres
> wide. On it an open fourteen-inch space-grey laptop faces the camera almost
> exactly square on, its screen switched off and completely black, all four
> corners of the display clearly visible and unobstructed. The laptop is about a
> quarter of the frame's width. Beside it a white ceramic mug, a stack of three
> books with a spiral notebook and a pen on top, a small brass desk lamp
> switched off, a white charging cable trailing off the back edge, and a pair of
> over-ear headphones lying flat. Four or five postcards and a printed
> photograph are taped to the wall above the desk. A plain wooden chair is
> pushed back from the desk with a dark jacket over its back.
>
> A single bed with an unmade navy duvet runs along the right wall, partly in
> frame. A half-full bookshelf on the left. A flat grey rug under the desk. A
> pair of trainers by the door. Lived in but not squalid.
>
> Realistic photograph, 35mm lens, moderate depth of field, sharp on the desk.
> No text anywhere, no readable writing, no people, no logos, no reflections or
> glare on the laptop screen. Landscape, 16:9, highest resolution available.

### What to reject

- A keyboard with warped or nonsensical keys. It is on screen for most of the
  push and it is the usual tell.
- A laptop seen at an angle. Square on or regenerate.
- Anything on the screen. It gets painted over, but a lit screen throws light
  into the room that will not match once it is replaced.
- Text on the postcards, the books or the wall. It always comes out as
  nonsense and it is the second usual tell.

---

## Beat 5 — the push onto the laptop · rendered here

    node scripts/render-room.mjs --photo media/room.png \
      --corners "x1,y1 x2,y2 x3,y3 x4,y4"

Corners clockwise from the screen's top left, in pixels of the image. The
interface is warped into the screen with a projective transform — not an affine
one, because a photographed screen's edges converge and an affine map keeps
parallel lines parallel — and the camera pushes in until the screen fills 62% of
the frame. It writes `media/room-end.json`, which stitch-intro puts in the
manifest, and the page grows the live interface out of that rectangle.

This last move is rendered rather than generated because it is the one that has
to be exact. Everything else only has to look right.
