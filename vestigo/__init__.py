"""Vestigo: work out where a photograph was taken, and say how sure you are.

The package is organised around `board.Board`. Tools produce evidence and
constraints, the board holds them, and the answer is whatever claim the
evidence supports at the finest granularity that clears its threshold.
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
)
from .geo import LatLon, haversine

__all__ = [
    "Board", "BoundingBox", "Candidate", "Claim", "Constraint", "Evidence",
    "EvidenceKind", "LatLon", "LatitudeBand", "Level", "LongitudeBand",
    "NearPoint", "RegionSet", "Resolution", "ScoredCandidate", "Support",
    "haversine",
]
