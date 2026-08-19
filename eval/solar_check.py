"""Does the solar constraint eliminate the wrong answers and keep the right one?

Phase 1, measured on data already on disk. No model calls and no network. The
eight rural images carry a true capture timestamp and a camera heading in the
manifest, and the three baseline arms left twenty-four guesses across them, so
the guesses become the candidate set and the timestamps become the constraint.

The question is not whether the constraint improves an estimate. It is whether
it removes candidates that are wrong while leaving the best one alone, which is
the only thing this class of evidence can do. Phase 0 measured displacement and
called the Mexico result "within noise" when the model had flipped continents
between identical runs.

Two candidate sets, because they answer different questions.

  guesses    the twenty-four real baseline guesses. Asks whether the constraint
             hurts, and whether it catches the one failure Phase 0 found.

  decoys     each image gets the other seven images' true coordinates as
             candidates alongside its own. Every decoy is a real place with a
             real timestamp, so this asks how much the constraint discriminates
             when the guesses are not already close.

Two readings, on both sets.

  daylight   the only thing used is that the photograph was taken in daylight.
             Nothing else. Deployable now, because day against night is the one
             reading a vision model does not get wrong.

  oracle     daylight, plus the sun's compass bearing read perfectly, taken
             from the ground truth rather than from the image. Not a result, a
             ceiling. It prices a perfect reading of shadow direction, which is
             what decides whether the second half of this tool is worth
             building.

Reported alongside the median: the spread, meaning the furthest two surviving
candidates from each other. Phase 0 measured run-to-run noise at a 40 km median
and a 14,951 km maximum, and said a constraint is measured by what it
eliminates and how much variance it removes rather than by displacement. Spread
is that sentence as a number. The median is kept in the table because watching
it sit still while the spread collapses is the whole argument.

Run:  ./.venv/bin/python eval/solar_check.py
"""
import json
import math
import pathlib
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vestigo.board import Board
from vestigo.geo import LatLon, haversine
from vestigo.scoring import spread_km as _spread
from vestigo.solar import HORIZON_DEG, sun_position
from vestigo.tools.base import attach
from vestigo.tools.solar import SolarTool

ARMS = ("arm_a", "arm_a2", "arm_b")
ELIMINATED = 0.5          # admissibility below this counts as ruled out
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_rural():
    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    images = {e["id"]: e for e in manifest if e["source"] == "mapillary_rural"}
    guesses: dict[str, list[dict]] = {i: [] for i in images}
    for arm in ARMS:
        for row in json.loads((ROOT / f"eval/{arm}.json").read_text()):
            key = row["file"].removesuffix(".jpg")
            if key in guesses:
                guesses[key].append({**row, "arm": arm})
    return images, guesses


def candidates_for(entry, rows):
    """Distinct guesses, nearest first, labelled by which arms produced them."""
    truth = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
    seen: dict[tuple[float, float], dict] = {}
    for row in rows:
        key = (round(row["lat"], 3), round(row["lon"], 3))
        if key in seen:
            seen[key]["arms"].append(row["arm"])
            continue
        point = LatLon(row["lat"], row["lon"])
        seen[key] = {"point": point, "arms": [row["arm"]],
                     "error_km": haversine(truth, point),
                     "country": row.get("country", "")}
    return sorted(seen.values(), key=lambda c: c["error_km"])


def sun_relative_from_truth(entry) -> str | None:
    """What a perfect reading of the sun's direction would have said.

    Ground truth in, so this is an oracle and never a result. It exists to
    price the second half of the tool before any of it is paid for.
    """
    heading = entry["context"].get("compass_angle")
    if heading is None:
        return None
    truth = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
    when = parse(entry["context"]["captured_utc"])
    sun = sun_position(truth, when)
    if not sun.is_daylight:
        return None
    offset = (sun.azimuth_deg - heading + 180.0) % 360.0 - 180.0
    if -45 <= offset < 45:
        return "front"
    if 45 <= offset < 135:
        return "right"
    if -135 <= offset < -45:
        return "left"
    return "back"


def parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def daylit_fraction(when: datetime, step: float = 2.0) -> float:
    """Share of the earth's surface in daylight at one instant.

    Area weighted by cos(latitude), since a two degree cell near a pole holds
    far less surface than one at the equator. This is what the daylight
    constraint removes before anything else is known.
    """
    lit = total = 0.0
    lat = -89.0
    while lat <= 89.0:
        w = math.cos(math.radians(lat))
        lon = -180.0
        while lon < 180.0:
            total += w
            if sun_position(LatLon(lat, lon), when).elevation_deg > HORIZON_DEG:
                lit += w
            lon += step
        lat += step
    return lit / total


def decoys_for(iid, images):
    """The other images' true coordinates, as candidates for this one.

    Real places at real instants, which is what makes this a fair test rather
    than a set of coordinates chosen to be easy to reject.
    """
    truth = LatLon(images[iid]["truth"]["lat"], images[iid]["truth"]["lon"])
    out = [{"point": truth, "arms": ["truth"], "error_km": 0.0, "country": "truth"}]
    for other, entry in images.items():
        if other == iid:
            continue
        point = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
        out.append({"point": point, "arms": ["decoy"], "country": "decoy",
                    "error_km": haversine(truth, point)})
    return sorted(out, key=lambda c: c["error_km"])


def run_condition(entry, cands, oracle: bool) -> dict:
    """Build a board, apply the solar tool, and score every candidate."""
    board = Board(entry["id"])
    kwargs = {"captured_utc": entry["context"]["captured_utc"], "lighting": "daylight"}
    if oracle:
        relative = sun_relative_from_truth(entry)
        heading = entry["context"].get("compass_angle")
        if relative and heading is not None:
            kwargs |= {"sun_relative": relative, "camera_heading_deg": heading}
    attach(board, SolarTool()(**kwargs))
    for c in cands:
        board.add_candidate(c["point"], label=c["country"], prior=1.0 / len(cands))
    scored = board.rank_candidates()
    by_point = {(round(s.point.lat, 3), round(s.point.lon, 3)): s for s in scored}
    for c in cands:
        c["adm"] = by_point[(round(c["point"].lat, 3), round(c["point"].lon, 3))].admissibility
    return {"kwargs": kwargs, "cands": cands}


def spread_km(cands, survivors_only: bool = True) -> float:
    """Furthest two surviving candidates from each other, in km.

    The number a constraint is supposed to move, and the median is the number
    it is not. `vestigo.scoring.spread_km` does the geometry; this only picks
    which candidates are still standing.
    """
    return _spread([c["point"] for c in cands
                    if not survivors_only or c["adm"] >= ELIMINATED])


def weighted_median_error(cands) -> float:
    """Median error of the candidate set, weighted by what survived.

    A constraint that removes only wrong candidates pulls this down without
    ever having proposed a location.
    """
    total = sum(c["adm"] for c in cands)
    if total <= 0:
        return statistics.median([c["error_km"] for c in cands])
    target, run = total / 2, 0.0
    for c in sorted(cands, key=lambda c: c["error_km"]):
        run += c["adm"]
        if run >= target:
            return c["error_km"]
    return cands[-1]["error_km"]


def report(images, sets, oracle: bool, title: str) -> None:
    print("=" * 79)
    print(title)
    print("=" * 79)
    print(f"{'image':<18}{'cands':>6}{'ruled out':>11}{'median km':>11}"
          f"{'spread before':>15}{'spread after':>14}")
    print("-" * 79)

    kept_best = 0
    cut_errors, kept_errors = [], []
    before_all, after_all, med_all = [], [], []
    total = 0
    for iid, entry in images.items():
        cands = sets[iid]
        run_condition(entry, cands, oracle)
        cut = [c for c in cands if c["adm"] < ELIMINATED]
        before = spread_km(cands, survivors_only=False)
        after = spread_km(cands)
        if cands[0]["adm"] >= ELIMINATED:
            kept_best += 1
        cut_errors += [c["error_km"] for c in cut]
        kept_errors += [c["error_km"] for c in cands if c["adm"] >= ELIMINATED]
        med = weighted_median_error(cands)
        before_all.append(before)
        after_all.append(after)
        med_all.append(med)
        total += len(cands)
        print(f"{iid:<18}{len(cands):>6}{len(cut):>11}{med:>11.0f}"
              f"{before:>15.0f}{after:>14.0f}")

    print("-" * 79)
    print(f"  candidates {total}, ruled out {len(cut_errors)}, kept {len(kept_errors)}")
    print(f"  best candidate survived on {kept_best}/{len(images)} images"
          + ("" if kept_best == len(images) else "   <-- the constraint cut the truth"))
    if cut_errors:
        print(f"  median error of what was ruled out: {statistics.median(cut_errors):>9.0f} km")
    if kept_errors:
        print(f"  median error of what was kept:      {statistics.median(kept_errors):>9.0f} km")
    print(f"  median spread: {statistics.median(before_all):.0f} km"
          f" -> {statistics.median(after_all):.0f} km")
    print(f"  worst spread:  {max(before_all):.0f} km -> {max(after_all):.0f} km")
    print(f"  median error over the set: {statistics.median(med_all):.0f} km\n")


def main():
    images, guesses = load_rural()
    print("Sun at ground truth, from the capture timestamp in the manifest\n")
    print(f"{'image':<18}{'country':<16}{'utc':<21}{'elev':>7}{'bearing':>9}")
    print("-" * 71)
    for iid, entry in images.items():
        truth = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
        sun = sun_position(truth, parse(entry["context"]["captured_utc"]))
        country = guesses[iid][0].get("country", "") if guesses[iid] else ""
        print(f"{iid:<18}{country:<16}{entry['context']['captured_utc']:<21}"
              f"{sun.elevation_deg:>6.1f} {sun.azimuth_deg:>8.0f}")

    lit = [sun_position(LatLon(e["truth"]["lat"], e["truth"]["lon"]),
                        parse(e["context"]["captured_utc"])).elevation_deg
           for e in images.values()]
    print(f"\nAll {len(lit)} are above the horizon at ground truth, so 'daylight' is the "
          f"correct reading\nfor every one. The lowest is {min(lit):.1f} degrees, close "
          "enough to sunset that a model\ncould reasonably have said twilight instead.")

    sample = parse(next(iter(images.values()))["context"]["captured_utc"])
    print(f"\nShare of the earth in daylight at one instant, area weighted: "
          f"{daylit_fraction(sample):.1%}\n")

    for oracle in (False, True):
        reading = "daylight plus a perfect reading of sun direction (a ceiling, not a result)" \
            if oracle else "daylight only, the one reading a vision model does not get wrong"
        report(images,
               {i: candidates_for(images[i], guesses[i]) for i in images},
               oracle, f"BASELINE GUESSES: {reading}")
        report(images,
               {i: decoys_for(i, images) for i in images},
               oracle, f"DECOYS: {reading}")


if __name__ == "__main__":
    main()
