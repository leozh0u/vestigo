"""Fetch the CC0 assets used by the offline opening scene, with checksums."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "media" / "continuous"
ASSETS = ROOT / "assets"
LOCK = Path(__file__).with_name("scene-assets.json")
TEXTURES = ["brown_brick_02", "red_brick_03", "old_wood_floor", "plastered_wall_02", "oak_veneer_01"]
MODELS = ["desk_lamp_arm_01", "potted_plant_02",
          "painted_wooden_chair_01", "wooden_bookshelf_worn",
          "vintage_day_bed", "throw_pillows_01", "decorative_book_set_01"]


def read_url(url):
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Vestigo-local-render/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def metadata(name):
    path = ROOT / f"{name}.json"
    if not path.exists():
        path.write_bytes(read_url(f"https://api.polyhaven.com/files/{name}"))
    return json.loads(path.read_text())


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        records = json.loads(LOCK.read_text())
        for record in records:
            path = ROOT / record["path"]
            if path.exists() and hashlib.md5(path.read_bytes()).hexdigest() == record["md5"]:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            body = read_url(record["url"])
            if hashlib.md5(body).hexdigest() != record["md5"]:
                raise ValueError(f"Checksum mismatch: {path}")
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(body)
            temporary.replace(path)
        (ROOT / "asset-downloads.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"Verified {len(records)} locked assets")
        return
    jobs = []
    for name in TEXTURES:
        data = metadata(name)
        for kind in ["Diffuse", "nor_gl", "Rough", "Displacement"]:
            formats = data[kind]["2k"]
            ext = "jpg" if "jpg" in formats else next(iter(formats))
            jobs.append((ASSETS / name / f"{kind}.{ext}", formats[ext], name))
    for name in MODELS:
        data = metadata(name)["blend"]["2k"]["blend"]
        jobs.append((ASSETS / name / f"{name}.blend", data, name))
        jobs.extend((ASSETS / name / relative, info, name)
                    for relative, info in data.get("include", {}).items())
    formats = metadata("urban_courtyard_02")["hdri"]["1k"]
    ext = "hdr" if "hdr" in formats else next(iter(formats))
    jobs.append((ASSETS / f"courtyard.{ext}", formats[ext], "urban_courtyard_02"))

    def download(job):
        path, info, name = job
        path.parent.mkdir(parents=True, exist_ok=True)
        valid = path.exists() and hashlib.md5(path.read_bytes()).hexdigest() == info["md5"]
        if not valid:
            body = read_url(info["url"])
            if hashlib.md5(body).hexdigest() != info["md5"]:
                raise ValueError(f"Checksum mismatch: {path}")
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(body)
            temporary.replace(path)
        return {"path": str(path.relative_to(ROOT)), "url": info["url"],
                "md5": info["md5"], "bytes": path.stat().st_size,
                "license": "CC0", "source": f"https://polyhaven.com/a/{name}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(download, jobs))
    (ROOT / "asset-downloads.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Verified {len(records)} files, {sum(r['bytes'] for r in records)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
