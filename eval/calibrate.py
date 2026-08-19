"""The headline metric, computed on the Phase 0 data for the first time.

The project's claim is that it answers at the granularity the evidence supports
and stops, which makes calibration the thing to measure and distance error a
supporting number. Every result so far has been distance error, because nothing
scored granularity. This does.

Three questions, in order.

  1. How often is a claim correct at the level it was made at, as opposed to
     within some fixed radius that has nothing to do with what was claimed.
  2. How often does the system claim finer than it earned. That is the failure
     to drive to zero, and it is not the same as being inaccurate.
  3. When it says high confidence, how often is it right.

Then variance, on the rural set, where three runs exist per image.

Run:  ./.venv/bin/python eval/calibrate.py
"""
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vestigo.geo import LatLon
from vestigo.scoring import (
    LEVEL_RADIUS_KM,
    report,
    score,
    summarise_repeats,
    worst_overshoot,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ("im2gps", "mapillary_urban", "mapillary_rural")
ARMS = ("arm_a", "arm_a2", "arm_b")


def load(arm):
    return {r["file"].removesuffix(".jpg"): r
            for r in json.loads((ROOT / f"eval/{arm}.json").read_text())}


def truth_map():
    return {e["id"]: e for e in json.loads((ROOT / "data/manifest.json").read_text())}


def scored_for(arm, truths):
    rows = []
    for key, guess in load(arm).items():
        entry = truths[key]
        rows.append(score(
            subject=key,
            claimed=guess["granularity"],
            guess=LatLon(guess["lat"], guess["lon"]),
            truth=LatLon(entry["truth"]["lat"], entry["truth"]["lon"]),
            confidence=guess.get("confidence"),
            source=entry["source"],
        ))
    return rows


def print_bins(bins):
    print(f"  {'stated':<9}{'n':>4}{'promised':>10}{'observed':>10}"
          f"{'gap':>8}{'median km':>11}{'worst km':>10}")
    for b in bins:
        if b.gap > 0.15:
            note = "   overconfident"
        elif b.gap < -0.15:
            note = "   underconfident"
        else:
            note = ""
        print(f"  {b.label:<9}{b.n:>4}{b.stated:>10.0%}{b.observed:>10.0%}"
              f"{b.gap:>+8.0%}{b.median_error_km:>11.1f}{b.worst_error_km:>10.0f}"
              f"{note}")


def main():
    truths = truth_map()
    rows = scored_for("arm_a", truths)

    print("Granularity-aware scoring, arm A, all 28 images")
    print("A claim counts as correct if the truth falls inside the radius its")
    print("level implies. The radii are the standard IM2GPS bands.\n")
    print(f"  {'level':<11}{'radius km':>11}")
    for level, radius in sorted(LEVEL_RADIUS_KM.items()):
        print(f"  {level.label:<11}{radius:>11.0f}")

    print("\n" + "=" * 78)
    print("CORRECT AT THE LEVEL CLAIMED, by source")
    print("=" * 78)
    print(f"{'source':<18}{'n':>4}{'correct':>10}{'overclaimed':>13}"
          f"{'underclaimed':>14}{'median km':>11}")
    print("-" * 78)
    for src in SOURCES:
        sub = [r for r in rows if r.source == src]
        if not sub:
            continue
        rep = report(sub)
        print(f"{src:<18}{rep.n:>4}{rep.hit_rate:>10.0%}{rep.overclaim_rate:>13.0%}"
              f"{rep.underclaim_rate:>14.0%}{rep.median_error_km:>11.1f}")
    overall = report(rows)
    print("-" * 78)
    print(f"{'all':<18}{overall.n:>4}{overall.hit_rate:>10.0%}"
          f"{overall.overclaim_rate:>13.0%}{overall.underclaim_rate:>14.0%}"
          f"{overall.median_error_km:>11.1f}")

    print("\nWhat the two metrics disagree about:")
    for r in sorted(rows, key=lambda r: -r.error_km):
        if r.hit and r.error_km > 25:
            print(f"  {r.subject:<20} claimed {r.claimed.label:<9} "
                  f"{r.error_km:>7.0f} km   correct, and a failure by distance")
    for r in sorted(rows, key=lambda r: r.error_km):
        if not r.hit and r.error_km < 25:
            print(f"  {r.subject:<20} claimed {r.claimed.label:<9} "
                  f"{r.error_km:>7.1f} km   close, and still an overclaim")

    print("\n" + "=" * 78)
    print("CALIBRATION: when it says this, how often is it right")
    print("=" * 78)
    print_bins(overall.bins)
    print(f"\n  expected calibration error {overall.ece:.0%}")
    print("  The promised column is a reading of the words, not a measurement.")
    print("  Phase 5 replaces it with values fitted to this curve.\n")

    print("  Worst broken promise in each band, as a multiple of the radius the")
    print("  claimed level allows. At or below 1.0 the band kept its promise.")
    print("  Phase 0 found medium bimodal from 0.1 km to 1545 km, measured by")
    print("  distance. Measured against what each answer actually claimed:")
    for b in overall.bins:
        group = [r for r in rows if r.confidence == b.label]
        factor = worst_overshoot(group)
        flag = "   <-- broke its claim" if factor > 1.0 else "   kept its claim"
        print(f"    {b.label:<9}{factor:>7.1f}x{flag}")

    print("\n" + "=" * 78)
    print("VARIANCE: three runs on the eight rural images")
    print("=" * 78)
    per_arm = {arm: {r.subject: r for r in scored_for(arm, truths)} for arm in ARMS}
    guesses = {arm: load(arm) for arm in ARMS}
    rural = [k for k, e in truths.items() if e["source"] == "mapillary_rural"]

    print(f"{'image':<20}{'runs':>5}{'median km':>11}{'best':>8}{'worst':>9}"
          f"{'spread':>9}{'correct':>9}  stable")
    print("-" * 78)
    summaries = []
    for key in rural:
        runs = [per_arm[a][key] for a in ARMS if key in per_arm[a]]
        points = [LatLon(guesses[a][key]["lat"], guesses[a][key]["lon"])
                  for a in ARMS if key in guesses[a]]
        s = summarise_repeats(key, runs, points)
        summaries.append(s)
        print(f"{key:<20}{s.n:>5}{s.median_error_km:>11.0f}{s.best_error_km:>8.0f}"
              f"{s.worst_error_km:>9.0f}{s.spread_km:>9.0f}{s.hit_rate:>9.0%}"
              f"  {'yes' if s.stable else 'no'}")
    print("-" * 78)
    spreads = [s.spread_km for s in summaries]
    print(f"  median spread {statistics.median(spreads):.0f} km, "
          f"worst {max(spreads):.0f} km")
    print(f"  images whose runs agree closely enough to read as one answer: "
          f"{sum(1 for s in summaries if s.stable)}/{len(summaries)}")
    print("\n  A single-sample eval reports one column of this table and cannot")
    print("  tell an improvement from a reroll.")


if __name__ == "__main__":
    main()
