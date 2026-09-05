"""Check a claim against what could disprove it.

Everything before this point in a run is construction: the model looks, guesses,
calls tools, and states claims. Nothing ever tries to knock one down. That
matters because of where this system's errors actually live.

A frontier model's median on this data is 2.6 km. Its tail contains 1,545 km,
7,400 km and 16,753 km, and nothing in the response separates those from the
good ones. **The median is already excellent and the tail is dangerous**, and
the tail is the only axis on which a scaffold can beat a single API call. You
cannot out-guess the model. You can catch it.

## What can and cannot be caught

This catches **incoherence**, not wrongness.

If the model says "Kent County Courthouse, Chestertown" and pins a coordinate,
the gazetteer can say where that building actually is. If the two disagree by
250 km, the claim's own words and its own coordinate contradict each other, and
that is checkable without knowing the right answer.

If the model says "Spain", pins Spain, and the photograph is in New Zealand,
nothing here helps. The claim is coherent and wrong, and no internal check
reaches it. Consensus across samples is the mechanism for that case; this is
the mechanism for the other one. Neither covers both, and pretending otherwise
would be the sort of overclaiming this project is about.

## A refutation is evidence against one claim, not a veto over the board

The first attempt expressed a refutation as a `NearPoint` constraint centred
where the evidence said the place actually was. That was wrong, and testing it
showed why within a minute: a constraint is a statement about where the
*photograph* is, so refuting "Chestertown" at fifty kilometres also killed the
correct "United States" claim resting on the same point. The answer went from a
wrong city to nothing at all, when it should have gone to the right country.

A refutation is not about the photograph. It is about one claim's coherence.

So it attaches to the claim, through machinery the board already had:
`Support(supports=False)`. Supporting evidence is combined, opposing evidence
is combined the same way, and the second discounts the first. No new
arithmetic. The only thing missing was a way to reach a claim after it had been
stated, which is necessarily when a refutation arrives, and `Board.refute` is
that.

The coarser parent survives untouched, which is the whole point: a claim that
cannot defend a street can still defend a country.

## Weak checks must stay weak

The geocell classifier is right about 32% of the time. It cannot refute
anything, and wiring it in as though it could would replace one overconfident
voice with two. It is allowed to lower a `weight`, never to produce a
refutation on its own. Which check is entitled to what is stated in the table
below rather than left to whoever reads the code next.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .board import Board, Claim, EvidenceKind, Level
from .geo import LatLon, haversine
from .scoring import LEVEL_RADIUS_KM


class Verdict(StrEnum):
    """What a check concluded about a claim."""

    CONFIRMED = "confirmed"       # independent evidence puts the claim where it says
    UNSUPPORTED = "unsupported"   # nothing could check it, which is not a mark against it
    REFUTED = "refuted"           # independent evidence puts it somewhere else


# How far a claim's point may sit from where a check places it before the two
# are treated as disagreeing. One level's radius of slack, because a city claim
# pinned at the town hall and a gazetteer match at the railway station are the
# same answer, and a checker that cannot tell those apart refutes everything.
SLACK = 1.0

# How much a refutation is trusted, per source. A gazetteer that resolved a
# name to one prominent place is close to decisive about where that name is; a
# classifier right a third of the time is not entitled to overturn anything.
# These are ceilings on the constraint's weight, not on the claim.
TRUST: dict[str, float] = {
    "place_lookup": 0.8,
    "solar_position": 0.6,
    "geocell_classifier": 0.0,     # may inform, may never refute. See the module docstring
}
DEFAULT_TRUST = 0.3


@dataclass(frozen=True, slots=True)
class Check:
    """One check of one claim, and what it is entitled to do about it."""

    claim_id: str
    source: str
    verdict: Verdict
    detail: str
    elsewhere: LatLon | None = None    # where the check says the claim belongs
    distance_km: float | None = None
    weight: float = 0.0

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "source": self.source,
            "verdict": str(self.verdict), "detail": self.detail,
            "distance_km": (round(self.distance_km, 1)
                            if self.distance_km is not None else None),
            "weight": round(self.weight, 3),
        }


@dataclass(frozen=True, slots=True)
class Verification:
    """Every check made in one run, and the constraints they produced."""

    checks: tuple[Check, ...] = field(default_factory=tuple)
    refutations_applied: int = 0

    @property
    def refuted(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.verdict is Verdict.REFUTED)

    @property
    def confirmed(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.verdict is Verdict.CONFIRMED)

    def describe(self) -> str:
        if not self.checks:
            return "nothing on the board could check a claim"
        return (f"{len(self.confirmed)} confirmed, {len(self.refuted)} refuted, "
                f"{len(self.checks) - len(self.confirmed) - len(self.refuted)} "
                f"unsupported; {self.refutations_applied} applied")

    def to_dict(self) -> dict:
        return {"checks": [c.to_dict() for c in self.checks],
                "refutations_applied": self.refutations_applied}


def tolerance_km(level: Level) -> float:
    """How far apart a claim and a check may be and still be the same answer."""
    return LEVEL_RADIUS_KM[level] * (1.0 + SLACK)


def _gazetteer_points(board: Board) -> list[tuple[str, LatLon, str, float]]:
    """Every place a name lookup found, with the strength it was worth.

    Read off the evidence records rather than by calling the tool again, so
    verification costs nothing and cannot quietly answer a different question
    than the one the run asked.
    """
    out = []
    for ev in board.evidence.values():
        if ev.source != "place_lookup" or not isinstance(ev.result, dict):
            continue
        for match in ev.result.get("matches", []):
            try:
                point = LatLon(float(match["lat"]), float(match["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            out.append((ev.id, point, match.get("display_name", ""), ev.max_strength))
    return out


def check_against_gazetteer(board: Board, claim: Claim) -> Check | None:
    """Does the claim's coordinate agree with where its names were found?

    A claim is refuted only when **every** match for **every** name looked up
    in this run is further away than the claim's level allows. One match
    landing near it is enough to clear it, because a run that looked up four
    names has three the claim was never about.
    """
    point = board.locate(claim)
    matches = _gazetteer_points(board)
    if point is None or not matches:
        return None

    limit = tolerance_km(claim.level)
    distances = [(haversine(point, p), p, label, strength)
                 for _, p, label, strength in matches]
    nearest, where, label, strength = min(distances, key=lambda d: d[0])

    if nearest <= limit:
        return Check(
            claim_id=claim.id, source="place_lookup", verdict=Verdict.CONFIRMED,
            detail=f"{label[:70]} is {nearest:.0f} km away, inside the "
                   f"{limit:.0f} km a {claim.level.label} claim allows",
            elsewhere=where, distance_km=nearest,
            weight=min(TRUST["place_lookup"], strength),
        )

    return Check(
        claim_id=claim.id, source="place_lookup", verdict=Verdict.REFUTED,
        detail=f"nothing this run looked up is within {limit:.0f} km of the "
               f"claim; nearest is {label[:60]} at {nearest:.0f} km",
        elsewhere=where, distance_km=nearest,
        weight=min(TRUST["place_lookup"], strength),
    )


def check_against_constraints(board: Board, claim: Claim) -> Check | None:
    """Do the constraints already on the board permit the claim's point?

    Reporting, not new arithmetic. `Board.confidence` already multiplies by
    admissibility, so this changes no number; it makes a silent multiplication
    into a line someone can read.
    """
    point = board.locate(claim)
    if point is None or not board.constraints:
        return None
    admits = board.admissibility(point)
    if admits >= 0.5:
        return Check(claim_id=claim.id, source="constraints",
                     verdict=Verdict.CONFIRMED,
                     detail=f"constraints admit this point at {admits:.2f}")
    return Check(
        claim_id=claim.id, source="constraints", verdict=Verdict.REFUTED,
        detail=f"constraints admit this point at only {admits:.2f}",
        weight=0.0,     # already priced into confidence; a second charge is double counting
    )


CHECKS = (check_against_gazetteer, check_against_constraints)


def verify(board: Board, *, checks=CHECKS) -> Verification:
    """Run every check against every claim and add what they refute.

    Refutations are applied after all checks have run, not during, so no check
    sees a refutation another one produced. Checks that could weaken each
    other's inputs mid-pass would make the outcome depend on the order they
    happen to be listed in.
    """
    results: list[Check] = []
    for claim in list(board.claims.values()):
        for check in checks:
            outcome = check(board, claim)
            if outcome is not None:
                results.append(outcome)

    applied = 0
    for outcome in results:
        if outcome.verdict is not Verdict.REFUTED or outcome.weight <= 0.0:
            continue
        claim = board.claims[outcome.claim_id]
        evidence = board.add_evidence(
            source="verify",
            summary=f"{outcome.source} refutes {claim.value!r}: {outcome.detail}",
            kind=EvidenceKind.TOOL,
            inputs={"claim": outcome.claim_id, "check": outcome.source},
            result=outcome.to_dict(),
            # A refutation reaches exactly as far as the claim it refutes. It
            # is not a statement about where the photograph is, so it must not
            # be citable as one by anything else.
            resolves_to=claim.level,
            max_strength=outcome.weight,
        )
        board.refute(claim.id, evidence.id, outcome.weight,
                     note=f"refuted by {outcome.source}")
        applied += 1

    return Verification(checks=tuple(results), refutations_applied=applied)
