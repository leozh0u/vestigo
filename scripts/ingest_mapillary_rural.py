"""Build the genuinely hard half: rural and small-road street imagery.

The first Mapillary pass sampled 440 m boxes centred on city centres, which
produced tourist districts full of legible shopfronts and made "name the city"
score under a kilometre by construction. That set is kept, relabelled
mapillary_urban, because comparing the two directly measures how much the model
leans on landmarks and readable text.

This pass seeds on rural and small-town roads instead. The box is wider because
rural coverage is sparse, and the point is that there is no nameable landmark to
shortcut to rather than that the box is tight.
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
BOX = 0.05           # ~5.5 km; rural coverage is thin
N_WANTED = 10

# lon, lat on rural or small roads, deliberately away from any city centre.
CANDIDATES = [
    ("se_orebro_farmland",   15.50,  59.30),
    ("fr_burgundy_backroad",  4.20,  47.30),
    ("us_iowa_county",      -93.50,  42.00),
    ("au_victoria_country", 144.20, -37.20),
    ("jp_hokkaido_rural",   142.50,  43.50),
    ("br_sp_interior",      -48.50, -22.50),
    ("za_freestate",         26.50, -28.50),
    ("pl_mazovia_rural",     20.50,  52.80),
    ("es_castilla_meseta",   -4.50,  41.50),
    ("ca_ontario_rural",    -80.50,  43.80),
    ("nz_manawatu",         175.50, -40.00),
    ("th_central_plain",    100.20,  14.80),
    ("cl_maule",            -71.50, -35.00),
    ("fi_lakeland",          25.50,  61.50),
    ("ar_pampas",           -60.50, -34.50),
    ("de_hesse_rural",        9.80,  51.50),
    ("uk_shropshire",        -2.50,  52.30),
    ("no_buskerud",           9.50,  60.50),
    ("mx_guanajuato",      -100.50,  20.50),
    ("in_karnataka_rural",   76.50,  15.50),
]


def token() -> str:
    for line in pathlib.Path(".env").read_text().splitlines():
        if line.startswith("MAPILLARY_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("MAPILLARY_TOKEN missing from .env")


def find_image(tok, lon, lat):
    bbox = f"{lon - BOX},{lat - BOX},{lon + BOX},{lat + BOX}"
    q = urllib.parse.urlencode(
        {"access_token": tok, "fields": FIELDS, "bbox": bbox, "limit": 10}
    )
    try:
        with urllib.request.urlopen(f"{API}?{q}", timeout=60) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"query failed ({type(e).__name__})")
        return None
    if "error" in data:
        print(f"api error: {data['error'].get('message', '')[:50]}")
        return None
    for it in data.get("data", []):
        if (it.get("computed_geometry") or {}).get("coordinates") \
           and not it.get("is_pano") and it.get("thumb_2048_url"):
            return it
    return None


def fetch_stripped(url, dest):
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read()
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata()))
        clean.save(dest, format="JPEG", quality=95)


def main():
    tok = token()
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, lon, lat in CANDIDATES:
        if len(entries) >= N_WANTED:
            break
        print(f"  {name:<24}", end=" ", flush=True)
        it = find_image(tok, lon, lat)
        if not it:
            print("nothing usable")
            continue
        clon, clat = it["computed_geometry"]["coordinates"]
        image_id = "rural_" + hashlib.sha1(str(it["id"]).encode()).hexdigest()[:10]
        dest = OUT / f"{image_id}.jpg"
        try:
            fetch_stripped(it["thumb_2048_url"], dest)
        except Exception as e:
            print(f"download failed ({type(e).__name__})")
            continue
        captured = None
        if it.get("captured_at"):
            captured = time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.gmtime(it["captured_at"] / 1000))
        entries.append({
            "id": image_id, "source": "mapillary_rural", "file": dest.name,
            "truth": {"lat": clat, "lon": clon},
            "context": {"captured_utc": captured,
                        "compass_angle": it.get("compass_angle")},
            "mapillary_id": str(it["id"]), "seed_area": name,
        })
        print(f"ok  {clat:>8.4f},{clon:>9.4f}")
        time.sleep(0.4)

    m = pathlib.Path("data/manifest.json")
    existing = [e for e in json.loads(m.read_text()) if e["source"] != "mapillary_rural"]
    m.write_text(json.dumps(existing + entries, indent=2) + "\n")
    print(f"\n{len(entries)} rural entries; manifest now {len(existing) + len(entries)}")
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
