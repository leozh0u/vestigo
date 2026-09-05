"""Download NASA's Earth imagery for the globe.

The textures were drawn from coastline polygons, which is why the planet looked
like a diagram of Earth rather than Earth: latitude bands for climate, noise
for terrain, and a guess at where the deserts are. No amount of tuning gets a
procedural map to the point where somebody says "that looks real", because what
they are comparing it against is a photograph.

So use the photograph. NASA publishes Blue Marble Next Generation, a cloud-free
true-colour composite of the whole planet at 500 m per pixel, and Black Marble,
the night-lights mosaic. Both are **public domain** as US government work, with
no key, no account and no attribution requirement, though the credit line below
is the courteous thing and costs nothing.

    ./.venv/bin/python scripts/fetch_earth_imagery.py

## Which month

August, record 73776. The composites are monthly and the difference between
them is snow cover and how green the northern forests are.

The first version fetched December by mistake, and it is worth saying what that
looked like rather than just correcting it: Canada, Scandinavia and most of
Russia were white, so a planet that had supposedly just come alive was buried
under snow across the entire northern hemisphere. August has the least snow
outside the poles, which means the most visible land.
"""
from __future__ import annotations

import argparse
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site/public/textures"
# Downloads and intermediates live outside public/, because vite copies that
# directory wholesale into the build. The raw mosaic is 0.8 MB of input to a
# derivation nobody's browser needs to run.
WORK = ROOT / "site/media"

AGENT = "vestigo/0.1 (research project; github.com/leozh0u/vestigo)"

# 5400x2700 rather than the 21600-wide originals. The globe is drawn at roughly
# 600 pixels across on screen and 1920 in the render, so anything past this is
# bandwidth for detail no frame can show, and the originals are hundreds of
# megabytes each.
SOURCES = {
    "earth-day.jpg": (
        "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73776/"
        "world.topo.bathy.200408.3x5400x2700.jpg",
        "Blue Marble Next Generation with topography and bathymetry",
    ),
    "earth-night-raw.jpg": (
        "https://eoimages.gsfc.nasa.gov/images/imagerecords/79000/79765/"
        "dnb_land_ocean_ice.2012.3600x1800.jpg",
        "Black Marble 2012, VIIRS day/night band",
    ),
}

# Anything at or below this in the night mosaic is not a light.
#
# The file is called dnb_land_ocean_ice for a reason: under the city lights it
# carries a dim grey rendering of the land, the sea and the ice, so that the
# printed version reads as a planet rather than as a scatter of dots on black.
# Sampled at nine places, the base layer runs from 5 (open ocean) to 32
# (Greenland) and the dimmest real city is over 150. There is no overlap, which
# is why a flat cut is the right instrument here rather than anything cleverer.
#
# Added to the surface as emitted light, that base put a tan wash over the
# Sahara and the whole Amazon basin: continents glowing evenly in the dark,
# which is the one thing a night side must not do.
FLOOR = 40

CREDIT = """NASA Visible Earth, public domain.

Blue Marble: Next Generation was produced by Reto Stockli, NASA Earth
Observatory, using data from the MODIS instrument aboard Terra. The night
lights are Black Marble 2012, from the VIIRS day/night band on Suomi NPP.

US government works are not subject to copyright. The credit is here because
saying where a picture came from is the right thing to do, not because a
licence demands it.
"""


def fetch(name: str, url: str, label: str, force: bool = False,
          into: pathlib.Path | None = None) -> None:
    dest = (into or OUT) / name
    if dest.exists() and not force:
        print(f"  {name:<18} already here ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    # Written through a temporary file, so an interrupted download cannot leave
    # a half-image that loads as a grey band across the planet.
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    print(f"  {name:<18} {len(body) / 1e6:>5.1f} MB   {label}")


def make_night() -> None:
    """Turn the raw mosaic into the two textures the globe samples.

    Two files come out of one download.

    **earth-night.jpg** is the mosaic with its land-and-ocean base cut away, so
    what remains is only light that something emitted. See FLOOR above.

    **earth-glow.jpg** is the same thing blurred. City light seen from orbit
    does not stop at the edge of the city: it scatters through fifty kilometres
    of air into a halo, and the halo is most of what the eye reads as
    brightness. The usual way to get that is a bloom pass over the finished
    frame, but the globe's canvas has to stay transparent — the field of
    readings sits behind it — and screen-space bloom writes an opaque alpha
    across the whole rectangle. Blurring the only thing that will ever be
    bright, once, offline, costs one texture read at runtime and nothing else.

    Done here rather than in the shader because a wide blur cannot be done in
    one pass per pixel, and because this image never changes.
    """
    from PIL import Image, ImageFilter

    raw = Image.open(WORK / "earth-night-raw.jpg").convert("L")
    lights = raw.point(
        lambda v: 0 if v <= FLOOR else int((v - FLOOR) / (255 - FLOOR) * 255)
    )
    lights.save(OUT / "earth-night.jpg", quality=90, optimize=True)

    # Half resolution first: a nine-pixel gaussian over 3600 px is slow, and
    # its output is smooth by definition, so nothing in it survives a
    # downsample anyway.
    small = lights.resize((lights.width // 2, lights.height // 2), Image.LANCZOS)
    glow = small.filter(ImageFilter.GaussianBlur(radius=9))
    # Lifted, because the blur of a mostly black image is mostly black and the
    # halo being asked for lives in the faint end of the range.
    glow = glow.point(lambda v: min(255, int((v / 255) ** 0.72 * 255)))
    glow = glow.resize(lights.size, Image.LANCZOS)
    glow.save(OUT / "earth-glow.jpg", quality=88, optimize=True)

    for name in ("earth-night.jpg", "earth-glow.jpg"):
        print(f"  {name:<18} {(OUT / name).stat().st_size / 1e6:>5.1f} MB   derived")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download what is present")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"NASA imagery -> {OUT.relative_to(ROOT)}")
    WORK.mkdir(parents=True, exist_ok=True)
    for name, (url, label) in SOURCES.items():
        fetch(name, url, label, args.force, into=WORK if name.endswith("-raw.jpg") else OUT)
    make_night()
    (OUT / "CREDIT.txt").write_text(CREDIT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
