"""Build the IM2GPS half of the baseline set.

Ground truth for this dataset lives in the JPEG COM (comment) markers, not in
EXIF -- the original MATLAB evaluation script reads Comment{9} and Comment{10}
and takes the second whitespace-separated token of each. Every comment line is
a C string followed by buffer garbage from whatever tool wrote the files, so the
real value ends at the first NUL byte -- Python's str.split() does not treat NUL
as whitespace, MATLAB's imfinfo truncates there for free. Cutting at the NUL is
load-bearing, not cosmetic.

Three things leak the answer and all three are removed before a model sees the
image: the COM markers, any EXIF, and the filename (many are of the form
"wales_00004_...jpg").
"""
import hashlib
import json
import pathlib
import random
import sys

from PIL import Image

RAW = pathlib.Path("data/raw/im2gps")
OUT = pathlib.Path("data/images")
SEED = 20260811
N = 10


def com_segments(path: pathlib.Path) -> list[str]:
    """Every JPEG COM segment payload, in file order."""
    b = path.read_bytes()
    out, i = [], 2  # skip SOI
    while i < len(b) - 1:
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:  # start of scan; metadata is done
            break
        seg_len = int.from_bytes(b[i + 2 : i + 4], "big")
        if marker == 0xFE:
            out.append(b[i + 4 : i + 2 + seg_len].decode("utf-8", "replace"))
        i += 2 + seg_len
    return out


def parse(path: pathlib.Path) -> dict | None:
    """Pull ground truth and capture time out of the comment block."""
    fields = {}
    for seg in com_segments(path):
        key, _, rest = seg.partition(":")
        # Value ends at the first NUL; everything after is buffer garbage.
        fields.setdefault(key.strip().lower(), rest.split("\x00")[0].strip())

    try:
        lat = float(fields["latitude"].split()[0])
        lon = float(fields["longitude"].split()[0])
    except (KeyError, ValueError, IndexError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:  # null island, i.e. missing
        return None

    taken = None
    raw_taken = fields.get("datetaken", "")
    parts = raw_taken.split()
    if len(parts) >= 2 and parts[0].count("-") == 2:
        taken = f"{parts[0]} {parts[1]}"

    return {"lat": lat, "lon": lon, "captured_local": taken}


def strip_and_save(src: pathlib.Path, dest: pathlib.Path) -> None:
    """Re-encode pixels only. Drops EXIF, COM markers, and every other tag."""
    with Image.open(src) as im:
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata()))
        clean.save(dest, format="JPEG", quality=95)


def main() -> int:
    files = sorted(RAW.glob("*.jpg"))
    if not files:
        print(f"no images under {RAW}", file=sys.stderr)
        return 1

    usable = []
    for f in files:
        rec = parse(f)
        if rec:
            usable.append((f, rec))
    print(f"{len(usable)}/{len(files)} images have usable ground truth")

    random.Random(SEED).shuffle(usable)
    chosen = usable[:N]

    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for src, rec in chosen:
        # Opaque id: the filename itself often names the region.
        image_id = "im2gps_" + hashlib.sha1(src.name.encode()).hexdigest()[:10]
        dest = OUT / f"{image_id}.jpg"
        strip_and_save(src, dest)
        entries.append(
            {
                "id": image_id,
                "source": "im2gps",
                "file": dest.name,
                "truth": {"lat": rec["lat"], "lon": rec["lon"]},
                "context": {"captured_local": rec["captured_local"]},
                "original_name": src.name,  # for my own auditing, never shown to a model
            }
        )

    manifest = pathlib.Path("data/manifest.json")
    existing = []
    if manifest.exists():
        existing = [e for e in json.loads(manifest.read_text()) if e["source"] != "im2gps"]
    manifest.write_text(json.dumps(existing + entries, indent=2) + "\n")
    print(f"wrote {len(entries)} entries to {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
