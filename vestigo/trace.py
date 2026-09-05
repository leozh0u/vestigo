"""Replay a finished board, one step at a time.

A `Board` is append-only, so the answer at the end is not the only thing it
holds: the order things arrived is a record of how the answer was reached. This
module walks that order and writes what changed at every step.

Two uses, and the second is the one that justifies the code.

**It drives the site.** Every frame the frontend wants is a row here: the first
guess and where it sat, each piece of evidence as it landed, the region
shrinking as constraints ruled places out, and the level the run finally stopped
at. Animating from this file means the animation is a recording rather than a
dramatisation.

**It is the debugging view this project never had.** Five eval runs went by
before it was clear that a tool candidate can never outrank the model's first
guess, because the run records held totals and not sequences. A trace shows a
gazetteer match arrive with a good point, score below the first pass, and change
nothing, in one screen. That is ten minutes of reading instead of three runs of
inference.

## How a step is built

The board is replayed into a fresh one, adding journal entries in order and
snapshotting after each. Replay rather than slicing, because `add_claim` clamps
strengths and caps levels as it goes, and a snapshot that skipped that work
would show numbers the board would never actually hold. Ids come out identical
because the counters are sequential and the order is preserved.

## The region

`admissible` is the constraint surface sampled on a lat/lon grid: for each cell,
the product of every live constraint's opinion of it, as an integer 0 to 100.
That array is the shrinking region on the globe, and it is computed from the
same `admits` calls the ranking uses rather than drawn to look right.

It is emitted only on steps where the constraint set changed. Most steps do not
touch it, and repeating sixteen thousand identical numbers per step would make
the file large enough that the site would have to fetch it lazily, which is a
cost paid for nothing.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from .board import Board, Level

SCHEMA = "vestigo-trace-1"

# Degrees per grid cell. Four is a deliberate choice rather than a default: the
# coarsest constraint here is a latitude band, the finest is a bounding box a
# few degrees across, and four resolves both while keeping a step under five
# thousand numbers. Finer grids cost file size and buy detail no constraint in
# this project can express.
GRID_DEG = 4.0


def _grid_spec(step_deg: float = GRID_DEG) -> dict:
    cols = int(round(360.0 / step_deg))
    rows = int(round(180.0 / step_deg))
    return {
        "step_deg": step_deg,
        "rows": rows,
        "cols": cols,
        # Cell centres, so a cell is the square around its sample rather than
        # the square starting at it. Off-by-half-a-cell is the classic way a
        # heatmap ends up shifted against the coastlines under it.
        "lat0": -90.0 + step_deg / 2.0,
        "lon0": -180.0 + step_deg / 2.0,
        "order": "row-major, south to north, west to east",
    }


def admissible_grid(board: Board, step_deg: float = GRID_DEG) -> list[int]:
    """Every live constraint's verdict on every cell, as integers 0 to 100.

    Row-major from the south-west corner. Contradicted constraints are left out,
    the same ones `Board.admissibility` leaves out, so the picture agrees with
    the ranking instead of telling a second story.
    """
    from .geo import LatLon

    spec = _grid_spec(step_deg)
    skip = board.contradicted()
    live = [c for cid, c in board.constraints.items() if cid not in skip]
    if not live:
        return []                      # nothing ruled out, so nothing to draw

    out: list[int] = []
    for r in range(spec["rows"]):
        lat = spec["lat0"] + r * step_deg
        for c in range(spec["cols"]):
            lon = spec["lon0"] + c * step_deg
            point = LatLon(lat, lon)
            p = 1.0
            for constraint in live:
                p *= constraint.admits(point)
                if p == 0.0:
                    break
            out.append(round(p * 100))
    return out


def _candidates(board: Board) -> list[dict]:
    return [
        {
            "id": s.candidate.id,
            "lat": round(s.candidate.point.lat, 5),
            "lon": round(s.candidate.point.lon, 5),
            "label": s.candidate.label,
            "origin": s.candidate.origin,
            "prior": round(s.candidate.prior, 4),
            "score": round(s.score, 4),
            "admissibility": round(s.admissibility, 4),
        }
        for s in board.rank_candidates()
    ]


def _answer(board: Board) -> dict | None:
    resolution = board.resolve()
    if resolution.answer is None:
        return None
    answer = resolution.answer
    return {
        "id": answer.id,
        "value": answer.value,
        "level": answer.level.label,
        "stated": answer.stated_confidence,
        "confidence": round(resolution.confidences.get(answer.id, 0.0), 4),
        "chain": [
            {"level": c.level.label, "value": c.value,
             "confidence": round(resolution.confidences[c.id], 4)}
            for c in resolution.chain
        ],
    }


def _describe(board: Board, kind: str, ident: str) -> dict:
    """The one line a viewer reads for this step."""
    if kind == "evidence":
        ev = board.evidence[ident]
        return {"source": ev.source, "summary": ev.summary,
                "evidence_kind": str(ev.kind),
                "resolves_to": ev.resolves_to.label if ev.resolves_to else None,
                "max_strength": ev.max_strength}
    if kind == "constraint":
        con = board.constraints[ident]
        return {"source": con.kind, "summary": con.description or con.kind,
                "weight": con.weight, "cites": list(con.evidence_ids)}
    if kind == "refutation":
        claim_id, _, evidence_id = ident.partition(":")
        claim = board.claims[claim_id]
        return {"source": "verify",
                "summary": f"{claim.value!r} was refuted",
                "claim_id": claim_id, "cites": [evidence_id]}
    if kind == "claim":
        claim = board.claims[ident]
        return {"source": "claim", "summary": f"{claim.value} ({claim.level.label})",
                "level": claim.level.label,
                "stated": claim.stated_confidence,
                "note": claim.note,
                "cites": [s.evidence_id for s in claim.supports]}
    cand = board.candidates[ident]
    return {"source": cand.origin or "candidate",
            "summary": cand.label or f"candidate at {cand.point.lat:.3f}, {cand.point.lon:.3f}",
            "cites": list(cand.evidence_ids)}


def trace(board: Board, *, step_deg: float = GRID_DEG) -> dict:
    """Walk a finished board and return every state it passed through.

    Raises if the board has no journal, which happens when it was loaded from a
    file written before journals existed. Refusing is the right answer: a
    replay in a guessed order would look exactly as convincing as a real one.
    """
    if not board.journal:
        raise ValueError(
            f"board for {board.subject!r} has no journal, so it cannot be "
            f"replayed. Rerun the image rather than inferring an order."
        )

    replay = Board(board.subject, board.thresholds)
    steps: list[dict] = []
    previous_grid: list[int] | None = None

    for i, (kind, ident) in enumerate(board.journal):
        if kind == "evidence":
            source = board.evidence[ident]
            replay.add_evidence(
                source=source.source, summary=source.summary, kind=source.kind,
                inputs=source.inputs, result=source.result,
                derived_from=source.derived_from,
                resolves_to=source.resolves_to, max_strength=source.max_strength,
            )
        elif kind == "constraint":
            replay.add_constraint(board.constraints[ident])
        elif kind == "candidate":
            cand = board.candidates[ident]
            replay.add_candidate(cand.point, label=cand.label, prior=cand.prior,
                                 origin=cand.origin, evidence_ids=cand.evidence_ids)
        elif kind == "claim":
            claim = board.claims[ident]
            # Only the supports that existed when the claim was made. A claim
            # carries its refutations too, and those cite evidence added later
            # in the journal; replaying them here would fail on evidence the
            # replay has not reached, and would also apply a refutation before
            # the step that recorded it.
            original = tuple(sp for sp in claim.supports
                             if sp.supports and sp.evidence_id in replay.evidence)
            replay.add_claim(claim.level, claim.value, supports=original,
                             point=claim.point, parent=claim.parent,
                             stated_confidence=claim.stated_confidence,
                             note=claim.note)
        elif kind == "refutation":
            claim_id, _, evidence_id = ident.partition(":")
            against = next(
                (sp for sp in board.claims[claim_id].supports
                 if not sp.supports and sp.evidence_id == evidence_id), None)
            if against is not None:
                replay.refute(claim_id, evidence_id, against.strength)
        else:
            raise ValueError(f"unknown journal entry kind {kind!r}")

        step: dict[str, Any] = {
            "i": i,
            "kind": kind,
            "id": ident,
            **_describe(replay, kind, ident),
            "candidates": _candidates(replay),
            "answer": _answer(replay),
        }

        # The region only moves when a constraint does, so only look then.
        if kind == "constraint":
            grid = admissible_grid(replay, step_deg)
            if grid != previous_grid:
                step["admissible"] = grid
                previous_grid = grid
        steps.append(step)

    return {
        "schema": SCHEMA,
        "subject": board.subject,
        "grid": _grid_spec(step_deg),
        "steps": steps,
        "final": {
            "answer": _answer(replay),
            "candidates": _candidates(replay),
            "admissible": admissible_grid(replay, step_deg),
            "evidence": len(board.evidence),
            "constraints": len(board.constraints),
            "claims": len(board.claims),
        },
    }


def write_trace(board: Board, path: pathlib.Path | str, *,
                step_deg: float = GRID_DEG) -> pathlib.Path:
    """Write a trace to disk and return where it went."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(trace(board, step_deg=step_deg), separators=(",", ":")) + "\n")
    return p
