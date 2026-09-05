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
import concurrent.futures
import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vestigo.agent import Agent
from vestigo.geo import LatLon
from vestigo.ledger import Ledger
from vestigo.llm import Budget, BudgetExceeded, Router
from vestigo.scoring import (
    Scored,
    calibration_curve,
    report,
    summarise_repeats,
    worst_overshoot,
)
from vestigo.board import EvidenceKind
from vestigo.tools.base import Registry
from vestigo.consensus import consense
from vestigo.trace import write_trace
from vestigo.tools.gazetteer import PlaceLookup
from vestigo.tools.geocell import GeocellTool
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
    """A scripted provider, so the whole pipeline runs with no key and no spend.

    Dispatches on the shape of the request rather than on call order. A
    positional script cannot survive images being handled in parallel, because
    two threads popping from one list get each other's replies. Answering by
    what was asked for is both thread safe and closer to how a real model
    behaves.

    Worth having beyond convenience: a change to the harness can be checked
    before spending anything on finding out it was wrong.
    """
    from vestigo.agent import CLAIM_SCHEMA, GUESS_SCHEMA
    from vestigo.llm import Completion, Provider, Usage
    from vestigo.observe import OBSERVATION_SCHEMA

    class Scripted(Provider):
        name = "scripted"
        default_model = "scripted-1"

        def _send(self, request, model):
            usage = Usage(200, 60, model="claude-sonnet-5")
            if request.schema is OBSERVATION_SCHEMA:
                answer = {"observations": [
                    {"modality": "road", "what": "unmarked asphalt", "certainty": 0.9,
                     "region": {"x0": 0.0, "y0": 0.6, "x1": 1.0, "y1": 1.0}},
                    {"modality": "vegetation", "what": "dry scrub", "certainty": 0.7,
                     "region": {"x0": 0.1, "y0": 0.4, "x1": 0.4, "y1": 0.8}},
                ]}
            elif request.schema is GUESS_SCHEMA:
                answer = {"lat": 20.0, "lon": -100.0, "place": "somewhere dry",
                          "granularity": "country", "confidence": "medium",
                          "reasoning": "scripted, not a real reading"}
            elif request.schema is CLAIM_SCHEMA:
                answer = {"claims": [{"level": "country", "value": "scripted",
                                      "confidence": "medium",
                                      "supports": [{"evidence_id": "e1",
                                                    "strength": 0.7}]}]}
            else:
                return Completion("no tool would narrow this", model, usage)
            return Completion(json.dumps(answer), model, usage, structured=answer)

    return Router(Scripted(budget=budget))


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
    ap.add_argument("--monthly", type=float, default=20.0,
                    help="ceiling for the calendar month, across every run. Set "
                         "your provider's own cap as well; that one is the only "
                         "ceiling a bug here cannot get past")
    ap.add_argument("--workers", type=int, default=6,
                    help="images handled at once. The calls are network bound, "
                         "so this is close to a linear speedup until the "
                         "provider starts rate limiting")
    ap.add_argument("--traces", metavar="DIR",
                    help="also write a step-by-step replay of each board here, "
                         "one JSON per run. Free, and it is what the site plays "
                         "back. Also the fastest way to see why a tool changed "
                         "nothing")
    ap.add_argument("--no-gazetteer", action="store_true",
                    help="drop the OpenStreetMap name lookup, to measure what "
                         "external retrieval is worth on its own")
    ap.add_argument("--no-classifier", action="store_true",
                    help="leave the geocell classifier out of the registry, to "
                         "measure what it is worth by its absence")
    ap.add_argument("--out", default="results/agent_runs.json")
    args = ap.parse_args()

    if args.samples < 2:
        print("warning: below 2 samples the spread column is meaningless, and a "
              "median that moves 40 km on rerun will look like a result.\n")

    ledger = Ledger(monthly_limit_usd=None if args.dry else args.monthly)
    if not args.dry:
        try:
            ledger.check(args.limit)
        except BudgetExceeded as exc:
            print(f"refused before starting: {exc}")
            return 1
        print(f"  {ledger.summary()}\n")

    if args.dry:
        budget = Budget(None, allow_unpriced=True)
        router = dry_router(budget)
    else:
        from vestigo.config import build
        router, budget = build(args.preset, limit_usd=args.limit, batched=args.batched)

    tools = [SolarTool()]
    if not args.no_gazetteer:
        tools.append(PlaceLookup())
    if not args.no_classifier:
        try:
            tools.append(GeocellTool())
        except Exception as exc:               # no ML stack, or nothing trained
            print(f"  classifier unavailable, running without it: {exc}\n")
    agent = Agent(router, tools=Registry(tools), budget=budget)
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
    consensus_rows: list[dict] = []
    records = []
    stopped = None

    def one_image(entry: dict):
        """Everything for a single photograph. Independent of every other one,
        which is what makes the fan-out safe: the samples within an image share
        nothing, and the board is rebuilt per run."""
        path = ROOT / "data/images" / entry["file"]
        return entry, agent.run_samples(path, n=args.samples, subject=entry["id"],
                                        context=context_for(entry))

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one_image, e): e for e in entries}
        try:
            for future in concurrent.futures.as_completed(futures):
                try:
                    entry, runs = future.result()
                except BudgetExceeded as exc:
                    stopped = str(exc)
                    for other in futures:
                        other.cancel()
                    continue
                except Exception as exc:                # one bad image, not the run
                    print(f"{futures[future]['id']:<20}failed: {exc}")
                    continue

                truth = LatLon(entry["truth"]["lat"], entry["truth"]["lon"])
                rows, points = [], []
                for sample, run in enumerate(runs):
                    if args.traces:
                        # One file per sample, not per image: two samples of
                        # the same photograph reach the answer differently and
                        # the difference is the interesting part. Written
                        # before the decline check, because a run that refused
                        # to answer is the case the site most wants to show.
                        stem = f"{entry['id']}_s{sample}"
                        try:
                            write_trace(run.board, ROOT / args.traces / f"{stem}.json")
                        except ValueError as exc:
                            print(f"  no trace for {stem}: {exc}")
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
                        # The board resolves on computed confidence, not on the
                        # stated word. Fitting thresholds against anything else
                        # fits a proxy, so both go in the record.
                        "computed_confidence": run.resolution.confidences.get(
                            run.answer.id, 0.0),
                        "all_levels": {c.level.label: run.resolution.confidences[c.id]
                                       for c in run.resolution.chain},
                        "evidence": len(run.board.evidence),
                        "constraints": len(run.board.constraints),
                        # Which tools actually fired, and what they said. The
                        # earlier runs recorded only a count, which is why
                        # "tools change nothing" took four runs to diagnose:
                        # a count cannot tell a tool that ran and found nothing
                        # from a tool the model never reached for.
                        "tools": [
                            {"tool": ev.source, "summary": ev.summary}
                            for ev in run.board.evidence.values()
                            if ev.kind == EvidenceKind.TOOL
                        ],
                        "rejected": run.rejected,
                        # What tried to knock the answer down and whether it
                        # succeeded. Without this a refuted run and a run
                        # nothing could check look identical in the record.
                        "verification": run.verification.to_dict(),
                    })

                # What the samples agree on, scored alongside the per-sample
                # answers rather than instead of them. The samples are already
                # paid for; using only one of them and reporting the spread of
                # the rest is the waste this measures against.
                agreed = consense(runs)
                consensus_rows.append({
                    "id": entry["id"], "source": entry["source"],
                    **agreed.to_dict(),
                    "error_km": (truth.distance_km(agreed.point)
                                 if agreed.point else None),
                })

                if rows:
                    summary = summarise_repeats(entry["id"], rows, points)
                    summaries.append(summary)
                    print(f"{entry['id']:<20}{entry['source']:<17}"
                          f"{summary.median_error_km:>9.1f} km  "
                          f"spread {summary.spread_km:>8.0f} km"
                          f"  {summary.hit_rate:>4.0%} correct  "
                          f"{'' if summary.stable else 'unstable'}", flush=True)
        except KeyboardInterrupt:
            stopped = "interrupted"
            pool.shutdown(wait=False, cancel_futures=True)

    if stopped:
        print(f"\nstopped: {stopped}")

    if not scored:
        print("\nno scorable runs")
        return 1

    summaries.sort(key=lambda s: s.subject)
    records.sort(key=lambda r: (r["id"], r["error_km"]))

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

    # ------------------------------------------------------------------
    # Consensus across samples
    # ------------------------------------------------------------------
    if consensus_rows:
        print("\n" + "=" * 78)
        print("CONSENSUS ACROSS SAMPLES")
        print("=" * 78)
        answered = [c for c in consensus_rows if c["error_km"] is not None]
        refused = [c for c in consensus_rows if c["error_km"] is None]

        print(f"{'source':<18}{'n':>4}{'median km':>11}{'worst km':>11}"
              f"{'unanimous':>11}{'demoted':>9}")
        print("-" * 78)
        for src in SOURCES:
            sub = [c for c in answered if c["source"] == src]
            if not sub:
                continue
            errs = sorted(c["error_km"] for c in sub)
            print(f"{src:<18}{len(sub):>4}{statistics.median(errs):>11.1f}"
                  f"{errs[-1]:>11.0f}"
                  f"{sum(1 for c in sub if c['agreement'] == 1.0) / len(sub):>11.0%}"
                  f"{sum(1 for c in sub if c['demoted_from']):>9}")
        if answered:
            errs = sorted(c["error_km"] for c in answered)
            print("-" * 78)
            print(f"{'all':<18}{len(answered):>4}{statistics.median(errs):>11.1f}"
                  f"{errs[-1]:>11.0f}"
                  f"{sum(1 for c in answered if c['agreement'] == 1.0) / len(answered):>11.0%}"
                  f"{sum(1 for c in answered if c['demoted_from']):>9}")

        # The comparison this exists for. A single sample is what one API call
        # buys; consensus is what three of them buy, and the tail is where the
        # difference should show up if it shows up anywhere.
        singles = sorted(r["error_km"] for r in records)
        if singles and answered:
            def tail(v, q):
                return v[min(len(v) - 1, int(len(v) * q))]
            print(f"\n  {'':<14}{'median':>10}{'75th':>10}{'90th':>10}{'worst':>10}")
            print(f"  {'one sample':<14}{statistics.median(singles):>10.0f}"
                  f"{tail(singles, 0.75):>10.0f}{tail(singles, 0.90):>10.0f}"
                  f"{singles[-1]:>10.0f}")
            print(f"  {'consensus':<14}{statistics.median(errs):>10.0f}"
                  f"{tail(errs, 0.75):>10.0f}{tail(errs, 0.90):>10.0f}"
                  f"{errs[-1]:>10.0f}")
            print("\n  The median is not the point. A frontier model already has a good\n"
                  "  median and a dangerous tail, and the tail is the only column where\n"
                  "  three samples can buy something one call cannot.")

        if refused:
            print(f"\n  {len(refused)} images where the samples agreed on nothing and no\n"
                  f"  answer was stated. Each of those had samples that would each have\n"
                  f"  been stated alone, with a confidence.")
            for c in refused[:5]:
                print(f"    {c['id']:<24} spread {c['spread_km']:>8.0f} km")

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
    if not args.dry:
        ledger.absorb(budget)
        print(f"  {ledger.summary()}")
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
        "spent_usd": budget.spent_usd, "runs": records, "consensus": consensus_rows,
    }, indent=2) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
