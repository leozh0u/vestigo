"""Fit the board's confidence thresholds to measured runs.

`DEFAULT_THRESHOLDS` in the board are numbers written before any agent had run,
and the first real eval says they are wrong: the agent overclaims on 28% of
runs against the bare model's 11%, and 38% of its point and district claims
miss. A threshold that lets a low-confidence region claim through at 17,740 km
is not a threshold, it is a formality.

The idea is one line. A claim at level L is only stated if its confidence
clears the bar for L. Raise the bar and fewer claims are made, so overclaiming
falls and the system answers coarser. Lower it and the reverse. There is a
right place to sit and it is a property of the data, not of anyone's judgement.

What is optimised: overclaim rate first, held under a target, then the finest
answer available subject to that. Accuracy is not the objective. A system that
answers "continent" every time never overclaims and is useless, so the search
has to be told to want specificity and to pay for it in overclaims.

**This fits a proxy, and the gap is the point.** The board resolves on computed
confidence, evidence strength times admissibility. The first run only recorded
the stated word, so this maps those words to numbers and fits against that.

The check that proves it: simulating the current thresholds on the recorded
runs predicts a 9% overclaim rate, and the run actually produced 28%. The
simulation is not modelling the mechanism, so its output is a direction and not
a setting. The harness now records computed confidence too, which is what makes
the next fit a real one.

    ./.venv/bin/python eval/fit_thresholds.py

Reads results/agent_full.json. Costs nothing and needs no network.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vestigo.board import DEFAULT_THRESHOLDS, Level
from vestigo.scoring import LEVEL_RADIUS_KM, parse_level

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRID = [round(x / 20, 2) for x in range(0, 21)]      # 0.00 to 1.00 in twentieths
TARGET_OVERCLAIM = 0.10                              # the baseline's rate


def load(path: str):
    """One row per run: what it claimed, at what confidence, and how far out.

    The stated confidence is mapped to a number the same way the calibration
    report does, which is an assumption this inherits and cannot remove.
    """
    from vestigo.scoring import STATED_CONFIDENCE
    rows = []
    for r in json.loads((ROOT / path).read_text())["runs"]:
        if not r.get("confidence"):
            continue
        rows.append({
            "level": parse_level(r["level"]),
            "score": STATED_CONFIDENCE.get(r["confidence"], 0.5),
            "error_km": r["error_km"],
            "source": r["source"],
        })
    return rows


def outcome(rows, thresholds):
    """What a set of thresholds would have produced.

    A claim that fails its threshold is not scored as wrong. It is not made,
    and the system falls back to the coarsest level it would have cleared. That
    is what the board does, so the fit has to model it rather than pretend a
    blocked claim disappears.
    """
    stated = overclaimed = 0
    depth = 0
    for row in rows:
        level = None
        for candidate in sorted(Level, reverse=True):
            if candidate <= row["level"] and row["score"] >= thresholds[candidate]:
                level = candidate
                break
        if level is None:
            continue                                  # says nothing at all
        stated += 1
        depth += int(level)
        if row["error_km"] > LEVEL_RADIUS_KM[level]:
            overclaimed += 1
    if not stated:
        return {"stated": 0, "overclaim": 0.0, "depth": 0.0, "silent": len(rows)}
    return {"stated": stated,
            "overclaim": overclaimed / stated,
            "depth": depth / stated,
            "silent": len(rows) - stated}


def fit(rows, target=TARGET_OVERCLAIM):
    """Coordinate descent over one level at a time.

    Small enough to brute force per level and the levels barely interact, since
    each claim is only tested against its own bar. Two passes converge.
    """
    best = dict(DEFAULT_THRESHOLDS)
    for _ in range(2):
        for level in sorted(Level):
            scored = []
            for value in GRID:
                trial = {**best, level: value}
                out = outcome(rows, trial)
                if out["stated"] == 0:
                    continue
                # Under the target, prefer the finest answers. Over it, prefer
                # the lowest overclaim rate. Specificity has to be wanted, or
                # the search answers "continent" forever and scores perfectly.
                key = ((0, -out["depth"], out["overclaim"])
                       if out["overclaim"] <= target
                       else (1, out["overclaim"], -out["depth"]))
                scored.append((key, value))
            if scored:
                best[level] = min(scored)[1]
    return best


def show(name, thresholds, rows):
    out = outcome(rows, thresholds)
    print(f"\n{name}")
    print("  " + "  ".join(f"{lv.label}={thresholds[lv]:.2f}" for lv in sorted(Level)))
    print(f"  claims stated {out['stated']}/{len(rows)}, "
          f"silent {out['silent']}, "
          f"overclaim {out['overclaim']:.0%}, "
          f"mean level {out['depth']:.2f}")
    return out


def main():
    path = "results/agent_full.json"
    if not (ROOT / path).exists():
        print(f"no {path}. Run eval/harness.py first.")
        return 1
    rows = load(path)
    print(f"{len(rows)} scored runs with a stated confidence, "
          f"from {len({r['source'] for r in rows})} sources")
    print(f"target overclaim rate {TARGET_OVERCLAIM:.0%}, "
          "which is what the bare model call achieved")

    have_computed = any("computed_confidence" in r for r in
                        json.loads((ROOT / path).read_text())["runs"])
    if not have_computed:
        print("\n  WARNING: these runs predate the harness recording computed\n"
              "  confidence, so the fit below is against the stated word instead.\n"
              "  Simulating the current thresholds predicts 9% overclaim where the\n"
              "  run produced 28%, which is how far off the proxy is. Treat the\n"
              "  output as a direction. Rerun the eval to fit the real mechanism.")

    before = show("as written, guessed before any data existed", DEFAULT_THRESHOLDS, rows)
    fitted = fit(rows)
    after = show("fitted to these runs", fitted, rows)

    print("\n" + "-" * 66)
    print(f"  overclaim {before['overclaim']:.0%} -> {after['overclaim']:.0%}"
          f"   mean level {before['depth']:.2f} -> {after['depth']:.2f}"
          f"   silent {before['silent']} -> {after['silent']}")
    print("-" * 66)
    print("""
  Three reasons not to apply these yet.

  It fits the stated confidence word, and the board resolves on computed
  confidence. Those are different numbers and the gap is large.

  It is fitted and scored on the same runs, which is the definition of
  overfitting.

  The rural half is missing, and that is the half the project is for.

  A city bar of 0.00 sitting at the edge of the grid is the usual sign of a
  thin dataset rather than a real optimum. What it is saying is that the
  agent's point claims tend to be accurate to about a city, so demoting them
  is nearly free. That much is probably true and worth keeping in mind.""")

    out = ROOT / "results/fitted_thresholds.json"
    out.write_text(json.dumps(
        {"fitted": {lv.label: fitted[lv] for lv in sorted(Level)},
         "before": before, "after": after,
         "target_overclaim": TARGET_OVERCLAIM,
         "fitted_on": path, "runs": len(rows),
         "caveat": "fitted and scored on the same runs, rural half missing"},
        indent=2) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
