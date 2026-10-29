"""Present recorded investigations or exercise the agent with a scripted example.

    python -m vestigo.demo --case landmark
    python -m vestigo.demo --case declined
    python -m vestigo.demo --scripted

Both modes run without API keys, downloaded images, trained checkpoints or
network access. Recorded mode displays historical states; scripted mode runs
the current agent using deliberately synthetic replies and input bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from importlib.resources import files
from pathlib import Path

from .agent import Agent
from .board import Level
from .llm import Budget, Completion, Router, Usage
from .providers import FakeProvider
from .trace import SCHEMA


def validate_recording(record: dict) -> None:
    """Reject a broken replay instead of presenting invented evidence links."""
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ValueError("unsupported recorded trace schema")
    steps, final = record.get("steps"), record.get("final")
    if not isinstance(steps, list) or not steps or not isinstance(final, dict):
        raise ValueError("recording has no steps or final state")
    seen = {kind: set() for kind in ("evidence", "claim", "candidate", "constraint")}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("i") != index:
            raise ValueError("recorded steps are not in order")
        kind, ident = step.get("kind"), step.get("id")
        if kind not in (*seen, "refutation") or not isinstance(ident, str):
            raise ValueError("invalid recorded step")
        if kind in seen:
            if ident in seen[kind]:
                raise ValueError(f"duplicate {kind} id {ident}")
            seen[kind].add(ident)
        if any(cite not in seen["evidence"] for cite in step.get("cites", [])):
            raise ValueError("recorded step cites missing or future evidence")
        if kind == "refutation" and step.get("claim_id") not in seen["claim"]:
            raise ValueError("refutation names a missing claim")
        answer = step.get("answer")
        if answer is not None and answer.get("id") not in seen["claim"]:
            raise ValueError("recorded answer names a missing claim")
    for name, kind in (("evidence", "evidence"), ("claims", "claim"),
                       ("constraints", "constraint")):
        if final.get(name) != len(seen[kind]):
            raise ValueError(f"recorded {name} count does not match its steps")
    if final.get("answer") != steps[-1].get("answer"):
        raise ValueError("recorded final answer differs from its last step")


def load_recording(case: str) -> tuple[dict, dict]:
    fixtures = files("vestigo").joinpath("fixtures")
    manifest = json.loads(fixtures.joinpath("manifest.json").read_text())
    if case not in manifest:
        raise ValueError(f"unknown recording {case!r}")
    provenance = manifest[case]
    body = fixtures.joinpath(provenance["file"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != provenance["sha256"]:
        raise ValueError("recording checksum does not match its source manifest")
    record = json.loads(body)
    validate_recording(record)
    return record, provenance


def scripted_run() -> dict:
    """Exercise current grounding rules; these replies are not model results."""
    model = "claude-sonnet-5"
    answers = [
        {"observations": [{"modality": "vegetation", "what": "dry scrub",
                           "certainty": .9}]},
        {"lat": 20.45, "lon": -100.5, "place": "Mexico", "granularity": "country",
         "confidence": "medium", "reasoning": "synthetic demonstration"},
        {"claims": [
            {"level": "point", "value": "Mexico", "lat": 20.45, "lon": -100.5,
             "supports": [{"evidence_id": "e1", "strength": .99}]},
            {"level": "point", "value": "Unsupported exact address",
             "supports": [{"evidence_id": "invented-id", "strength": .99}]},
        ]},
    ]
    replies = [Completion(json.dumps(answer), model, Usage(model=model),
                          structured=answer) for answer in answers]
    budget = Budget(0)
    provider = FakeProvider(replies, model=model)
    agent = Agent(Router(provider))
    with tempfile.TemporaryDirectory(prefix="vestigo-demo-") as directory:
        image = Path(directory) / "synthetic-input.jpg"
        image.write_bytes(b"synthetic input; no image is being interpreted")
        run = agent.run(image, subject="scripted-grounding-example")
    claim = next(iter(run.board.claims.values()))
    assert claim.level is Level.COUNTRY and run.rejected
    return {"mode": "scripted", "input": "synthetic bytes; not a photograph",
            "inference": "synthetic model replies; current Agent and Board executed",
            "paid_requests": 0, "spent_usd": budget.spent_usd,
            "accepted_level": claim.level.label, "requested_level": "point",
            "rejected": run.rejected, "trace": run.trace.steps}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", choices=("landmark", "rural", "declined"),
                        default="landmark")
    parser.add_argument("--scripted", action="store_true")
    parser.add_argument("--json", action="store_true", help="print a machine-readable summary")
    args = parser.parse_args()
    try:
        if args.scripted:
            summary = scripted_run()
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                print("SCRIPTED EXAMPLE — synthetic replies, current Agent and Board")
                print("No photograph is interpreted. No network or paid requests.")
                for step, detail in summary["trace"]:
                    print(f"{step:<10} {detail}")
                for rejection in summary["rejected"]:
                    print(f"rejected   {rejection}")
                print("Requested point precision was capped to country evidence.")
            return 0
        record, provenance = load_recording(args.case)
        summary = {"mode": "recorded", "source": provenance, "subject": record["subject"],
                   "steps": len(record["steps"]), "final": record["final"]["answer"],
                   "paid_requests": 0, "new_inference": False}
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print("RECORDED INVESTIGATION — historical output, no new inference")
            print(f"Source: {provenance['source']}")
            print(f"Subject: {record['subject']}; {len(record['steps'])} validated steps")
            for step in record["steps"]:
                print(f"{step['i'] + 1:02d} {step['kind']:<11} {step.get('summary', '')}")
            final = summary["final"]
            if final:
                print(f"Recorded final answer: {final['value']} ({final['level']})")
                print(f"Recorded board score: {final['confidence']:.4f}; not a calibrated LLM probability")
            else:
                print("Recorded final answer: declined — insufficient surviving support")
            print("Current inference cost: $0.00. Historical decisions were not recomputed.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"demo could not load: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
