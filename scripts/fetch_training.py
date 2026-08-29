"""Fetch Mapillary imagery to train the geocell classifier on.

The eval set is 28 photographs and deliberately small, because every ground
truth in it was checked by hand. Training needs a different order of magnitude
and a different standard: thousands of images, none of them inspected.

Two rules keep the two sets apart.

Seed points are drawn on a global grid rather than from the eval locations, and
anything landing within `EXCLUSION_KM` of an eval image is dropped. Training on
a photograph taken down the road from a test photograph would produce a number
that means nothing.

Coverage is whatever Mapillary has, which is heavily Europe and North America
and thin almost everywhere else. That is not corrected for here. It is recorded,
because a classifier cannot predict a region it has never seen and the honest
version of this project reports which regions those are rather than quoting one
accuracy figure.

    ./.venv/bin/python scripts/fetch_training.py --target 3000

Resumable. Re-running picks up where it stopped, so it can be interrupted.
"""
import argparse
import hashlib
import io
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/train"
INDEX = ROOT / "data/train_index.json"
API = "https://graph.mapillary.com/images"
FIELDS = "id,computed_geometry,captured_at,compass_angle,is_pano,thumb_1024_url"
BOX = 0.08                  # about 9 km, since rural coverage is thin
EXCLUSION_KM = 25.0         # keep training imagery away from the eval set
PER_SEED = 6


def token() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("MAPILLARY_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("MAPILLARY_TOKEN missing from .env")


def seeds(step: float = 6.0):
    """A global grid, land-biased only by what Mapillary answers for.

    Deliberately not hand-picked. The rural eval set was hand-picked for spread,
    which is right for twenty images checked individually and wrong for training
    data, where choosing the locations means choosing the answer distribution.
    """
    lat = -56.0
    while lat <= 70.0:
        lon = -180.0
        while lon < 180.0:
            yield round(lon, 2), round(lat, 2)
            lon += step
        lat += step


def excluded(lon: float, lat: float, eval_points) -> bool:
    import math
    for elat, elon in eval_points:
        p1, p2 = math.radians(lat), math.radians(elat)
        h = (math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2)
             * math.sin(math.radians(elon - lon) / 2) ** 2)
        if 2 * 6371.0088 * math.asin(math.sqrt(h)) < EXCLUSION_KM:
            return True
    return False


def query(tok, lon, lat, limit):
    bbox = f"{lon - BOX},{lat - BOX},{lon + BOX},{lat + BOX}"
    url = f"{API}?{urllib.parse.urlencode({'access_token': tok, 'fields': FIELDS, 'bbox': bbox, 'limit': limit})}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read()).get("data", [])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []


def fetch(url, dest) -> bool:
    """Download, strip every scrap of metadata, save.

    Re-encoding through Pillow without an exif argument is what removes it. A
    training image that still carries its GPS tag would let the classifier read
    the answer off the file instead of the picture.
    """
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            img = Image.open(io.BytesIO(r.read())).convert("RGB")
        img.save(dest, "JPEG", quality=88)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=3000)
    ap.add_argument("--step", type=float, default=6.0, help="grid spacing in degrees")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text()) if INDEX.exists() else []
    have = {r["mapillary_id"] for r in index}
    done_seeds = {tuple(r["seed"]) for r in index}

    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    eval_points = [(e["truth"]["lat"], e["truth"]["lon"]) for e in manifest]

    tok = token()
    print(f"{len(index)} already fetched, target {args.target}")

    for lon, lat in seeds(args.step):
        if len(index) >= args.target:
            break
        if (lon, lat) in done_seeds or excluded(lon, lat, eval_points):
            continue
        for row in query(tok, lon, lat, PER_SEED):
            if len(index) >= args.target:
                break
            if row.get("is_pano") or row["id"] in have:
                continue
            geom = (row.get("computed_geometry") or {}).get("coordinates")
            if not geom:
                continue
            name = f"t_{hashlib.sha1(row['id'].encode()).hexdigest()[:12]}.jpg"
            if not fetch(row["thumb_1024_url"], OUT / name):
                continue
            have.add(row["id"])
            index.append({"file": name, "mapillary_id": row["id"],
                          "lat": geom[1], "lon": geom[0], "seed": [lon, lat],
                          "captured_at": row.get("captured_at"),
                          "compass_angle": row.get("compass_angle")})
            if len(index) % 25 == 0:
                INDEX.write_text(json.dumps(index) + "\n")
                print(f"  {len(index)}", flush=True)
        time.sleep(0.15)                 # be polite to a free API

    INDEX.write_text(json.dumps(index) + "\n")
    lats = [r["lat"] for r in index]
    print(f"\n{len(index)} images in {OUT}")
    if lats:
        north = sum(1 for la in lats if la > 25) / len(lats)
        print(f"  {north:.0%} north of 25 degrees, which is the coverage skew "
              "this data has and the writeup has to report")


if __name__ == "__main__":
    raise SystemExit(main())
