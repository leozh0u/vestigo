"""Run the agent over the dataset and score what comes back.

This is the piece the project is for. Everything else measures one part; this
runs the whole thing and reports it the way the design asks to be judged:
correct at the level claimed, calibrated, and stable across repeats.

Three things it will not let you skip.

Every image is sampled more than once. Run-to-run noise on this data is a 40 km
median with a 14,951 km tail, so a single sample reports a median that moves on
rerun and cannot separate an improvement from a reroll. The default is three.

Results are broken out by source and never pooled. The Flickr half is
landmark-heavy and probably memorised, the city-centre half is easy by
construction, and the rural half is the case the project is actually for. One
number over all three says nothing.

Cost is reported per step. If the extractor is eating the budget, that shows up
here rather than on a statement.

    ./.venv/bin/python eval/harness.py --dry              # no key, no spend
    ./.venv/bin/python eval/harness.py --preset cheap --limit 2.00
    ./.venv/bin/python eval/harness.py --source mapillary_rural --samples 5
"""
import argparse
import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vestigo.agent import Agent
from vestigo.geo import LatLon
from vestigo.llm import Budget, BudgetExceeded, Router
from vestigo.scoring import (
    Scored,
    calibration_curve,
    report,
    summarise_repeats,
    worst_overshoot,
)
from vestigo.tools.base import Registry
from vestigo.tools.solar import SolarTool

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ("im2gps", "mapillary_urban", "mapillary_rural")


def load_manifest(source: str | None, limit: int | None):
    rows = json.loads((ROOT / "data/manifest.json").read_text())
    if source:
        rows = [r for r in rows if r["source"] == source]
    return rows[:limit] if limit else rows


def context_for(entry: dict) -> str:
    """Only what actually shipped with the photograph.

    Writing plausible context by hand would measure the writer rather than the
    system, which is the reason arm B was built the way it was.
    """
    ctx = entry.get("context", {})
    bits = []
    if ctx.get("captured_utc"):
        bits.append(f"Captured {ctx['captured_utc']} UTC.")
    if ctx.get("captured_local"):
        bits.append(f"Captured {ctx['captured_local']} local time.")
    if ctx.get("compass_angle") is not None:
        bits.append(f"Camera heading {ctx['compass_angle']:.0f} degrees.")
    return " ".join(bits)


def dry_router(budget: Budget) -> Router:
    """A scripted provider, so the whole pipeline can be exercised with no key.

    Worth having beyond convenience: it means a change to the harness can be
    checked before spending anything on finding out it was wrong.
    """
    from vestigo.providers import FakeProvider
    from vestigo.llm import Completion, Usage

    def script():
        return [
            {"observations": [
                {"modality": "road", "what": "unmarked asphalt", "certainty": 0.9,
                 "region": {"x0": 0.0, "y0": 0.6, "x1": 1.0, "y1": 1.0}},
                {"modality": "vegetation", "what": "dry scrub", "certainty": 0.7,
                 "region": {"x0": 0.1, "y0": 0.4, "x1": 0.4, "y1": 0.8}},
            ]},
            {"lat": 20.0, "lon": -100.0, "place": "somewhere dry",
             "granularity": "country", "confidence": "medium",
             "reasoning": "scripted, not a real reading"},
            Completion("no tool would narrow this", "fake-1",
                       Usage(50, 10, model="claude-sonnet-5")),
            {"claims": [{"level": "country", "value": "scripted", "confidence": "medium",
                         "supports": [{"evidence_id": "e1", "strength": 0.7}]}]},
        ]

    return Router(FakeProvider(script() * 200, model="claude-sonnet-5", budget=budget))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="cheap",
                    help="cheap, quality, local or kimi. See vestigo/config.py")
    ap.add_argument("--limit", type=float, default=2.0,
                    help="budget ceiling in dollars. The run stops rather than passing it")
    ap.add_argument("--samples", type=int, default=3,
                    help="runs per image. Below 3 the variance figures mean little")
    ap.add_argument("--source", choices=SOURCES, help="one source only")
    ap.add_argument("--max-images", type=int)
    ap.add_argument("--batched", action="store_true",
                    help="half price, and nothing is waiting on an eval")
    ap.add_argument("--dry", action="store_true",
                    help="scripted replies, no key and no spend")
    ap.add_argument("--out", default="results/agent_runs.json")
    args = ap.parse_args()

    if args.samples < 2:
        print("warning: below 2 samples the spread column is meaningless, and a "
              "median that moves 40 km on rerun will look like a result.\n")

    if args.dry:
        budget = Budget(None, allow_unpriced=True)
        router = dry_router(budget)
    else:
        from vestigo.config import build
        router, budget = build(args.preset, limit_usd=args.limit, batched=args.batched)

    agent = Agent(router, tools=Registry([SolarTool()]), budget=budget)
    entries = load_manifest(args.source, args.max_images)
    missing = [e for e in entries if not (ROOT / "data/images" / e["file"]).exists()]
    if missing:
        print(f"{len(missing)} images are not on disk. Run the ingest scripts first.")
        entries = [e for e in entries if e not in missing]
    if not entries:
        print("nothing to run")
        return 1

    print(f"{len(entries)} images, {args.samples} samples each, "
          f"{len(entries) * args.samples} runs, preset {args.preset}"
          f"{' (dry)' if args.dry else ''}\n")
    if args.dry:
        print("DRY RUN. The replies are scripted, so every accuracy figure below "
              "is meaningless.\nWhat is real is the plumbing and the cost "
              "accounting.\n")

    scored: list[Scored] = []
    summaries = []
    declined = 0
    records = []

    for entry in entries:
        path = ROOT / "data/images" / entry["file"]
        truth = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
        runs, rows, points = [], [], []
        try:
            runs = agent.run_samples(path, n=args.samples, subject=entry["id"],
                                     context=context_for(entry))
        except BudgetExceeded as exc:
            print(f"\nstopped: {exc}")
            break

        for run in runs:
            if run.answer is None or run.best_point is None:
                declined += 1
                continue
            row = Scored(
                subject=entry["id"],
                claimed=run.answer.level,
                error_km=truth.distance_km(run.best_point),
                confidence=run.answer.stated_confidence,
                source=entry["source"],
            )
            rows.append(row)
            points.append(run.best_point)
            scored.append(row)
            records.append({
                "id": entry["id"], "source": entry["source"],
                "claim": run.answer.value, "level": run.answer.level.label,
                "confidence": run.answer.stated_confidence,
                "lat": run.best_point.lat, "lon": run.best_point.lon,
                "error_km": row.error_km, "cost_usd": run.cost_usd,
                "rejected": run.rejected,
            })

        if rows:
            summary = summarise_repeats(entry["id"], rows, points)
            summaries.append(summary)
            print(f"{entry['id']:<20}{entry['source']:<17}"
                  f"{summary.median_error_km:>9.1f} km  spread {summary.spread_km:>8.0f} km"
                  f"  {summary.hit_rate:>4.0%} correct  {'' if summary.stable else 'unstable'}")

    if not scored:
        print("\nno scorable runs")
        return 1

    print("\n" + "=" * 78)
    print("CORRECT AT THE LEVEL CLAIMED, by source")
    print("=" * 78)
    print(f"{'source':<18}{'n':>4}{'correct':>10}{'overclaimed':>13}"
          f"{'underclaimed':>14}{'median km':>11}")
    print("-" * 78)
    for src in SOURCES:
        sub = [s for s in scored if s.source == src]
        if sub:
            rep = report(sub)
            print(f"{src:<18}{rep.n:>4}{rep.hit_rate:>10.0%}{rep.overclaim_rate:>13.0%}"
                  f"{rep.underclaim_rate:>14.0%}{rep.median_error_km:>11.1f}")
    overall = report(scored)
    print("-" * 78)
    print(f"{'all':<18}{overall.n:>4}{overall.hit_rate:>10.0%}"
          f"{overall.overclaim_rate:>13.0%}{overall.underclaim_rate:>14.0%}"
          f"{overall.median_error_km:>11.1f}")
    if declined:
        print(f"\n  {declined} runs made no claim at all. Not counted above, and not a "
              "failure:\n  declining to answer is the design working. Watch it for drift.")

    print("\n" + "=" * 78)
    print("CALIBRATION")
    print("=" * 78)
    print(f"  {'stated':<9}{'n':>4}{'promised':>10}{'observed':>10}{'gap':>8}"
          f"{'median km':>11}{'worst':>9}{'worst claim broken':>21}")
    for b in calibration_curve(scored):
        group = [s for s in scored if s.confidence == b.label]
        print(f"  {b.label:<9}{b.n:>4}{b.stated:>10.0%}{b.observed:>10.0%}"
              f"{b.gap:>+8.0%}{b.median_error_km:>11.1f}{b.worst_error_km:>9.0f}"
              f"{worst_overshoot(group):>20.1f}x")
    print(f"\n  expected calibration error {overall.ece:.0%}")

    if summaries:
        spreads = [s.spread_km for s in summaries]
        stable = sum(1 for s in summaries if s.stable)
        print("\n" + "=" * 78)
        print("VARIANCE")
        print("=" * 78)
        print(f"  median spread {statistics.median(spreads):.0f} km, "
              f"worst {max(spreads):.0f} km")
        print(f"  images whose samples agree closely enough to read as one answer: "
              f"{stable}/{len(summaries)}")

    print("\n" + "=" * 78)
    print("COST")
    print("=" * 78)
    print(f"  {budget.summary()}")
    for label, spend in budget.by_label().items():
        print(f"    {label:<12}${spend:>9.4f}")
    if scored:
        print(f"  per image ${budget.spent_usd / max(1, len(summaries)):.4f}, "
              f"per run ${budget.spent_usd / len(scored):.4f}")
    for provider in router.providers():
        if provider.cache:
            print(f"  cache hit rate {provider.cache.hit_rate:.0%} "
                  f"({provider.cache.hits} hits, {provider.cache.misses} misses)")
            break

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "ran_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "preset": args.preset, "samples": args.samples, "dry": args.dry,
        "spent_usd": budget.spent_usd, "runs": records,
    }, indent=2) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
