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
    """One example per level, finest first, then a declined run if there is one.

    Spreading across levels is the argument the site is making. Three examples
    that all land on a street would show a system that always succeeds, which
    is both untrue and the opposite of the point.
    """
    picked: list[dict] = []
    seen_levels: set[str] = set()
    for level in LEVELS:
        for row in rows:
            if row["level"] == level and level not in seen_levels:
                picked.append(row)
                seen_levels.add(level)
                break
        if len(picked) >= count:
            break

    declined = [r for r in rows if r["level"] is None]
    if declined and len(picked) < count:
        picked.append(declined[0])

    for row in rows:                       # top up if the set was thin
        if len(picked) >= count:
            break
        if row not in picked:
            picked.append(row)
    return picked[:count]


def label(row: dict) -> str:
    """Short enough that four of them stay on one line.

    A model writes these values and some run long: "Mediterranean coastal
    region (Adriatic coast)" is an honest answer and a terrible button. The
    first clause is almost always the name.
    """
    if row["level"] is None:
        return "declined"
    name = str(row["value"]).split("(")[0].split(",")[0].strip()
    if len(name) > 22:
        name = name[:21].rstrip() + "\u2026"
    return f"{name} · {row['level']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="source", default="results/traces_v9",
                    help="directory of traces written by eval/harness.py --traces")
    ap.add_argument("--count", type=int, default=4,
                    help="how many examples the site offers")
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

    index = [{**row, "label": label(row)} for row in picked]
    (DEST / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    print(f"{len(picked)} of {len(rows)} traces -> {DEST.relative_to(ROOT)}")
    for row in index:
        print(f"  {row['label']:<40} {row['steps']:>3} steps  {row['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
