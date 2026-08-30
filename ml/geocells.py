"""Geocells: chopping the world into the units a classifier predicts.

A classifier has to pick from a fixed list, so the first decision in the ML
half is what that list is. The obvious answer is a latitude and longitude grid,
and it is the wrong one. What a photograph shows changes at borders and not at
round numbers: road paint, plate shapes, signage script, plug sockets, kerb
profiles, the side of the road people drive on. A grid cuts through all of that
and puts two visually unrelated places in one cell while splitting one country
across four.

PIGEON builds cells from administrative boundaries. Their boundary data is not
public, and neither is anything else about their setup, so this builds cells
from the training points themselves instead. Regions with dense coverage get
small cells and empty regions get none, which is honest: a classifier cannot
predict a cell it has never seen an image from, and pretending otherwise turns
an absence of data into a confident wrong answer.

The cost of that choice, stated up front: coverage follows Mapillary, which is
heavily Europe and North America. Whole countries will have no cell at all, and
the writeup has to say which rather than quoting one accuracy number.

Pure standard library. Clustering a few thousand points does not need a
dependency.
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class Cell:
    """One region the classifier can predict, and where inside it to answer."""

    id: int
    lat: float                  # centroid, which is the point a prediction becomes
    lon: float
    count: int                  # training images that landed here
    radius_km: float            # how far the furthest of them sits from the centre

    def to_dict(self) -> dict:
        return {"id": self.id, "lat": self.lat, "lon": self.lon,
                "count": self.count, "radius_km": self.radius_km}

    @classmethod
    def from_dict(cls, d: dict) -> "Cell":
        return cls(int(d["id"]), float(d["lat"]), float(d["lon"]),
                   int(d["count"]), float(d["radius_km"]))


def haversine(a_lat, a_lon, b_lat, b_lon) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _to_unit(lat: float, lon: float) -> tuple[float, float, float]:
    """A point on the unit sphere.

    Clustering in raw degrees is wrong twice over: a degree of longitude is
    111 km at the equator and 20 km at 70 north, and the dateline splits
    neighbours by 360. Cartesian coordinates on the sphere have neither problem,
    and the mean of a set of them points at their centroid.
    """
    la, lo = math.radians(lat), math.radians(lon)
    return math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)


def _to_latlon(x: float, y: float, z: float) -> tuple[float, float]:
    norm = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / norm, y / norm, z / norm
    return math.degrees(math.asin(z)), math.degrees(math.atan2(y, x))


def build(points: list[tuple[float, float]], n_cells: int = 200,
          iterations: int = 25, seed: int = 20260822,
          min_count: int = 0) -> list[Cell]:
    """Cluster training coordinates into `n_cells` geocells.

    Lloyd's algorithm on the sphere, seeded deterministically so two runs give
    the same cells and a model trained yesterday still means something today.

    Seeding is furthest-point rather than random. Random seeds in a set that is
    two thirds European produce two thirds European cells and leave whole
    continents inside one enormous cell. Furthest-point spreads the initial
    centres over the occupied surface, so sparse regions still get their own
    cell even though they will hold few images.
    """
    if not points:
        return []
    n_cells = max(1, min(n_cells, len(points)))
    unit = [_to_unit(la, lo) for la, lo in points]

    # Furthest-point seeding, starting from a fixed index so it is repeatable.
    centres = [unit[seed % len(unit)]]
    far = [_sq(p, centres[0]) for p in unit]
    while len(centres) < n_cells:
        pick = max(range(len(unit)), key=lambda i: far[i])
        if far[pick] <= 0:
            break
        centres.append(unit[pick])
        far = [min(d, _sq(p, centres[-1])) for d, p in zip(far, unit)]

    assign = [0] * len(unit)
    for _ in range(iterations):
        moved = False
        for i, p in enumerate(unit):
            best = min(range(len(centres)), key=lambda c: _sq(p, centres[c]))
            if best != assign[i]:
                assign[i], moved = best, True
        if not moved:
            break
        for c in range(len(centres)):
            members = [unit[i] for i in range(len(unit)) if assign[i] == c]
            if members:
                centres[c] = (sum(m[0] for m in members) / len(members),
                              sum(m[1] for m in members) / len(members),
                              sum(m[2] for m in members) / len(members))

    groups = {}
    for c in range(len(centres)):
        members = [i for i in range(len(points)) if assign[i] == c]
        if members:                     # an empty cell is not a cell
            groups[c] = members

    if min_count > 1:
        groups = _absorb_small(groups, points, centres, min_count)

    cells = []
    for c in sorted(groups):
        members = groups[c]
        lat, lon = _to_latlon(*centres[c])
        radius = max(haversine(lat, lon, *points[i]) for i in members)
        cells.append(Cell(len(cells), lat, lon, len(members), radius))
    return cells


def _absorb_small(groups, points, centres, min_count: int):
    """Fold undersized cells into their nearest surviving neighbour.

    A cell holding one image is not a class, it is a place the classifier will
    memorise and never generalise from. Merging rather than discarding, because
    dropping the points would quietly shrink the training set and the discarded
    ones are exactly the sparse regions worth keeping.

    Smallest first, so a chain of thin cells collapses into one viable cell
    instead of each being pushed onto the next.
    """
    while True:
        small = [c for c, m in groups.items() if len(m) < min_count]
        if not small or len(groups) < 2:
            return groups
        victim = min(small, key=lambda c: len(groups[c]))
        others = [c for c in groups if c != victim]
        target = min(others, key=lambda c: _sq(centres[victim], centres[c]))
        groups[target] = groups[target] + groups.pop(victim)


def _sq(a, b) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def assign_cell(cells: list[Cell], lat: float, lon: float) -> int | None:
    """Which cell a coordinate belongs to. The nearest centroid."""
    if not cells:
        return None
    return min(cells, key=lambda c: haversine(lat, lon, c.lat, c.lon)).id


def save(cells: list[Cell], path: pathlib.Path | str) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([c.to_dict() for c in cells], indent=2) + "\n")


def load(path: pathlib.Path | str) -> list[Cell]:
    return [Cell.from_dict(d) for d in json.loads(pathlib.Path(path).read_text())]


def describe(cells: list[Cell]) -> str:
    """What the cell set looks like, which is worth reading before training.

    The number to watch is the median radius. It is the floor on how precise
    this classifier can ever be, since a prediction resolves to a centroid, and
    it will be far larger than the frontier model's median error.
    """
    if not cells:
        return "no cells"
    radii = sorted(c.radius_km for c in cells)
    counts = sorted(c.count for c in cells)
    mid = len(radii) // 2
    return (f"{len(cells)} cells, {sum(counts)} points\n"
            f"  radius km   median {radii[mid]:.0f}  min {radii[0]:.0f}  max {radii[-1]:.0f}\n"
            f"  per cell    median {counts[mid]}  min {counts[0]}  max {counts[-1]}")
