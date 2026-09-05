"""Render the globe's textures from the boundary data already in this repo.

The site needs a recognisable Earth, and the coastlines for one are sitting in
`data/boundaries/`, put there for the geocell experiment. Drawing them rather
than downloading a NASA image keeps the site's assets generated from the
project's own data, and it means the land the camera flies over is the same
land the classifier was trained against.

Two textures come out, and the page cross-fades between them as a run resolves:

    globe-metal.png    dark machined steel, coastlines etched as glowing seams
    globe-natural.png  land and sea, shaded by latitude

Equirectangular projection throughout: longitude maps straight to x, latitude
straight to y, which is the layout three.js expects when it wraps an image
around a sphere.

    ./.venv/bin/python scripts/build_globe_textures.py
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pathlib

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOUNDARIES = ROOT / "data/boundaries/ne_50m_admin_0_countries.geojson"
OUT = ROOT / "site/public/textures"

# 2:1, because the projection is. 4096 wide is sharp on a retina display at the
# size this sphere is drawn and still only a few hundred kilobytes as a PNG.
WIDTH, HEIGHT = 4096, 2048


def rings(path: pathlib.Path):
    """Every outer ring of every country, in lon/lat."""
    data = json.loads(path.read_text())
    for feature in data["features"]:
        geom = feature.get("geometry") or {}
        kind = geom.get("type")
        if kind == "Polygon":
            polys = [geom["coordinates"]]
        elif kind == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        for poly in polys:
            if poly:
                yield poly[0]


def project(ring, w: int, h: int):
    """Longitude and latitude onto pixels.

    Rings that straddle the antimeridian would otherwise draw a band right
    across the map as the line runs from +180 back to -180. Splitting on a
    large jump in x breaks them into pieces that each stay on one side.
    """
    pieces, current, last_x = [], [], None
    for lon, lat in ring:
        x = (lon + 180.0) / 360.0 * w
        y = (90.0 - lat) / 180.0 * h
        if last_x is not None and abs(x - last_x) > w * 0.5:
            if len(current) > 2:
                pieces.append(current)
            current = []
        current.append((x, y))
        last_x = x
    if len(current) > 2:
        pieces.append(current)
    return pieces


def land_mask(w: int, h: int) -> Image.Image:
    """White where there is land, black where there is not."""
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for ring in rings(BOUNDARIES):
        for piece in project(ring, w, h):
            draw.polygon(piece, fill=255)
    return mask


def coastlines(w: int, h: int, width: int = 3) -> Image.Image:
    """Just the outlines, for the etched look."""
    lines = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(lines)
    for ring in rings(BOUNDARIES):
        for piece in project(ring, w, h):
            draw.line(piece + [piece[0]], fill=255, width=width)
    return lines


def metal(mask: Image.Image, coast: Image.Image) -> Image.Image:
    """Machined tungsten with the coastlines cut into it.

    The first version was near-black and read as a void rather than as a metal
    object. Tungsten is a pale, slightly warm grey, and a metal texture has to
    be genuinely light: metalness multiplies the reflection by the base colour,
    so a dark base cancels out the environment the material is supposed to be
    showing you. Dark metal is the same mistake as no environment map, made a
    second way.

    Land sits lighter than sea so the continents are legible before anything is
    coloured, and the coastline is a bright seam rather than a drawn border.
    The read should be a milled surface, not a printed map.
    """
    import numpy as np

    w, h = mask.size
    SEA = np.array([118, 124, 132], np.float32)      # tungsten
    LAND = np.array([166, 170, 176], np.float32)     # a machined step higher

    m = (np.asarray(mask, np.float32) / 255.0)[:, :, None]
    out = SEA * (1 - m) + LAND * m

    # Brushed grain, so the surface has a direction and catches the light like
    # something that was turned on a lathe.
    grain = _fbm(w, h, octaves=4, seed=3)
    out += ((grain - 0.5) * 26.0)[:, :, None]

    # The seam: a bright line where the coast is, blurred into a glow.
    seam = np.asarray(coast.filter(ImageFilter.GaussianBlur(max(1, w // 1600))),
                      np.float32) / 255.0
    seam = np.clip(seam * 1.8, 0, 1)[:, :, None]
    out = out * (1 - seam) + np.array([228, 240, 252], np.float32) * seam

    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"), "RGB")


def _fbm(w: int, h: int, octaves: int = 6, seed: int = 7) -> "np.ndarray":
    """Fractal noise in [0, 1], tiling horizontally.

    Sum of several octaves of smooth random values, each at twice the frequency
    and half the amplitude of the last. That is what gives natural terrain its
    look: large shapes with smaller ones on them, all the way down.

    The x axis wraps, because this texture is going around a sphere and a seam
    down the Pacific is the one flaw nobody misses.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), dtype=np.float32)
    amplitude, total = 1.0, 0.0
    for octave in range(octaves):
        gw = max(4, (w >> (octaves - octave)) // 2)
        gh = max(2, (h >> (octaves - octave)) // 2)
        grid = rng.random((gh + 1, gw), dtype=np.float32)
        grid = np.concatenate([grid, grid[:, :1]], axis=1)   # wrap in x

        ys = np.linspace(0, gh, h, endpoint=False)
        xs = np.linspace(0, gw, w, endpoint=False)
        y0 = np.floor(ys).astype(int); x0 = np.floor(xs).astype(int)
        fy = (ys - y0)[:, None]; fx = (xs - x0)[None, :]
        # Smoothstep, so the interpolation has no visible grid creases.
        fy = fy * fy * (3 - 2 * fy); fx = fx * fx * (3 - 2 * fx)
        y1 = np.minimum(y0 + 1, gh); x1 = (x0 + 1) % (gw + 1)

        top = grid[y0][:, x0] * (1 - fx) + grid[y0][:, x1] * fx
        bot = grid[y1][:, x0] * (1 - fx) + grid[y1][:, x1] * fx
        out += (top * (1 - fy) + bot * fy) * amplitude
        total += amplitude
        amplitude *= 0.5
    return out / total


def natural(mask: Image.Image, coast: Image.Image) -> Image.Image:
    """Land and sea, shaded by latitude and broken up by terrain noise.

    Not a satellite image and not pretending to be. Latitude gets most of the
    way to something that reads as Earth: ice at the poles, boreal green, a dry
    band at the horse latitudes where the world's deserts actually sit, and
    tropical green at the equator.

    The first version banded the latitudes with a sine wave and the result was
    a striped beach ball. Real terrain is not a function of latitude alone, so
    the bands are now smooth and the variation comes from fractal noise on top:
    the same climate zones, with mountains and basins interrupting them.
    """
    import numpy as np

    w, h = mask.size
    lat = 90.0 - (np.arange(h, dtype=np.float32) / h) * 180.0
    a = np.abs(lat)[:, None]

    def band(lo, hi, colour_lo, colour_hi):
        """Smooth blend between two colours across a latitude range."""
        t = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
        t = t * t * (3 - 2 * t)
        return [colour_lo[i] + (colour_hi[i] - colour_lo[i]) * t for i in range(3)]

    TROPICS = (42, 92, 52); ARID = (156, 132, 88)
    TEMPERATE = (72, 108, 66); BOREAL = (48, 76, 58); ICE = (236, 241, 246)

    land = np.zeros((h, w, 3), dtype=np.float32)
    for i in range(3):
        c = np.full((h, 1), float(TROPICS[i]), dtype=np.float32)
        c = np.where(a > 12, band(12, 30, TROPICS, ARID)[i], c)
        c = np.where(a > 30, band(30, 46, ARID, TEMPERATE)[i], c)
        c = np.where(a > 46, band(46, 62, TEMPERATE, BOREAL)[i], c)
        c = np.where(a > 62, band(62, 76, BOREAL, ICE)[i], c)
        land[:, :, i] = c

    # Terrain. Two scales: broad relief, and a finer grain over it.
    relief = _fbm(w, h, octaves=6, seed=11)
    detail = _fbm(w, h, octaves=7, seed=29)
    height = (relief * 0.72 + detail * 0.28)

    # Darker in the basins, lighter and greyer on the peaks.
    shade = ((height - 0.5) * 78.0)[:, :, None]
    rock = np.clip((height - 0.68) / 0.32, 0, 1)[:, :, None]
    land = land + shade
    land = land * (1 - rock * 0.55) + np.array([148, 146, 142], np.float32) * rock * 0.55

    # Ocean: deep everywhere, lighter towards the equator.
    DEEP = np.array([6, 22, 44], np.float32)
    SHALLOW = np.array([18, 58, 92], np.float32)
    warmth = (1.0 - a / 90.0)
    sea = DEEP + (SHALLOW - DEEP) * warmth
    sea = np.repeat(sea[:, None, :], w, axis=1) if sea.ndim == 2 else sea
    sea = np.broadcast_to(sea[:, None, :] if sea.ndim == 2 else sea, (h, w, 3)).copy()
    sea += ((relief - 0.5) * 10.0)[:, :, None]

    m = (np.asarray(mask, dtype=np.float32) / 255.0)[:, :, None]
    out = sea * (1 - m) + land * m

    # A pale continental shelf just offshore, which is most of what makes a
    # drawn globe read as a real one.
    shelf = np.asarray(coast.filter(ImageFilter.GaussianBlur(w // 340)),
                       dtype=np.float32) / 255.0
    shelf = np.clip(shelf * 2.4, 0, 1)[:, :, None] * (1 - m)
    out = out * (1 - shelf * 0.7) + np.array([70, 126, 158], np.float32) * shelf * 0.7

    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"), "RGB")


def growth_order(mask: Image.Image) -> Image.Image:
    """When each pixel comes alive, as a greyscale map from 0 (first) to 1 (last).

    The transition from metal to Earth is not a cross-fade. Land greens the way
    moss spreads, in patches that widen and join, and the sea fills from the
    deep basins up towards the coast. Both are the same mechanism: every pixel
    is given a moment, and the shader reveals a pixel once the global clock has
    passed it. Ordering the pixels well is the entire effect, and it is decided
    here rather than in the shader.

    Land takes fractal noise directly, so growth starts at many small seeds at
    once and the patches merge. Sea takes distance from the coast inverted, so
    water arrives in the middle of oceans first and creeps inward to the
    shoreline, which is what "filling up" looks like from orbit.
    """
    import numpy as np

    w, h = mask.size
    m = np.asarray(mask, np.float32) / 255.0

    # How far each sea pixel is from land, approximated by blurring the land
    # mask hard: a proper distance transform is slower and looks identical
    # once it is driving a threshold.
    near_land = np.asarray(
        mask.filter(ImageFilter.GaussianBlur(w // 90)), np.float32) / 255.0

    patchy = _fbm(w, h, octaves=5, seed=41)

    # Land: mostly noise, nudged so high latitudes lag slightly. Tundra coming
    # last is both true and legible.
    lat = np.abs(90.0 - (np.arange(h, dtype=np.float32) / h) * 180.0)[:, None]
    land_when = np.clip(patchy * 0.82 + (lat / 90.0) * 0.18, 0, 1)

    # Sea: deep water first, coastline last, with a little noise so the
    # advancing edge is not a clean contour.
    sea_when = np.clip(near_land * 0.85 + patchy * 0.15, 0, 1)

    when = land_when * m + sea_when * (1 - m)
    return Image.fromarray((np.clip(when, 0, 1) * 255).astype("uint8"), "L")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=WIDTH)
    args = ap.parse_args()
    w = args.width
    h = w // 2

    if not BOUNDARIES.exists():
        raise SystemExit(f"no boundaries at {BOUNDARIES}")

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"rendering {w}x{h} from {BOUNDARIES.name}")
    mask = land_mask(w, h)
    coast = coastlines(w, h, width=max(2, w // 1400))

    for name, image in (("globe-metal.png", metal(mask, coast)),
                        ("globe-natural.png", natural(mask, coast))):
        image.save(OUT / name, optimize=True)
        print(f"  {name:<20} {(OUT / name).stat().st_size / 1024:>7.0f} KB")

    # The mask ships too: the shader uses it to keep the sea shiny while the
    # land goes matte, which is the single strongest cue that a sphere is wet
    # in some places and not others.
    growth_order(mask).save(OUT / "globe-growth.png", optimize=True)
    print(f"  {'globe-growth.png':<20} "
          f"{(OUT / 'globe-growth.png').stat().st_size / 1024:>7.0f} KB")

    mask.save(OUT / "globe-land.png", optimize=True)
    print(f"  {'globe-land.png':<20} {(OUT / 'globe-land.png').stat().st_size / 1024:>7.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
