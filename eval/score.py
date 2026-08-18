"""Score baseline guesses against held-back ground truth.

Reports median great-circle error and the standard IM2GPS threshold bands,
broken out by source. Never pooled: the whole point of the two-source split is
that a strong score on the Flickr half may be recall rather than reasoning, and
pooling would hide exactly that.
"""
import json
import math
import pathlib
import sys
from collections import Counter

BANDS = [1, 25, 200, 750, 2500]


def haversine(a_lat, a_lon, b_lat, b_lon):
    """Great-circle distance in km."""
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def report(name, rows):
    if not rows:
        return
    errs = [r["error_km"] for r in rows]
    print(f"\n{name}  (n={len(rows)})")
    print(f"  median error   {median(errs):>10.1f} km")
    print(f"  mean error     {sum(errs)/len(errs):>10.1f} km")
    print("  within:", "  ".join(
        f"{b}km {100*sum(1 for e in errs if e <= b)/len(errs):.0f}%" for b in BANDS
    ))
    conf = Counter(r["confidence"] for r in rows)
    print("  confidence:", dict(conf))
    # Calibration sanity: is high confidence actually more accurate?
    for level in ("high", "medium", "low"):
        sub = [r["error_km"] for r in rows if r["confidence"] == level]
        if sub:
            print(f"    {level:<7} n={len(sub)}  median {median(sub):>8.1f} km")


def main(guess_path):
    truth = {e["file"]: e for e in json.loads(pathlib.Path("data/manifest.json").read_text())}
    guesses = json.loads(pathlib.Path(guess_path).read_text())

    rows = []
    for g in guesses:
        t = truth[g["file"]]
        err = haversine(t["truth"]["lat"], t["truth"]["lon"], g["lat"], g["lon"])
        rows.append({**g, "source": t["source"], "error_km": err,
                     "truth_lat": t["truth"]["lat"], "truth_lon": t["truth"]["lon"]})

    rows.sort(key=lambda r: r["error_km"])
    print(f"{'file':<26} {'source':<10} {'err km':>10}  {'conf':<7} guess")
    print("-" * 88)
    for r in rows:
        print(f"{r['file']:<26} {r['source']:<10} {r['error_km']:>10.1f}  "
              f"{r['confidence']:<7} {r['country']}")

    for src in ("im2gps", "mapillary"):
        report(src.upper(), [r for r in rows if r["source"] == src])
    report("POOLED (reported only for completeness)", rows)

    out = pathlib.Path("results") / (pathlib.Path(guess_path).stem + "_scored.json")
    out.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "eval/arm_a.json")
