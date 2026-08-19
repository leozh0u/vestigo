"""Scoring that can see the thing this project is for.

Distance error cannot. On the Bengaluru image the model answered at country
granularity, said so, and explained it was hedging because there was no legible
text or landmark. India was correct. Scored by distance that is a 502 km
failure, and scored by whether the claim it made was true it is a success. A
metric that punishes appropriate humility will drive the system towards
confident precision, which is the failure mode the whole design exists to
avoid.

So there are three things here, and none of them is a mean distance.

**Granularity-aware correctness.** A claim is right if the truth falls inside
the radius the claimed level implies. Claiming a country and landing 500 km
away is correct. Claiming a street and landing 500 km away is not. The radii
are the standard IM2GPS bands rather than new numbers, so a result here can
still be read next to published ones.

**Overclaim rate.** How often the system claims a finer level than it earned.
This is the specific failure to drive to zero, and it is not the same as being
inaccurate. Underclaiming is tracked separately and is not a failure, because
answering at country level and stopping is the design working.

**Calibration.** When it says city level at high confidence, how often is it
right? Phase 0 measured stated confidence and found high trustworthy, low
honest, and medium bimodal from 0.1 km to 1545 km. Turning that observation
into a number that can be tracked across runs is what this module is for.

One thing deliberately absent: any use of a mean. On this data the mean is
dominated by whichever run flipped continents, and the run-to-run noise is a
40 km median with a 14,951 km tail, so a mean says more about the tail than
about the system.
"""
from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .board import Level
from .geo import LatLon, haversine

# How close a claim at each level has to land to count as correct. These are
# the IM2GPS threshold bands, reused rather than invented so numbers here stay
# comparable with published ones.
#
# A radius is a stand-in for the real test, which is whether the point falls
# inside the named administrative boundary. Doing that properly needs a
# boundary lookup, and until there is one this over-credits a claim near a
# large country's edge and under-credits one in the middle of a small country.
LEVEL_RADIUS_KM: dict[Level, float] = {
    Level.CONTINENT: 2500.0,
    Level.COUNTRY: 750.0,
    Level.REGION: 200.0,
    Level.CITY: 25.0,
    Level.DISTRICT: 5.0,
    Level.POINT: 1.0,
}

# What the baseline runs wrote in their `granularity` field, mapped onto the
# board's levels. "street" is the board's DISTRICT: finer than a city, coarser
# than a defended coordinate.
GRANULARITY_ALIASES: dict[str, Level] = {
    "continent": Level.CONTINENT,
    "country": Level.COUNTRY,
    "region": Level.REGION,
    "state": Level.REGION,
    "province": Level.REGION,
    "city": Level.CITY,
    "town": Level.CITY,
    "district": Level.DISTRICT,
    "neighbourhood": Level.DISTRICT,
    "neighborhood": Level.DISTRICT,
    "street": Level.DISTRICT,
    "point": Level.POINT,
    "exact": Level.POINT,
}

# Stated confidence has no number attached to it, so comparing what was claimed
# against what happened needs one. These are the reading a downstream user would
# take from the words, and they are an assumption, not a measurement. Phase 5
# replaces them with values fitted to the calibration curve. Until then every
# calibration error computed against them inherits the assumption.
STATED_CONFIDENCE: dict[str, float] = {"high": 0.9, "medium": 0.6, "low": 0.3}


def parse_level(name: str | Level) -> Level:
    if isinstance(name, Level):
        return name
    key = name.strip().lower()
    if key not in GRANULARITY_ALIASES:
        raise ValueError(f"unknown granularity {name!r}")
    return GRANULARITY_ALIASES[key]


def achieved_level(error_km: float) -> Level | None:
    """The finest level this error would have been correct at.

    None when the error is too large even for a continent claim, which is the
    honest answer for a guess on the wrong side of the planet.
    """
    for level in sorted(LEVEL_RADIUS_KM, reverse=True):
        if error_km <= LEVEL_RADIUS_KM[level]:
            return level
    return None


def hit_at_level(level: Level | str, error_km: float) -> bool:
    """Was a claim at this level correct."""
    return error_km <= LEVEL_RADIUS_KM[parse_level(level)]


@dataclass(frozen=True, slots=True)
class Scored:
    """One answer, judged on what it claimed rather than on distance alone."""

    subject: str
    claimed: Level
    error_km: float
    confidence: str | None = None
    source: str = ""

    @property
    def achieved(self) -> Level | None:
        return achieved_level(self.error_km)

    @property
    def hit(self) -> bool:
        return hit_at_level(self.claimed, self.error_km)

    @property
    def overclaimed(self) -> bool:
        """Claimed finer than it earned. The failure worth driving to zero."""
        return not self.hit

    @property
    def underclaimed(self) -> bool:
        """Claimed coarser than it earned.

        Not a failure. Answering at country level and stopping when that is all
        the evidence supports is the design working, and a metric that treats
        it as a miss would push the system back towards confident precision.
        """
        got = self.achieved
        return got is not None and got > self.claimed

    @property
    def levels_overclaimed(self) -> int:
        """How far the claim overshot, in levels. Zero if it did not."""
        if self.hit:
            return 0
        got = self.achieved
        return int(self.claimed) - int(got) if got else int(self.claimed)


def score(subject: str, claimed: Level | str, guess: LatLon, truth: LatLon,
          confidence: str | None = None, source: str = "") -> Scored:
    return Scored(subject=subject, claimed=parse_level(claimed),
                  error_km=haversine(truth, guess), confidence=confidence,
                  source=source)


# --------------------------------------------------------------------------
# Variance
# --------------------------------------------------------------------------

def spread_km(points: Sequence[LatLon]) -> float:
    """Distance between the two furthest points in a set.

    How far two runs of the same system on the same photograph are allowed to
    end up from each other. Phase 0 measured this at a 40 km median and a
    14,951 km maximum, which is why a single-sample eval cannot tell an
    improvement from a reroll, and why it is reported beside every median here.
    """
    if len(points) < 2:
        return 0.0
    return max(haversine(a, b)
               for i, a in enumerate(points) for b in points[i + 1:])


@dataclass(frozen=True, slots=True)
class RepeatSummary:
    """Several runs of one system on one photograph."""

    subject: str
    n: int
    median_error_km: float
    best_error_km: float
    worst_error_km: float
    spread_km: float
    hit_rate: float             # share of runs correct at the level they claimed

    @property
    def stable(self) -> bool:
        """Do the runs agree closely enough to be worth reading as one answer.

        The threshold is the level the median error would have earned, so a
        set of country-level answers is allowed to disagree by more than a set
        of street-level ones.
        """
        level = achieved_level(self.median_error_km)
        return self.spread_km <= LEVEL_RADIUS_KM[level] if level else False


def summarise_repeats(subject: str, runs: Sequence[Scored],
                      points: Sequence[LatLon]) -> RepeatSummary:
    """Fold N runs of one image into one row.

    Every eval run has to sample each image more than once. With single
    sampling the reported median moves 40 km on rerun and there is no way to
    tell a real improvement from a reroll.
    """
    if not runs:
        raise ValueError("no runs to summarise")
    errors = [r.error_km for r in runs]
    return RepeatSummary(
        subject=subject,
        n=len(runs),
        median_error_km=statistics.median(errors),
        best_error_km=min(errors),
        worst_error_km=max(errors),
        spread_km=spread_km(points),
        hit_rate=sum(1 for r in runs if r.hit) / len(runs),
    )


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Bin:
    """One confidence band, and what actually happened inside it."""

    label: str
    n: int
    stated: float               # what the label is taken to promise
    observed: float             # share correct at the level claimed
    median_error_km: float
    worst_error_km: float

    @property
    def gap(self) -> float:
        """Positive means overconfident, negative means underconfident."""
        return self.stated - self.observed

    @property
    def spread_km(self) -> float:
        return self.worst_error_km - self.median_error_km


def calibration_curve(scored: Iterable[Scored],
                      stated: dict[str, float] | None = None) -> list[Bin]:
    """Hit rate at the claimed level, per stated confidence band.

    The question the project exists to answer, in one table. When it says city
    level at high confidence, how often is it right?
    """
    stated = stated or STATED_CONFIDENCE
    rows = [s for s in scored if s.confidence]
    out = []
    for label in sorted({s.confidence for s in rows},
                        key=lambda c: stated.get(c, 0.0), reverse=True):
        group = [s for s in rows if s.confidence == label]
        errors = [s.error_km for s in group]
        out.append(Bin(
            label=label,
            n=len(group),
            stated=stated.get(label, float("nan")),
            observed=sum(1 for s in group if s.hit) / len(group),
            median_error_km=statistics.median(errors),
            worst_error_km=max(errors),
        ))
    return out


def expected_calibration_error(bins: Sequence[Bin]) -> float:
    """Average gap between promise and outcome, weighted by band size.

    Inherits the assumption in STATED_CONFIDENCE, since the words carry no
    number of their own. Useful for comparing two runs of this system against
    each other and not for comparing against anything outside it.
    """
    total = sum(b.n for b in bins)
    if not total:
        return float("nan")
    return sum(b.n * abs(b.gap) for b in bins) / total


def overshoot(row: Scored) -> float:
    """How far outside its promise an answer landed, as a multiple of the
    radius the claimed level implies.

    At or below 1 the claim was kept. At 6 the answer is six times further out
    than the level it claimed allows. Measuring against the claim rather than
    against the median is what makes this comparable across bands: a worst case
    of 30 km is excellent for a country claim and terrible for a street one,
    and a ratio to the median cannot tell those apart.

    The first version here was that ratio, worst over median in log10, which
    ranked the high confidence band as the most erratic of the three purely
    because its median was small. That is the same mistake as scoring a country
    claim by distance, one level up.
    """
    return row.error_km / LEVEL_RADIUS_KM[row.claimed]


def worst_overshoot(rows: Iterable[Scored]) -> float:
    """The worst broken promise in a set. 1.0 or below means none were broken."""
    factors = [overshoot(r) for r in rows]
    return max(factors) if factors else 0.0


@dataclass(frozen=True, slots=True)
class Report:
    """Everything worth saying about one set of answers."""

    n: int
    hit_rate: float
    overclaim_rate: float
    underclaim_rate: float
    median_error_km: float
    bins: tuple[Bin, ...]
    ece: float

    def describe(self) -> str:
        return (f"n={self.n}  correct at the level claimed {self.hit_rate:.0%}  "
                f"overclaimed {self.overclaim_rate:.0%}  "
                f"median {self.median_error_km:.1f} km")


def report(scored: Iterable[Scored]) -> Report:
    rows = list(scored)
    if not rows:
        raise ValueError("nothing to report on")
    bins = calibration_curve(rows)
    return Report(
        n=len(rows),
        hit_rate=sum(1 for s in rows if s.hit) / len(rows),
        overclaim_rate=sum(1 for s in rows if s.overclaimed) / len(rows),
        underclaim_rate=sum(1 for s in rows if s.underclaimed) / len(rows),
        median_error_km=statistics.median([s.error_km for s in rows]),
        bins=tuple(bins),
        ece=expected_calibration_error(bins),
    )
