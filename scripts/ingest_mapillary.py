"""Build the Mapillary half of the baseline set.

Mapillary is crowd-sourced street-level imagery: phone photos, dashcams, bike
mounts, variable quality. Deliberately chosen over Google Street View, which
GeoGuessr uses and which cannot legally be scraped for this. The variability is
a feature here -- the target case is an ordinary photograph, not a professional
panorama, so this distribution is closer to real input than Street View is.

Imagery is CC-BY-SA, so the repo attributes it.

Locations are hand-picked for geographic spread rather than sampled, because a
uniform sample of Mapillary is overwhelmingly Europe and North America. The
point of this half is generic streetscapes the model has not memorised, and a
spread across continents tests that harder than ten European roads would.
"""
import hashlib
import io
import json
import pathlib
import time
import urllib.parse
import urllib.request

from PIL import Image

OUT = pathlib.Path("data/images")
API = "https://graph.mapillary.com/images"
FIELDS = "id,computed_geometry,captured_at,compass_angle,is_pano,thumb_2048_url"
BOX = 0.004  # degrees; Mapillary rejects queries covering too much data
N_WANTED = 10

# lon, lat centres, spread across continents and road types.
CANDIDATES = [
    ("jp_tokyo",      139.7008, 35.6595),
    ("br_saopaulo",   -46.6396, -23.5613),
    ("za_capetown",    18.4241, -33.9249),
    ("th_bangkok",    100.5018,  13.7563),
    ("au_melbourne",  144.9631, -37.8136),
    ("mx_cdmx",       -99.1332,  19.4326),
    ("in_bengaluru",   77.5946,  12.9716),
    ("pl_warsaw",      21.0122,  52.2297),
    ("ca_montreal",   -73.5673,  45.5017),
    ("es_madrid",      -3.7038,  40.4168),
    ("tr_istanbul",    28.9784,  41.0082),
    ("ke_nairobi",     36.8219,  -1.2921),
    ("ar_buenosaires", -58.3816, -34.6037),
    ("kr_seoul",      126.9780,  37.5665),
    ("it_rome",        12.4964,  41.9028),
    ("us_chicago",    -87.6298,  41.8781),
]


def token() -> str:
    for line in pathlib.Path(".env").read_text().splitlines():
        if line.startswith("MAPILLARY_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("MAPILLARY_TOKEN missing from .env")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def find_image(tok: str, lon: float, lat: float) -> dict | None:
    """One non-panoramic image with coordinates near this centre."""
    bbox = f"{lon - BOX},{lat - BOX},{lon + BOX},{lat + BOX}"
    q = urllib.parse.urlencode(
        {"access_token": tok, "fields": FIELDS, "bbox": bbox, "limit": 8}
    )
    try:
        data = get_json(f"{API}?{q}")
    except Exception as e:
        print(f"    query failed: {e}")
        return None
    if "error" in data:
        print(f"    api error: {data['error'].get('message')}")
        return None
    for it in data.get("data", []):
        coords = (it.get("computed_geometry") or {}).get("coordinates")
        if not coords or it.get("is_pano") or not it.get("thumb_2048_url"):
            continue
        return it
    return None


def fetch_stripped(url: str, dest: pathlib.Path) -> None:
    """Download and re-encode pixels only, dropping every metadata block."""
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read()
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata()))
        clean.save(dest, format="JPEG", quality=95)


def main() -> int:
    tok = token()
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []

    for name, lon, lat in CANDIDATES:
        if len(entries) >= N_WANTED:
            break
        print(f"  {name} ...", end=" ", flush=True)
        it = find_image(tok, lon, lat)
        if not it:
            print("no usable image")
            continue

        clon, clat = it["computed_geometry"]["coordinates"]
        image_id = "mapillary_" + hashlib.sha1(str(it["id"]).encode()).hexdigest()[:10]
        dest = OUT / f"{image_id}.jpg"
        try:
            fetch_stripped(it["thumb_2048_url"], dest)
        except Exception as e:
            print(f"download failed: {e}")
            continue

        captured = None
        if it.get("captured_at"):
            captured = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.gmtime(it["captured_at"] / 1000)
            )

        entries.append(
            {
                "id": image_id,
                "source": "mapillary",
                "file": dest.name,
                "truth": {"lat": clat, "lon": clon},
                "context": {
                    "captured_utc": captured,
                    "compass_angle": it.get("compass_angle"),
                },
                "mapillary_id": str(it["id"]),  # attribution, never shown to a model
                "seed_area": name,
            }
        )
        print(f"ok -> {clat:.4f},{clon:.4f}")
        time.sleep(0.4)  # be polite to the API

    manifest = pathlib.Path("data/manifest.json")
    existing = []
    if manifest.exists():
        existing = [e for e in json.loads(manifest.read_text()) if e["source"] != "mapillary"]
    manifest.write_text(json.dumps(existing + entries, indent=2) + "\n")
    print(f"\nwrote {len(entries)} mapillary entries; manifest now {len(existing) + len(entries)} total")
    return 0 if len(entries) >= N_WANTED else 1


if __name__ == "__main__":
    raise SystemExit(main())
