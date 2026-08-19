"""The evidence board.

The spine of the project. Everything else attaches to this.

Five record types, and the separation between them is the whole design:

  Evidence    something that happened. A tool ran with these inputs and
              returned this, or a rule was cited. A fact, with no opinion in it.
  Support     the reading of one piece of evidence for one claim. The same
              shadow measurement can support Mexico and refute Kenya, so the
              direction and the weight live on the link, not on the fact.
  Claim       a location at some granularity. Country, region, city, point.
              A claim holds no confidence of its own. Its confidence is
              computed from the evidence supporting it, every time it is asked
              for. A claim with no supporting evidence scores zero and does not
              appear in an answer.
  Constraint  a region of the earth that the answer has to be in, or has to be
              out of. Not a claim. It does not compete with point estimates, it
              filters them.
  Candidate   a specific place under consideration, from wherever. Candidates
              are what constraints act on, which is how a constraint narrows an
              answer without ever proposing one.

The Constraint type is here because of what Phase 0 measured. On the Thailand
image the model derived a longitude band that contained the truth, then chose a
point inside the band six times worse than its own image-only guess. The band
was right and treating it as a point estimate was wrong. On the Mexico image
the capture timestamp did not move the answer at all, it stopped the answer
flipping to Kenya between identical runs. Both cases say the same thing: this
kind of evidence eliminates candidates and reduces variance, and it has to be
represented as something that eliminates rather than something that votes.

Two rules the code enforces rather than encourages:

1. Evidence can only raise a claim's confidence. Constraints can only lower it.
   Nothing in the pipeline can talk a claim up past what its evidence carries.
2. Correlated evidence counts once. Five signals read off the same signboard
   are one signal. That distinction is what stops a chain of confident
   restatements from looking like corroboration.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import IntEnum, StrEnum
from typing import Any, ClassVar

from .geo import LatLon, haversine, lat_band_excess, lon_band_excess

SCHEMA_VERSION = 1


class Level(IntEnum):
    """Granularity of a claim, coarse to fine.

    Ordered so that "the most specific claim the evidence supports" is a max
    over the levels that clear their threshold.
    """

    CONTINENT = 1
    COUNTRY = 2
    REGION = 3      # state, province, prefecture
    CITY = 4
    DISTRICT = 5    # neighbourhood, village, named road
    POINT = 6       # a coordinate worth defending on its own

    @property
    def label(self) -> str:
        return self.name.lower()


class EvidenceKind(StrEnum):
    """Where a piece of evidence came from."""

    TOOL = "tool"                   # a tool ran and returned something
    RULE = "rule"                   # a cited rule from the knowledge base
    OBSERVATION = "observation"     # a structured reading of the image itself
    CONTEXT = "context"             # something that shipped with the photo


@dataclass(frozen=True, slots=True)
class Evidence:
    """A record of something that happened. Immutable once on the board.

    `derived_from` is what makes independence computable. It holds the ids of
    the evidence or observation this one rests on. Two pieces of evidence that
    share a root are correlated and are not allowed to compound.
    """

    id: str
    kind: str
    source: str                     # tool name, rule id, or extractor name
    summary: str                    # one line, for the board view
    inputs: dict[str, Any] = field(default_factory=dict)
    result: Any = None              # what came back, kept verbatim
    derived_from: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "summary": self.summary,
            "inputs": self.inputs,
            "result": self.result,
            "derived_from": list(self.derived_from),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        return cls(
            id=d["id"],
            kind=d["kind"],
            source=d["source"],
            summary=d["summary"],
            inputs=d.get("inputs", {}),
            result=d.get("result"),
            derived_from=tuple(d.get("derived_from", ())),
        )


@dataclass(frozen=True, slots=True)
class Support:
    """One piece of evidence, read for one claim.

    `strength` is the probability that this evidence on its own would settle
    the claim. A signboard naming the town is close to 1. Left-hand traffic in
    a photograph that already looks European is maybe 0.3.
    """

    evidence_id: str
    strength: float
    supports: bool = True           # False means it argues against the claim
    note: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be in [0, 1], got {self.strength}")

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "strength": self.strength,
            "supports": self.supports,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Support":
        return cls(d["evidence_id"], float(d["strength"]),
                   bool(d.get("supports", True)), d.get("note", ""))


@dataclass(frozen=True, slots=True)
class Claim:
    """A location at one granularity.

    No confidence field. Ask the board. `stated_confidence` is only what a
    model said about itself, kept beside the computed number so the two can be
    compared. Phase 0 found stated medium confidence to be bimodal from 0.1 km
    to 1545 km, so the stated value is data to be calibrated, not a number to
    act on.
    """

    id: str
    level: Level
    value: str                      # "Mexico", "Queretaro", "Ban Krut"
    point: LatLon | None = None     # representative location, if there is one
    supports: tuple[Support, ...] = ()
    parent: str | None = None       # id of the coarser claim this sits inside
    stated_confidence: str | None = None
    note: str = ""

    @property
    def grounded(self) -> bool:
        """Does any evidence argue for this claim at all."""
        return any(s.supports and s.strength > 0 for s in self.supports)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": int(self.level),
            "value": self.value,
            "point": self.point.to_dict() if self.point else None,
            "supports": [s.to_dict() for s in self.supports],
            "parent": self.parent,
            "stated_confidence": self.stated_confidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        return cls(
            id=d["id"],
            level=Level(d["level"]),
            value=d["value"],
            point=LatLon.from_dict(d["point"]) if d.get("point") else None,
            supports=tuple(Support.from_dict(s) for s in d.get("supports", ())),
            parent=d.get("parent"),
            stated_confidence=d.get("stated_confidence"),
            note=d.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """A specific place under consideration.

    Candidates are what constraints act on. They come from anywhere: the
    model's own guess, an Overpass co-occurrence query, a GeoCLIP top-k, a
    gazetteer lookup. `prior` is the weight before any constraint is applied.
    """

    id: str
    point: LatLon
    label: str = ""
    prior: float = 1.0
    origin: str = ""                # what proposed it
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "point": self.point.to_dict(),
            "label": self.label,
            "prior": self.prior,
            "origin": self.origin,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(
            id=d["id"],
            point=LatLon.from_dict(d["point"]),
            label=d.get("label", ""),
            prior=float(d.get("prior", 1.0)),
            origin=d.get("origin", ""),
            evidence_ids=tuple(d.get("evidence_ids", ())),
        )


# --------------------------------------------------------------------------
# Constraints
# --------------------------------------------------------------------------

CONSTRAINT_TYPES: dict[str, type["Constraint"]] = {}


def register_constraint(cls):
    """Register a constraint type so boards can round-trip through JSON.

    Public, because constraint types live wherever their subject matter lives.
    The solar ones are in `vestigo/solar.py` next to the algorithm they use, not
    here. The cost of that is a decorator every new type has to remember and an
    import in `vestigo/__init__.py`, which is what makes a saved board readable.
    """
    CONSTRAINT_TYPES[cls.kind] = cls
    return cls


@dataclass(frozen=True, kw_only=True, slots=True)
class Constraint(ABC):
    """A region the answer has to be in, or has to be out of.

    `weight` is how sure we are of the constraint itself, which is a different
    question from whether a given point satisfies it. At weight 1.0 a point
    outside the region scores 0 and is dead. At weight 0.8 it keeps 0.2, so a
    constraint that turns out to be wrong costs the true answer some ranking
    but does not delete it. Solar geometry off a misjudged shadow should not be
    able to rule out the correct country outright, so tools that measure
    something from a soft input should not claim weight 1.0.

    Subclasses implement `raw_admits`, returning 1.0 for fully inside, 0.0 for
    fully outside, something between for a soft edge, or None to abstain.
    **Abstaining is not vetoing.** A constraint that cannot evaluate a point,
    because it has no resolver or the point is missing, returns None and the
    point passes untouched.
    """

    kind: ClassVar[str] = "constraint"

    id: str
    description: str
    weight: float = 1.0
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be in [0, 1], got {self.weight}")

    @abstractmethod
    def raw_admits(self, point: LatLon | None) -> float | None:
        ...

    def admits(self, point: LatLon | None) -> float:
        """How well `point` satisfies this constraint, in [0, 1]."""
        raw = self.raw_admits(point)
        if raw is None:
            return 1.0
        raw = min(1.0, max(0.0, raw))
        return 1.0 - self.weight * (1.0 - raw)

    def excludes(self, point: LatLon | None, cutoff: float = 0.5) -> bool:
        return self.admits(point) < cutoff

    def _params(self) -> dict:
        return {}

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "description": self.description,
            "weight": self.weight,
            "evidence_ids": list(self.evidence_ids),
            "params": self._params(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Constraint":
        if d["kind"] not in CONSTRAINT_TYPES:
            raise KeyError(
                f"unknown constraint kind {d['kind']!r}. The module defining it "
                "has not been imported, so it never registered."
            )
        target = CONSTRAINT_TYPES[d["kind"]]
        return target(
            id=d["id"],
            description=d["description"],
            weight=float(d.get("weight", 1.0)),
            evidence_ids=tuple(d.get("evidence_ids", ())),
            **target._from_params(d.get("params", {})),
        )

    @staticmethod
    def _from_params(p: dict) -> dict:
        return dict(p)


def soft_score(excess: float, soft: float) -> float:
    """Map "how far outside the edge" to an admission score.

    With no soft margin this is a hard in-or-out. With one, the score falls
    linearly to zero across the margin, which is the honest shape for a band
    measured off a shadow with a few degrees of error in it.
    """
    if excess <= 0.0:
        return 1.0
    if soft <= 0.0:
        return 0.0
    return max(0.0, 1.0 - excess / soft)


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class LatitudeBand(Constraint):
    """Latitude between lo and hi. What solar elevation gives you."""

    kind: ClassVar[str] = "lat_band"

    lo: float
    hi: float
    soft_deg: float = 0.0

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        return soft_score(lat_band_excess(point.lat, self.lo, self.hi), self.soft_deg)

    def _params(self) -> dict:
        return {"lo": self.lo, "hi": self.hi, "soft_deg": self.soft_deg}


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class LongitudeBand(Constraint):
    """Longitude in the band running east from lo to hi.

    What solar time gives you: local noon against a capture timestamp in UTC
    fixes longitude to within however well the time of day can be read.
    Wrap-aware, so a band across the dateline is the short way round.
    """

    kind: ClassVar[str] = "lon_band"

    lo: float
    hi: float
    soft_deg: float = 0.0

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        return soft_score(lon_band_excess(point.lon, self.lo, self.hi), self.soft_deg)

    def _params(self) -> dict:
        return {"lo": self.lo, "hi": self.hi, "soft_deg": self.soft_deg}


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class BoundingBox(Constraint):
    """Both bands at once. Useful for "somewhere in the Pacific Northwest"."""

    kind: ClassVar[str] = "bbox"

    south: float
    west: float
    north: float
    east: float
    soft_deg: float = 0.0

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        lat = soft_score(lat_band_excess(point.lat, self.south, self.north), self.soft_deg)
        lon = soft_score(lon_band_excess(point.lon, self.west, self.east), self.soft_deg)
        return min(lat, lon)

    def _params(self) -> dict:
        return {"south": self.south, "west": self.west, "north": self.north,
                "east": self.east, "soft_deg": self.soft_deg}


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class NearPoint(Constraint):
    """Within (or beyond) a radius of a point.

    `inside=False` is the useful half. "More than 40 km from any coast" is a
    real constraint that a coastline lookup can produce, and it is the shape
    that rules candidates out rather than proposing new ones.
    """

    kind: ClassVar[str] = "near_point"

    center: LatLon
    radius_km: float
    soft_km: float = 0.0
    inside: bool = True

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        d = haversine(self.center, point)
        excess = (d - self.radius_km) if self.inside else (self.radius_km - d)
        return soft_score(excess, self.soft_km)

    def _params(self) -> dict:
        return {"center": self.center.to_dict(), "radius_km": self.radius_km,
                "soft_km": self.soft_km, "inside": self.inside}

    @staticmethod
    def _from_params(p: dict) -> dict:
        return {"center": LatLon.from_dict(p["center"]), "radius_km": p["radius_km"],
                "soft_km": p.get("soft_km", 0.0), "inside": p.get("inside", True)}


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class RegionSet(Constraint):
    """Membership of a named set of regions, usually countries.

    This is where most of the sharp geo knowledge lives. Left-hand traffic,
    plate aspect ratio, script, plug socket shape and road paint colour all
    reduce to "the answer is in one of these countries" or "the answer is not".
    The Mexico case from Phase 0 is the negative form of this: solar timing
    ruled out East Africa, which is a set exclusion, not a point estimate.

    Needs a resolver to turn a coordinate into a region code. The resolver is
    injected rather than stored, since it is code and the board serializes to
    JSON. Without one the constraint abstains, which is deliberate: an
    unevaluated constraint must never quietly veto the right answer.
    """

    kind: ClassVar[str] = "region_set"

    codes: frozenset[str]
    inside: bool = True
    resolver: Callable[[LatLon], str | None] | None = field(
        default=None, compare=False, repr=False
    )

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None or self.resolver is None:
            return None
        code = self.resolver(point)
        if code is None:
            return None
        hit = code.upper() in {c.upper() for c in self.codes}
        return 1.0 if hit == self.inside else 0.0

    def with_resolver(self, resolver: Callable[[LatLon], str | None]) -> "RegionSet":
        return replace(self, resolver=resolver)

    def _params(self) -> dict:
        return {"codes": sorted(self.codes), "inside": self.inside}

    @staticmethod
    def _from_params(p: dict) -> dict:
        return {"codes": frozenset(p["codes"]), "inside": p.get("inside", True)}


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: Candidate
    score: float                            # posterior, normalized across the set
    admissibility: float                    # product of every constraint score
    per_constraint: dict[str, float]        # constraint id -> score, for the board view

    @property
    def point(self) -> LatLon:
        return self.candidate.point


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the board is prepared to say.

    `chain` runs coarse to fine and holds only the claims that cleared their
    threshold. `answer` is the finest of them, which is the whole design idea:
    the most specific claim the evidence supports, and then stop.
    """

    chain: tuple[Claim, ...]
    confidences: dict[str, float]
    answer: Claim | None

    @property
    def level(self) -> Level | None:
        return self.answer.level if self.answer else None

    def describe(self) -> str:
        if not self.answer:
            return "no claim clears its threshold"
        parts = [f"{c.level.label}={c.value} ({self.confidences[c.id]:.2f})"
                 for c in self.chain]
        return "  ".join(parts)


# --------------------------------------------------------------------------
# The board
# --------------------------------------------------------------------------

# Below this, a claim is not stated. Phase 5 fits these against the calibration
# curve, which is the point of having them per level rather than as one number:
# a point claim should have to clear a higher bar than a country claim.
DEFAULT_THRESHOLDS: dict[Level, float] = {
    Level.CONTINENT: 0.35,
    Level.COUNTRY: 0.45,
    Level.REGION: 0.55,
    Level.CITY: 0.60,
    Level.DISTRICT: 0.70,
    Level.POINT: 0.75,
}


class Board:
    """Working state for one photograph.

    Append only by design. Nothing is edited or deleted once added, so the
    board at the end of a run is a complete record of how the answer was
    reached and can be replayed or shown as-is.

    Ids are sequential per board rather than random, so two runs over the same
    image produce diffable boards. With run-to-run noise measured at a 40 km
    median in Phase 0, being able to diff two boards is not a nicety.
    """

    def __init__(self, subject: str, thresholds: dict[Level, float] | None = None):
        self.subject = subject
        self.thresholds = dict(thresholds or DEFAULT_THRESHOLDS)
        self.evidence: dict[str, Evidence] = {}
        self.claims: dict[str, Claim] = {}
        self.constraints: dict[str, Constraint] = {}
        self.candidates: dict[str, Candidate] = {}
        self._counters: dict[str, int] = {"e": 0, "c": 0, "k": 0, "n": 0}

    def _next(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}{self._counters[prefix]}"

    # -- adding ------------------------------------------------------------

    def add_evidence(
        self,
        source: str,
        summary: str,
        *,
        kind: str = EvidenceKind.TOOL,
        inputs: dict | None = None,
        result: Any = None,
        derived_from: Sequence[str] = (),
    ) -> Evidence:
        for parent in derived_from:
            if parent not in self.evidence:
                raise KeyError(f"derived_from references unknown evidence {parent!r}")
        ev = Evidence(
            id=self._next("e"),
            kind=kind,
            source=source,
            summary=summary,
            inputs=dict(inputs or {}),
            result=result,
            derived_from=tuple(derived_from),
        )
        self.evidence[ev.id] = ev
        return ev

    def add_claim(
        self,
        level: Level,
        value: str,
        *,
        supports: Iterable[Support] = (),
        point: LatLon | None = None,
        parent: str | None = None,
        stated_confidence: str | None = None,
        note: str = "",
    ) -> Claim:
        supports = tuple(supports)
        for s in supports:
            if s.evidence_id not in self.evidence:
                raise KeyError(f"claim cites unknown evidence {s.evidence_id!r}")
        if parent is not None and parent not in self.claims:
            raise KeyError(f"claim cites unknown parent {parent!r}")
        claim = Claim(
            id=self._next("c"),
            level=level,
            value=value,
            point=point,
            supports=supports,
            parent=parent,
            stated_confidence=stated_confidence,
            note=note,
        )
        self.claims[claim.id] = claim
        return claim

    def add_constraint(self, constraint: Constraint) -> Constraint:
        for eid in constraint.evidence_ids:
            if eid not in self.evidence:
                raise KeyError(f"constraint cites unknown evidence {eid!r}")
        if not constraint.id or constraint.id in self.constraints:
            constraint = replace(constraint, id=self._next("k"))
        self.constraints[constraint.id] = constraint
        return constraint

    def add_candidate(
        self,
        point: LatLon,
        *,
        label: str = "",
        prior: float = 1.0,
        origin: str = "",
        evidence_ids: Sequence[str] = (),
    ) -> Candidate:
        cand = Candidate(
            id=self._next("n"),
            point=point,
            label=label,
            prior=prior,
            origin=origin,
            evidence_ids=tuple(evidence_ids),
        )
        self.candidates[cand.id] = cand
        return cand

    # -- independence ------------------------------------------------------

    def roots(self, evidence_id: str) -> frozenset[str]:
        """The original observations a piece of evidence rests on.

        Walks `derived_from` back to evidence with no parents. Evidence that
        cites something outside the board, an observation id from the extractor
        for instance, counts that id as a root in its own right.
        """
        seen: set[str] = set()
        out: set[str] = set()
        stack = [evidence_id]
        while stack:
            eid = stack.pop()
            if eid in seen:
                continue
            seen.add(eid)
            ev = self.evidence.get(eid)
            if ev is None or not ev.derived_from:
                out.add(eid)
                continue
            stack.extend(ev.derived_from)
        return frozenset(out)

    def independent_groups(self, evidence_ids: Iterable[str]) -> list[list[str]]:
        """Partition evidence into groups that share no root observation.

        Two pieces of evidence read off the same signboard land in one group
        and count once. Two that came from unrelated observations land in
        separate groups and compound. Without this, a model restating the same
        observation four ways looks like four independent confirmations, which
        is the confabulation failure mode wearing a disguise.
        """
        ids = list(evidence_ids)
        groups: list[tuple[set[str], list[str]]] = []
        for eid in ids:
            r = set(self.roots(eid))
            merged: list[tuple[set[str], list[str]]] = []
            members = [eid]
            for roots, group in groups:
                if roots & r:
                    r |= roots
                    members = group + members
                else:
                    merged.append((roots, group))
            merged.append((r, members))
            groups = merged
        return [g for _, g in groups]

    # -- scoring -----------------------------------------------------------

    def evidence_confidence(self, claim: Claim) -> float:
        """Confidence in a claim from its evidence alone.

        Within a correlated group, the strongest piece counts and the rest add
        nothing. Across independent groups, noisy-OR, so weak independent
        signals compound the way they should. Evidence arguing against the
        claim is combined the same way and then discounts the result.

        A claim with no supporting evidence returns 0.0. That is the "does not
        count" rule, not a penalty applied afterwards.
        """
        pro = [s for s in claim.supports if s.supports]
        con = [s for s in claim.supports if not s.supports]

        def combine(items: list[Support]) -> float:
            if not items:
                return 0.0
            strongest = {}
            for s in items:
                strongest[s.evidence_id] = max(strongest.get(s.evidence_id, 0.0), s.strength)
            p = 1.0
            for group in self.independent_groups(strongest):
                p *= 1.0 - max(strongest[eid] for eid in group)
            return 1.0 - p

        return combine(pro) * (1.0 - combine(con))

    def admissibility(self, point: LatLon | None) -> float:
        """Product of every constraint's score for a point. 1.0 if unconstrained."""
        p = 1.0
        for c in self.constraints.values():
            p *= c.admits(point)
        return p

    def explain_point(self, point: LatLon | None) -> dict[str, float]:
        return {cid: c.admits(point) for cid, c in self.constraints.items()}

    def confidence(self, claim: Claim) -> float:
        """The number the answer is built on.

        Evidence raises it, constraints scale it down. A claim carrying no
        point is not something the constraints can speak to, so it is scored on
        evidence alone.
        """
        return self.evidence_confidence(claim) * self.admissibility(claim.point)

    def rank_candidates(self) -> list[ScoredCandidate]:
        """Apply every constraint to every candidate and rank what survives.

        This is where a constraint does its job. It never proposes a point of
        its own. The image-only guess sitting inside a correct band keeps its
        weight and stays on top, which is exactly what did not happen on the
        Thailand image in Phase 0.
        """
        scored = []
        for cand in self.candidates.values():
            per = self.explain_point(cand.point)
            adm = math.prod(per.values()) if per else 1.0
            scored.append(ScoredCandidate(cand, cand.prior * adm, adm, per))
        total = sum(s.score for s in scored)
        if total > 0:
            scored = [replace(s, score=s.score / total) for s in scored]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def resolve(self, thresholds: dict[Level, float] | None = None) -> Resolution:
        """The most specific claim the evidence supports, and the chain to it.

        Per level, the best-scoring claim that clears its threshold. The answer
        is the finest of those. Where the finest claim declares a parent, the
        chain follows the parents so the levels agree with each other rather
        than being four independently plausible answers stacked up.
        """
        th = dict(thresholds or self.thresholds)
        conf = {cid: self.confidence(c) for cid, c in self.claims.items()}

        best: dict[Level, Claim] = {}
        for claim in self.claims.values():
            if not claim.grounded:
                continue
            if conf[claim.id] < th.get(claim.level, 0.5):
                continue
            held = best.get(claim.level)
            if held is None or conf[claim.id] > conf[held.id]:
                best[claim.level] = claim

        if not best:
            return Resolution(chain=(), confidences=conf, answer=None)

        answer = best[max(best)]
        chain: dict[Level, Claim] = {}
        node: Claim | None = answer
        seen: set[str] = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            chain.setdefault(node.level, node)
            node = self.claims.get(node.parent) if node.parent else None
        for level, claim in best.items():
            chain.setdefault(level, claim)

        ordered = tuple(chain[k] for k in sorted(chain))
        return Resolution(chain=ordered, confidences=conf, answer=answer)

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "subject": self.subject,
            "thresholds": {int(k): v for k, v in self.thresholds.items()},
            "evidence": [e.to_dict() for e in self.evidence.values()],
            "claims": [c.to_dict() for c in self.claims.values()],
            "constraints": [c.to_dict() for c in self.constraints.values()],
            "candidates": [c.to_dict() for c in self.candidates.values()],
            "counters": dict(self._counters),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Board":
        if d.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"unsupported board schema {d.get('schema')!r}")
        board = cls(d["subject"],
                    {Level(int(k)): v for k, v in d.get("thresholds", {}).items()} or None)
        for e in d.get("evidence", ()):
            ev = Evidence.from_dict(e)
            board.evidence[ev.id] = ev
        for c in d.get("claims", ()):
            claim = Claim.from_dict(c)
            board.claims[claim.id] = claim
        for c in d.get("constraints", ()):
            con = Constraint.from_dict(c)
            board.constraints[con.id] = con
        for c in d.get("candidates", ()):
            cand = Candidate.from_dict(c)
            board.candidates[cand.id] = cand
        board._counters = dict(d.get("counters", board._counters))
        return board

    def __repr__(self) -> str:
        return (f"Board({self.subject!r}, evidence={len(self.evidence)}, "
                f"claims={len(self.claims)}, constraints={len(self.constraints)}, "
                f"candidates={len(self.candidates)})")
