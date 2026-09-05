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
    "earth-night.jpg": (
        "https://eoimages.gsfc.nasa.gov/images/imagerecords/55000/55167/"
        "earth_lights_lrg.jpg",
        "Earth at night, city lights",
    ),
}

CREDIT = """NASA Visible Earth, public domain.

Blue Marble: Next Generation was produced by Reto Stockli, NASA Earth
Observatory, using data from the MODIS instrument aboard Terra. The night
lights mosaic is from the Defense Meteorological Satellite Program.

US government works are not subject to copyright. The credit is here because
saying where a picture came from is the right thing to do, not because a
licence demands it.
"""


def fetch(name: str, url: str, label: str, force: bool = False) -> None:
    dest = OUT / name
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download what is present")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"NASA imagery -> {OUT.relative_to(ROOT)}")
    for name, (url, label) in SOURCES.items():
        fetch(name, url, label, args.force)
    (OUT / "CREDIT.txt").write_text(CREDIT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
