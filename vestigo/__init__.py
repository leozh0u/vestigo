"""Vestigo: work out where a photograph was taken, and say how sure you are.

The package is organised around `board.Board`. Tools produce evidence and
constraints, the board holds them, and the answer is whatever claim the
evidence supports at the finest granularity that clears its threshold.

Importing the package registers every constraint type, which is what lets a
saved board be read back. A constraint type defined in a module nobody imports
cannot be deserialized, so new ones belong in the import list below.
"""
from .board import (
    Board,
    BoundingBox,
    Candidate,
    Claim,
    Constraint,
    Evidence,
    EvidenceKind,
    LatitudeBand,
    Level,
    LongitudeBand,
    NearPoint,
    RegionSet,
    Resolution,
    ScoredCandidate,
    Support,
    register_constraint,
    soft_score,
)
from .geo import LatLon, haversine
from .solar import SolarAzimuth, SolarElevation, SunPosition, sun_position

__all__ = [
    "Board", "BoundingBox", "Candidate", "Claim", "Constraint", "Evidence",
    "EvidenceKind", "LatLon", "LatitudeBand", "Level", "LongitudeBand",
    "NearPoint", "RegionSet", "Resolution", "ScoredCandidate", "SolarAzimuth",
    "SolarElevation", "SunPosition", "Support", "haversine",
    "register_constraint", "soft_score", "sun_position",
]
