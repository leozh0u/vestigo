"""What several runs of one photograph agree on.

Every image is already run three times, and until now the samples were used
only to report how much the answer wobbled. The answer itself came from one of
them, chosen arbitrarily. That throws away the most useful thing three samples
give you.

## The number this exists for

One image in the eighth eval run returned answers **10,387 km apart** across
three samples. Each of the three was stated with a confidence. A caller reading
any one of them has no way to know the other two exist, let alone that they
disagreed by a quarter of the planet.

That is the tail, and the tail is the only axis on which this system can beat a
single API call. A frontier model's median is excellent and its worst cases are
catastrophic, and nothing in one response separates the two. Three responses
separate them for free.

## Agreement narrows, it never widens

Consensus can lower the level of an answer and can never raise it.

The temptation is obvious: three samples landing within two kilometres of each
other looks like precision worth claiming. It is not. The samples share an
image, a model and a prompt, so they are correlated in every way that matters,
and agreement between correlated draws is close to worthless as evidence. Two
people who read the same wrong newspaper are not two witnesses.

Disagreement is different, and asymmetric. Samples that scatter across a
continent prove that the evidence does not pin a continent, whoever said
otherwise. A refutation from a correlated source is still a refutation, because
it only takes one draw to show the answer was not determined.

So this promotes nothing. It takes the level the samples claimed and cuts it
down to the level they actually support.

## The medoid, not the centroid

The consensus point is the sample nearest to the others, not their average. The
average of two points on opposite sides of the world is in the middle of an
ocean neither sample proposed, and it would be reported as the answer.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .board import Level
from .geo import LatLon, haversine
from .scoring import LEVEL_RADIUS_KM


@dataclass(frozen=True, slots=True)
class SampleView:
    """One run, reduced to what consensus needs."""

    index: int
    point: LatLon | None
    level: Level | None
    value: str
    confidence: float

    @property
    def answered(self) -> bool:
        return self.point is not None and self.level is not None


@dataclass(frozen=True, slots=True)
class Consensus:
    """What the samples support together, which is never more than any of them.

    `level` is None when they agree on nothing, including when every sample
    declined. That is an answer: it says the evidence did not determine a
    location, which one sample on its own cannot tell you.
    """

    level: Level | None
    value: str
    point: LatLon | None
    agreement: float                  # share of answering samples in the cluster
    n_answered: int
    n_total: int
    spread_km: float                  # widest gap between any two answers
    demoted_from: Level | None = None
    note: str = ""
    samples: tuple[SampleView, ...] = field(default_factory=tuple)

    @property
    def unanimous(self) -> bool:
        return self.n_answered > 1 and self.agreement == 1.0

    def describe(self) -> str:
        if self.level is None:
            return (f"{self.n_answered}/{self.n_total} samples answered and agreed "
                    f"on nothing, spread {self.spread_km:.0f} km")
        head = (f"{self.value} ({self.level.label}) from "
                f"{self.agreement:.0%} of {self.n_answered} answering samples")
        return head + (f", demoted from {self.demoted_from.label}"
                       if self.demoted_from else "")

    def to_dict(self) -> dict:
        return {
            "level": self.level.label if self.level else None,
            "value": self.value,
            "lat": self.point.lat if self.point else None,
            "lon": self.point.lon if self.point else None,
            "agreement": round(self.agreement, 4),
            "n_answered": self.n_answered,
            "n_total": self.n_total,
            "spread_km": round(self.spread_km, 1),
            "demoted_from": self.demoted_from.label if self.demoted_from else None,
            "note": self.note,
        }


def _spread(points: list[LatLon]) -> float:
    """The widest gap between any two answers.

    The widest rather than the average, because the average hides exactly the
    case worth catching: two samples agreeing closely and a third on another
    continent averages out to something reassuring.
    """
    if len(points) < 2:
        return 0.0
    return max(haversine(a, b)
               for i, a in enumerate(points) for b in points[i + 1:])


def _largest_cluster(points: list[LatLon], radius_km: float) -> list[int]:
    """Indices of the biggest group of samples that sit within `radius_km` of
    one member, taking that member as the centre.

    Not a full clustering. With three or five samples, the sample with the most
    neighbours is the medoid and its neighbourhood is the group, and anything
    more elaborate would be machinery for a list that fits on one line. Ties go
    to the earlier sample so the result does not depend on dict ordering.
    """
    best: list[int] = []
    for i, centre in enumerate(points):
        near = [j for j, p in enumerate(points) if haversine(centre, p) <= radius_km]
        if len(near) > len(best):
            best = near
    return best


def consense(runs, *, majority: float = 0.5) -> Consensus:
    """Reduce several runs of one photograph to what they jointly support.

    Walks the levels from finest to coarsest and takes the first at which more
    than `majority` of the answering samples fall inside that level's radius of
    one of them. The level is then capped at the finest any single sample
    actually claimed, because agreement about where does not grant granularity
    the evidence never had.
    """
    views = [
        SampleView(
            index=i,
            point=r.best_point,
            level=r.answer.level if r.answer else None,
            value=r.answer.value if r.answer else "",
            confidence=(r.resolution.confidences.get(r.answer.id, 0.0)
                        if r.answer else 0.0),
        )
        for i, r in enumerate(runs)
    ]
    answering = [v for v in views if v.answered]

    if not answering:
        return Consensus(
            level=None, value="", point=None, agreement=0.0,
            n_answered=0, n_total=len(views), spread_km=0.0,
            note="no sample produced an answer", samples=tuple(views),
        )

    points = [v.point for v in answering]
    spread = _spread(points)

    if len(answering) == 1:
        only = answering[0]
        return Consensus(
            level=only.level, value=only.value, point=only.point,
            agreement=1.0, n_answered=1, n_total=len(views), spread_km=0.0,
            note="one sample answered, so there is nothing to check it against",
            samples=tuple(views),
        )

    # The finest level any sample claimed. Consensus cannot exceed it: three
    # samples that all said "Chile" support Chile however close their points
    # happen to sit, because none of them ever claimed more.
    claimed = max(v.level for v in answering)

    for level in sorted(LEVEL_RADIUS_KM, reverse=True):
        cluster = _largest_cluster(points, LEVEL_RADIUS_KM[level])
        share = len(cluster) / len(answering)
        if share <= majority:
            continue

        capped = Level(min(int(level), int(claimed)))
        # The member the others gathered around, and its own words for the
        # place. Picking the most confident member instead would let one loud
        # sample name somewhere the group never agreed on.
        centre = answering[_medoid_index(points, cluster)]

        note = ""
        demoted = None
        if capped < claimed:
            demoted = claimed
            note = (f"samples claimed {claimed.label} but agree only to "
                    f"{capped.label}, {spread:.0f} km apart at the widest")
        elif share < 1.0:
            note = f"{len(cluster)} of {len(answering)} samples agree"

        return Consensus(
            level=capped, value=centre.value, point=centre.point,
            agreement=share, n_answered=len(answering), n_total=len(views),
            spread_km=spread, demoted_from=demoted, note=note,
            samples=tuple(views),
        )

    return Consensus(
        level=None, value="", point=None, agreement=0.0,
        n_answered=len(answering), n_total=len(views), spread_km=spread,
        demoted_from=claimed,
        note=(f"samples disagree by {spread:.0f} km, which is wider than a "
              f"continent, so they support no answer at all"),
        samples=tuple(views),
    )


def _medoid_index(points: list[LatLon], among: list[int]) -> int:
    """Which member of `among` sits closest to the rest of them.

    The answer has to be a place a sample actually proposed. An average of two
    points on opposite sides of the world lands in an ocean neither sample
    named, and it would then be reported as the answer.
    """
    return min(among, key=lambda i: sum(haversine(points[i], points[j])
                                        for j in among))
