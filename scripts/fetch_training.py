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
import concurrent.futures
import hashlib
import io
import json
import math
import pathlib
import random
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/train"
INDEX = ROOT / "data/train_index.json"
API = "https://graph.mapillary.com/images"
FIELDS = "id,computed_geometry,captured_at,compass_angle,is_pano,thumb_1024_url"
# Mapillary caps a bounding box at 0.010 square degrees, so the side cannot
# exceed 0.1. This is 0.09 by 0.09, about 10 km across at the equator, which is
# the largest window the API will answer for and still thin for rural coverage.
BOX = 0.045
EXCLUSION_KM = 25.0         # keep training imagery away from the eval set
PER_SEED = 6


def token() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("MAPILLARY_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("MAPILLARY_TOKEN missing from .env")


# Populated places spread across every inhabited region. Seeds are drawn near
# these rather than from a global lattice, because Mapillary coverage follows
# roads and people. A blind 3 degree grid with the 10 km box the API allows
# returned seven images from several thousand queries, which is a hit rate of
# about a tenth of a percent and not a strategy.
#
# The bias this introduces is real and gets reported rather than corrected:
# coverage follows population and Mapillary's own contributor distribution, so
# Europe and North America are over-represented and much of central Africa and
# central Asia will have no cell at all.
PLACES = [
    # Europe
    (-3.70, 40.42), (2.35, 48.86), (13.40, 52.52), (12.50, 41.90), (-0.13, 51.51),
    (4.90, 52.37), (18.06, 59.33), (24.94, 60.17), (10.75, 59.91), (12.57, 55.68),
    (21.01, 52.23), (14.42, 50.09), (16.37, 48.21), (19.04, 47.50), (26.10, 44.44),
    (23.73, 37.98), (28.98, 41.01), (-8.61, 41.15), (-9.14, 38.72), (2.17, 41.39),
    (9.19, 45.46), (7.69, 45.07), (11.25, 43.77), (6.14, 46.20), (8.54, 47.38),
    (4.35, 50.85), (-6.26, 53.35), (-3.19, 55.95), (-1.55, 53.80), (-2.24, 53.48),
    (30.52, 50.45), (27.56, 53.90), (24.11, 56.95), (25.28, 54.69), (37.62, 55.75),
    (44.51, 40.18), (49.87, 40.41), (20.46, 44.79), (15.98, 45.81), (14.51, 46.06),
    # North America
    (-74.01, 40.71), (-118.24, 34.05), (-87.63, 41.88), (-95.37, 29.76),
    (-112.07, 33.45), (-122.42, 37.77), (-104.99, 39.74), (-93.27, 44.98),
    (-90.20, 38.63), (-84.39, 33.75), (-80.19, 25.76), (-71.06, 42.36),
    (-77.04, 38.91), (-79.38, 43.65), (-73.57, 45.50), (-123.12, 49.28),
    (-114.07, 51.05), (-97.14, 49.90), (-99.13, 19.43), (-103.35, 20.66),
    (-100.31, 25.69), (-86.85, 21.16), (-89.62, 20.97), (-84.09, 9.93),
    (-90.51, 14.63), (-79.52, 8.98), (-76.79, 18.00),
    # South America
    (-58.38, -34.60), (-46.63, -23.55), (-43.17, -22.91), (-47.88, -15.79),
    (-38.51, -12.97), (-34.88, -8.05), (-51.23, -30.03), (-49.27, -25.43),
    (-70.65, -33.45), (-77.03, -12.05), (-74.07, 4.71), (-78.47, -0.18),
    (-66.90, 10.49), (-56.16, -34.90), (-57.64, -25.28), (-68.15, -16.50),
    # Africa
    (31.24, 30.05), (3.38, 6.52), (7.49, 9.06), (-0.19, 5.60), (-17.45, 14.72),
    (-7.59, 33.57), (10.18, 36.81), (3.06, 36.75), (13.19, 32.89), (32.53, 15.50),
    (38.76, 9.03), (36.82, -1.29), (32.58, 0.35), (30.06, -1.94), (39.28, -6.82),
    (28.03, -26.20), (18.42, -33.93), (31.03, -17.83), (25.91, -24.65),
    (47.52, -18.88), (57.50, -20.16), (9.70, 4.05),
    # Asia
    (139.69, 35.69), (135.50, 34.69), (126.98, 37.57), (129.08, 35.18),
    (116.41, 39.90), (121.47, 31.23), (113.26, 23.13), (114.06, 22.54),
    (120.98, 23.97), (100.50, 13.76), (103.82, 1.35), (101.69, 3.14),
    (106.85, -6.21), (110.37, -7.80), (120.98, 14.60), (105.85, 21.03),
    (106.66, 10.82), (104.92, 11.56), (96.16, 16.87), (90.41, 23.81),
    (77.21, 28.61), (72.88, 19.08), (80.27, 13.08), (77.59, 12.97),
    (88.36, 22.57), (67.01, 24.86), (74.36, 31.52), (85.32, 27.72),
    (79.86, 6.93), (55.27, 25.20), (51.53, 25.29), (46.72, 24.71),
    (35.21, 31.77), (35.51, 33.89), (44.36, 33.31), (51.39, 35.69),
    (69.24, 41.30), (76.89, 43.24), (71.43, 51.13), (49.11, 55.79),
    (82.92, 55.03), (104.30, 52.29), (135.08, 48.48), (131.89, 43.12),
    # Oceania
    (151.21, -33.87), (144.96, -37.81), (153.03, -27.47), (138.60, -34.93),
    (115.86, -31.95), (147.33, -42.88), (174.76, -36.85), (174.78, -41.29),
    (172.64, -43.53), (178.44, -18.14), (147.15, -9.44), (166.46, -22.28),
]


def seeds(step: float = 0.0, per_place: int = 24, spread_km: float = 60.0,
          rng_seed: int = 20260822):
    """Points near populated places, offset onto the roads leading out of them.

    Not the place itself. A seed on a city centre returns the same tourist
    streetscape that made the urban half of the eval set too easy, so each seed
    is thrown a random 5 to `spread_km` kilometres in a random direction. That
    lands on ring roads, suburbs, farmland and the routes between towns, which
    is both what Mapillary has and what the project is aimed at.

    Deterministic, so an interrupted run resumes over the same seeds.
    """
    rng = random.Random(rng_seed)
    out = []
    for lon, lat in PLACES:
        for _ in range(per_place):
            bearing = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(5.0, spread_km)
            dlat = (dist / 111.0) * math.cos(bearing)
            dlon = (dist / (111.0 * max(0.2, math.cos(math.radians(lat))))) * math.sin(bearing)
            out.append((round(lon + dlon, 3), round(lat + dlat, 3)))
    rng.shuffle(out)                 # so an early stop is still globally spread
    return out


def excluded(lon: float, lat: float, eval_points) -> bool:
    import math
    for elat, elon in eval_points:
        p1, p2 = math.radians(lat), math.radians(elat)
        h = (math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2)
             * math.sin(math.radians(elon - lon) / 2) ** 2)
        if 2 * 6371.0088 * math.asin(math.sqrt(h)) < EXCLUSION_KM:
            return True
    return False


def query(tok, lon, lat, limit, errors: dict, box: float = BOX, depth: int = 0):
    """Ask for images in one box.

    An empty box and a rejected request look identical from the caller, and the
    first version treated both as "nothing here". It fetched zero images and
    said so without a reason, because every request had been refused for an
    oversized bounding box. Errors are counted and reported now: a run that
    finds nothing should say whether the world was empty or the API said no.
    """
    # Clamp to the valid range. A seed at -180 produces a west edge of
    # -180.045, which the API rejects outright.
    west, east = max(-180.0, lon - box), min(180.0, lon + box)
    south, north = max(-90.0, lat - box), min(90.0, lat + box)
    bbox = f"{west},{south},{east},{north}"
    url = f"{API}?{urllib.parse.urlencode({'access_token': tok, 'fields': FIELDS, 'bbox': bbox, 'limit': limit})}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read()).get("data", [])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        # "Please reduce the amount of data you're asking for" means the box
        # holds too much imagery, not too little. Those are the dense areas and
        # the best boxes in the run, so halve and retry rather than discard.
        if "reduce the amount of data" in detail and depth < 3:
            errors["shrunk"] = errors.get("shrunk", 0) + 1
            return query(tok, lon, lat, limit, errors, box / 2, depth + 1)
        errors[f"HTTP {exc.code}"] = errors.get(f"HTTP {exc.code}", 0) + 1
        errors.setdefault("_first", detail)
        return []
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        # A read timing out arrives as a bare TimeoutError rather than through
        # urllib's own hierarchy, and one slow box should not end a run of
        # several thousand.
        errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1
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
    ap.add_argument("--per-place", type=int, default=24,
                    help="seeds thrown around each populated place")
    ap.add_argument("--workers", type=int, default=8,
                    help="boxes queried at once. Network bound, so this is close "
                         "to a linear speedup over an almost entirely empty grid")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text()) if INDEX.exists() else []
    have = {r["mapillary_id"] for r in index}
    done_seeds = {tuple(r["seed"]) for r in index}

    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    eval_points = [(e["truth"]["lat"], e["truth"]["lon"]) for e in manifest]

    tok = token()
    errors: dict = {}
    tried = 0
    print(f"{len(index)} already fetched, target {args.target}")

    # Most of a global grid is ocean, and a box that covers ten kilometres needs
    # a lot of boxes. Querying them one at a time spends most of an hour waiting
    # on the network for empty answers, so the lookups run in parallel and only
    # the downloads are serialised, which keeps the index consistent.
    todo = [(lon, lat) for lon, lat in seeds(per_place=args.per_place)
            if (lon, lat) not in done_seeds and not excluded(lon, lat, eval_points)]
    print(f"{len(todo)} boxes to query, around {len(PLACES)} places")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(query, tok, lon, lat, PER_SEED, errors): (lon, lat)
                   for lon, lat in todo}
        for future in concurrent.futures.as_completed(futures):
            tried += 1
            if len(index) >= args.target:
                for other in futures:
                    other.cancel()
                continue
            lon, lat = futures[future]
            try:
                rows = future.result()
            except Exception:
                continue
            for row in rows:
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
                if len(index) % 50 == 0:
                    INDEX.write_text(json.dumps(index) + "\n")
                    print(f"  {len(index)} images, {tried}/{len(todo)} boxes", flush=True)

    INDEX.write_text(json.dumps(index) + "\n")
    lats = [r["lat"] for r in index]
    print(f"\n{len(index)} images in {OUT}, from {tried} boxes queried")
    if errors:
        first = errors.pop("_first", "")
        print(f"  request failures: {errors}")
        if first:
            print(f"  first was: {first}")
    if lats:
        north = sum(1 for la in lats if la > 25) / len(lats)
        print(f"  {north:.0%} north of 25 degrees, which is the coverage skew "
              "this data has and the writeup has to report")


if __name__ == "__main__":
    raise SystemExit(main())
