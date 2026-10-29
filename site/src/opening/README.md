# The opening sequence

The intro runs from Earth through Manhattan, into an apartment and onto a laptop. The laptop screen contains the live page. At the end, that page fills the viewport and becomes interactive. Skip and Escape return directly to the page.

## Render pipeline

The published film combines an Earth render, saved Google Photorealistic 3D Tiles footage and a Blender apartment. The six-second room and four-second exterior approach share a lighting setup and meet at the same camera pose. The final laptop screen becomes the live page.

## Present the published version

```sh
npm run assets:fetch
npm run assets:check
npm run check
npm run build
npm run preview
```

The asset fetch restores the checksum-locked published film and textures. It
does not call a model or map API or generate new media. The portal check uses
the screen track in the tracked public manifest, so it needs no ignored render
inputs. The full native render pipeline below is separate from presentation.

Local render outputs live under `media/continuous/` and are ignored by Git. The assembly script checks frame counts, duration, black intervals and the window camera join. It produces a review candidate before touching the public manifest.

```sh
# Requires Python with Pillow, ffmpeg and the existing rendered inputs.
node scripts/assemble-connected-intro.mjs
node scripts/check-screen-portal.mjs
node scripts/check-intro-guards.mjs
npm run build
```

Set `PYTHON` if Pillow is installed in a separate Python environment. The portal check reads the accepted room's `camera.json`.

After visual review, place the verdict and exact candidate SHA-256 in `approach-final/review.json`. Publication requires a passing verdict or explicit preview approval for those bytes:

```sh
node scripts/assemble-connected-intro.mjs --publish
./scripts/deploy.sh
```

The deploy script builds locally, validates asset references and pushes a new commit to `gh-pages` without rewriting history.

## City rendering and credits

`render-city-bridge.mjs` renders the descent and exterior background. `render-approach.py` renders the apartment facade with transparency. These tools do not extract Google's meshes. A map render requires an enabled Map Tiles API key and a same-day check of the account's no-cash billing condition. The CLI date flag records that check; it does not establish billing status by itself. Keys stay in an ignored environment file.

Map provider metadata is retained with the local render outputs. The published film has no bottom text overlay. See [Google's Map Tiles policies](https://developers.google.com/maps/documentation/tile/policies). Native scene asset sources and licences are recorded in `scripts/scene-assets.json`.

## Live laptop screen

`screen-portal.js` projects the existing page into the laptop's four screen corners using the exported camera track. It moves the actual DOM nodes, including the WebGL canvas, into a temporary stage. A matching hole in the video reveals them. The final transform becomes the viewport's identity transform, then the nodes return to their original positions.

The manifest carries the film path, camera state and screen track. Missing assets, load errors, stalled playback and timeouts return control to the page. `?introProof` selects the local candidate only in development. Reduced-motion preferences bypass the film.
