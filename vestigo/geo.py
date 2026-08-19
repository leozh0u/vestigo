"""Geographic primitives.

Small and dependency free on purpose. The board and the constraint types both
need distances and band arithmetic, and neither should pull in a geo stack to
get them.

Longitude is the part that bites. A band running east from 170 to -170 is a
20 degree band across the dateline, not a 340 degree band the other way, so
every longitude comparison here goes through the same wrap-aware helper rather
than a plain `lo <= x <= hi`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class LatLon:
    """A point on the earth, in decimal degrees."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"latitude out of range: {self.lat}")
        if not -180.0 <= self.lon <= 360.0:
            raise ValueError(f"longitude out of range: {self.lon}")
        object.__setattr__(self, "lon", norm_lon(self.lon))

    def distance_km(self, other: "LatLon") -> float:
        return haversine(self, other)

    def as_tuple(self) -> tuple[float, float]:
        return (self.lat, self.lon)

    def to_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lon": self.lon}

    @classmethod
    def from_dict(cls, d: dict) -> "LatLon":
        return cls(float(d["lat"]), float(d["lon"]))

    def __str__(self) -> str:
        ns = "N" if self.lat >= 0 else "S"
        ew = "E" if self.lon >= 0 else "W"
        return f"{abs(self.lat):.4f}{ns} {abs(self.lon):.4f}{ew}"


def norm_lon(lon: float) -> float:
    """Fold a longitude into [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


def haversine(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in km.

    Same formula as eval/score.py. That copy stays where it is: the eval
    scripts are meant to run standalone against a results file with no package
    import, and a scoring script that quietly changes when the library changes
    is not a scoring script.
    """
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def lat_band_excess(lat: float, lo: float, hi: float) -> float:
    """Degrees by which `lat` falls outside [lo, hi]. Zero if inside."""
    if lo > hi:
        lo, hi = hi, lo
    if lat < lo:
        return lo - lat
    if lat > hi:
        return lat - hi
    return 0.0


def lon_band_width(lo: float, hi: float) -> float:
    """Width in degrees of the band running east from `lo` to `hi`."""
    w = (norm_lon(hi) - norm_lon(lo)) % 360.0
    return 360.0 if w == 0.0 else w


def lon_band_excess(lon: float, lo: float, hi: float) -> float:
    """Degrees by which `lon` falls outside the band running east from lo to hi.

    Zero if inside. Measured to the nearer edge, so a point 3 degrees west of
    the western edge scores 3 whichever way round the band was written.
    """
    width = lon_band_width(lo, hi)
    offset = (norm_lon(lon) - norm_lon(lo)) % 360.0
    if offset <= width:
        return 0.0
    return min(offset - width, 360.0 - offset)
