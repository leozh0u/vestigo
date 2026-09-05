"""Copy traces into the site and write the index it reads.

The site is static: it runs no Python, calls no API, and spends nothing per
visitor. What it plays back are files produced by a real eval run on this
machine, which is the whole reason its numbers can be trusted.

    ./.venv/bin/python eval/harness.py --traces results/traces_v9 ...
    ./.venv/bin/python scripts/build_site_traces.py --from results/traces_v9

The selection is deliberate rather than "the first few". A demo of three
images that all land on a street shows a system that always succeeds, which is
neither true nor the point. What the site is arguing is that it answers at the
granularity the evidence supports, so it needs one that reaches a street, one
that stops at a country, and if there is one, a run that declined outright.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEST = ROOT / "site/public/traces"

# Finest first, so "the best example of a fine answer" is easy to ask for.
LEVELS = ["point", "district", "city", "region", "country", "continent"]


def summarise(path: pathlib.Path) -> dict | None:
    try:
        blob = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    answer = (blob.get("final") or {}).get("answer")
    return {
        "file": path.name,
        "subject": blob.get("subject", path.stem),
        "steps": len(blob.get("steps", [])),
        "level": (answer or {}).get("level"),
        "value": (answer or {}).get("value"),
        "confidence": (answer or {}).get("confidence"),
    }


def choose(rows: list[dict], count: int) -> list[dict]:
    """A deliberate spread, finest to coarsest, ending with a refusal.

    The row of examples is the argument the site is making, so what is in it
    decides what the site says. Four runs that all land on a street show a
    system that always succeeds, which is neither true nor the point.

    What the page claims is that it answers as precisely as the evidence allows
    and stops. Demonstrating that needs the whole ladder: something pinned to a
    building, something that only reaches a city, something that gets no
    further than a country, and at least one where it looked and refused. The
    refusals are the most convincing item in the set and the easiest to leave
    out, because they look like failures in a list of successes.

    One per photograph. The eval runs each image three times, so without this
    the same picture appears three times over as three different results, which
    reads as padding.
    """
    ladder = ["point", "district", "city", "region", "country", "continent"]
    picked: list[dict] = []
    seen_subjects: set[str] = set()

    def take(row: dict) -> None:
        picked.append(row)
        seen_subjects.add(row["subject"])

    # Two from the fine end, then one at each remaining level, so the row opens
    # on the system at its most precise and degrades from there.
    wanted = ["point", "point", "district", "city", "region", "country", "continent"]
    for level in wanted:
        if len(picked) >= count - 2:
            break
        for row in rows:
            if row["level"] == level and row["subject"] not in seen_subjects:
                take(row)
                break

    # Two refusals at the end. Reserved rather than taken if they happen to
    # fit, because they are the item most likely to be squeezed out and the
    # one the page most needs.
    refused = [r for r in rows if r["level"] is None and r["subject"] not in seen_subjects]
    for row in refused[:2]:
        take(row)

    # Top up from anything left, still one per photograph.
    for row in rows:
        if len(picked) >= count:
            break
        if row["subject"] not in seen_subjects:
            take(row)

    # Finest first, refusals last, which is the order the argument reads in.
    def rank(row: dict) -> int:
        return ladder.index(row["level"]) if row["level"] in ladder else len(ladder)

    return sorted(picked[:count], key=rank)


def copy_thumbnail(subject: str) -> str | None:
    """The photograph itself, small enough to sit in a row of four.

    The first version put the answer on the button: "Badshahi Mosque · point",
    before anything had been clicked. That gives away the result of the demo in
    the label of the control that starts it, which is the whole point handed
    over for free. A photograph asks the question instead, and asking the
    question is what the page is for.
    """
    from PIL import Image

    source = next(iter((ROOT / "data/images").glob(f"{subject}*")), None)
    if source is None:
        return None
    thumbs = DEST.parent / "photos"
    thumbs.mkdir(parents=True, exist_ok=True)
    name = f"{subject}.jpg"
    with Image.open(source) as im:
        im = im.convert("RGB")
        # Square, cropped from the middle. A row of mixed aspect ratios reads
        # as a folder of files; a row of squares reads as a set of choices.
        side = min(im.size)
        left = (im.width - side) // 2
        top = (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side)).resize((320, 320),
                                                                  Image.LANCZOS)
        im.save(thumbs / name, quality=82, optimize=True)
    return f"/photos/{name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="source", default="results/traces_v9",
                    help="directory of traces written by eval/harness.py --traces")
    ap.add_argument("--count", type=int, default=9,
                    help="how many examples the site offers. The row is the argument, so it needs the whole ladder and at least one refusal")
    ap.add_argument("--all", action="store_true",
                    help="copy every trace rather than a chosen spread")
    args = ap.parse_args()

    source = ROOT / args.source
    if not source.is_dir():
        raise SystemExit(f"no traces at {source}. Run the harness with --traces first.")

    rows = [r for r in (summarise(p) for p in sorted(source.glob("*.json"))) if r]
    if not rows:
        raise SystemExit(f"no readable traces in {source}")

    picked = rows if args.all else choose(rows, args.count)

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    for row in picked:
        shutil.copy2(source / row["file"], DEST / row["file"])

    index = [{**row, "photo": copy_thumbnail(row["subject"])} for row in picked]
    (DEST / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    print(f"{len(picked)} of {len(rows)} traces -> {DEST.relative_to(ROOT)}")
    for row in index:
        shown = row["photo"] or "no photograph on disk"
        print(f"  {row['subject']:<24} {row['steps']:>3} steps  {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
