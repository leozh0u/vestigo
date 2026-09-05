# The opening sequence

The cinematic that plays before the page: orbit, down through the atmosphere,
into Manhattan, through a window, onto a laptop showing this UI.

It is built in two halves because the two halves have genuinely different
answers, and neither of them is "model it in three.js".

## Half one: orbit to Manhattan — Google Photorealistic 3D Tiles

Not a texture and not a model. Google serves photogrammetry of real cities as
open-standard 3D tiles, and NASA's `3DTilesRendererJS` streams them into an
ordinary three.js scene. You fly between real buildings because they are real
buildings, in the same canvas as the globe, with no cut.

This is why the globe's own descent stops in orbit: a 4096-pixel texture has no
detail below about a hundred kilometres, and no amount of camera work invents
some. The tiles are where the detail comes from.

**Needs:** a Google Maps Platform API key with the Map Tiles API enabled.
1,000 free sessions a month, then $0.60 per thousand. Put it in
`site/.env.local` as `VITE_GOOGLE_MAPS_KEY=...` — Vite only exposes variables
prefixed `VITE_`, and `.env.local` is gitignored by default.

Before committing to it, check whether billing counts a session or a tile
request. A flyover pulls a lot of tiles, and that distinction is the difference
between free forever and a bill.

    npm install 3d-tiles-renderer

## Half two: window to laptop — generated video

Photogrammetry stops at rooftops. There are no interiors in that dataset and
there is no way to fly through a window into a room with it.

A room modelled from primitives and lit as though it were photographed looks
like a room modelled from primitives and lit badly, so the answer is a short
generated clip: six seconds, window to desk, ending on a dark laptop screen.
Higgsfield, Runway, Kling or Veo will all do it; Higgsfield has explicit
camera-move presets, which is what this shot is made of.

Save it as `site/public/opening/interior.mp4`.

### The handoff, which is why the video does not have to be perfect

Do **not** cut from the video into the UI. A pixel-perfect match is hard to
generate and obvious when it is slightly wrong.

Instead the clip ends on a laptop with a dark screen, the real interface fades
up *inside the bezel*, and the bezel then scales up and off the edges of the
frame. Nothing has to match, because the UI appears in a frame this code
controls. It reads as deliberate rather than as a seam that was got away with.

### Prompt to generate it

> Slow cinematic dolly through an open apartment window at night into a dim
> Manhattan loft. Moonlight and street light through the glass, dust in the
> air, shallow depth of field. The camera glides low over a wooden desk and
> settles on an open laptop, screen dark and reflective, filling the last
> third of the frame. No people. No text. Locked, steady move, no handheld
> shake. Photorealistic, 24fps, anamorphic.

Ask for the final frame to hold on the screen for half a second. That still
frame is what the UI fades up over.

## Falling back

If neither asset is present the page skips the opening and starts on the globe,
which is the state it is in today. That is a deliberate default rather than an
error: the site has to work for someone opening it thirty seconds before an
interview, and a cinematic that fails to load must never be the reason it does
not.
