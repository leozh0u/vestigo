"""Geocells that respect borders.

The cells in `geocells.py` are clustered from the training points alone, which
puts the boundaries wherever the data happens to thin out. That is defensible
with no other information and it is not what the pictures look like. Road paint,
plate shapes, signage script, kerb profiles and which side of the road people
drive on all change at a national border and nowhere else, so a cell that
straddles one contains two visually different places and a classifier has to
learn the union of both.

PIGEON builds cells by ranking administrative divisions hierarchically, then
clustering and tessellating them. This is the same idea with one level: assign
every training point to its country, then split countries that hold too many
points and absorb ones that hold too few. Borders are never crossed by a split
and only crossed by a merge when a country has too little data to stand alone.

**Measured, this loses to clustering.** At a matched cell count, cells drawn
from borders scored 32.0% and a 1,157 km median against 36.0% and 903 km for
cells clustered from the data. Kept because the code is sound and the result is
worth having written down, and because it tests one level of hierarchy rather
than the ranked-and-tessellated scheme PIGEON describes, so it is evidence
against this simplification and not against the idea.

The likely reason is mechanical. Clustering minimises spread within a cell by
construction, so a centroid sits close to its members and a prediction that
resolves to a centroid lands nearer. A cell shaped like Argentina has a centroid
far from most of Argentina. Borders match what the pictures show; centroids
match where the answer goes, and the metric rewards the second.

Boundaries are Natural Earth 1:50m, public domain, fetched rather than vendored.

Pure standard library apart from the clustering already in geocells.py.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from .geocells import Cell, _sq, _to_latlon, _to_unit, haversine

BOUNDARIES = pathlib.Path("data/boundaries/ne_50m_admin_0_countries.geojson")


@dataclass(frozen=True, slots=True)
class Country:
    """One admin unit, with a bounding box so most tests are one comparison."""

    name: str
    iso: str
    rings: tuple                    # list of (exterior, holes) in lon/lat
    west: float
    south: float
    east: float
    north: float

    def may_contain(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north


def _iso(props: dict) -> str:
    """The country's ISO 3166 alpha-3 code, working around Natural Earth.

    Eight features, France and Norway among them, carry "-99" in both ISO_A2
    and ISO_A3. Anything reading those fields directly merges all eight into a
    single country called "-99", which is silent and wrong rather than loud and
    wrong.
    """
    for key in ("ISO_A3_EH", "ISO_A3", "ADM0_A3"):
        value = props.get(key)
        if value and value != "-99":
            return value
    return "??"


def load_countries(path: pathlib.Path | str = BOUNDARIES) -> list[Country]:
    data = json.loads(pathlib.Path(path).read_text())
    out = []
    for feature in data["features"]:
        props, geom = feature["properties"], feature.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        rings, xs, ys = [], [], []
        for poly in polys:
            exterior = poly[0]
            rings.append((exterior, poly[1:]))
            xs += [p[0] for p in exterior]
            ys += [p[1] for p in exterior]
        if not rings:
            continue
        out.append(Country(
            name=props.get("NAME") or props.get("ADMIN") or "?",
            # ISO_A3_EH first. Natural Earth stores "-99" in ISO_A2 and
            # ISO_A3 for eight entries including France, Norway and Kosovo,
            # and reading those fields directly collapses all eight into one
            # country. The _EH variant carries the real codes.
            iso=_iso(props),
            rings=tuple(rings),
            west=min(xs), south=min(ys), east=max(xs), north=max(ys),
        ))
    return out


def _in_ring(lon: float, lat: float, ring) -> bool:
    """Ray casting. The standard crossing-number test, written out because
    pulling in a geometry library for forty lines is not a trade worth making.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def country_of(countries: list[Country], lat: float, lon: float) -> Country | None:
    """Which country a coordinate is in, or None if nowhere is close.

    The bounding box check rejects almost every country in one comparison, so
    the expensive ray casting runs on a handful of candidates rather than 242.

    Falls back to the nearest country when no polygon contains the point. At
    1:50m the coastline is coarse enough that a road along a shore can land in
    the sea, and 4% of the training set did. Left alone they collected in one
    "unassigned" cell spanning 9,877 km, which is the opposite of what cells
    built on borders are for. A coastal point belongs to the coast it is on.
    """
    for c in countries:
        if not c.may_contain(lon, lat):
            continue
        for exterior, holes in c.rings:
            if _in_ring(lon, lat, exterior) and not any(
                    _in_ring(lon, lat, h) for h in holes):
                return c
    return _nearest_country(countries, lat, lon)


# Beyond this, a point is genuinely at sea rather than just off a coarse
# coastline, and forcing it into a country would be inventing a fact.
COAST_TOLERANCE_KM = 120.0


def _nearest_country(countries: list[Country], lat: float, lon: float) -> Country | None:
    best, best_km = None, COAST_TOLERANCE_KM
    for c in countries:
        # One cheap rejection first: a country whose box is far in degrees
        # cannot have a vertex within the tolerance.
        if (lon < c.west - 2 or lon > c.east + 2
                or lat < c.south - 2 or lat > c.north + 2):
            continue
        for exterior, _ in c.rings:
            for vx, vy in exterior:
                d = haversine(lat, lon, vy, vx)
                if d < best_km:
                    best, best_km = c, d
    return best


def build(points: list[tuple[float, float]], countries: list[Country],
          target_per_cell: int = 300, min_count: int = 40,
          iterations: int = 20) -> tuple[list[Cell], list[str], list[int]]:
    """Cells that never straddle a border unless a country is too small to hold one.

    A country holding more than `target_per_cell` points is split into as many
    cells as it can support, clustered on the sphere so the split follows where
    the imagery actually is. A country holding fewer than `min_count` is merged
    into its nearest neighbour, because a class with twenty examples is a place
    the head memorises rather than a region it learns.

    Returns the cells, the country each came from, and the indices of points
    dropped. Naming the country is what makes a prediction explainable as a
    place rather than as a number.

    Points with no country within the coastal tolerance are dropped rather than
    collected. They are photographs geotagged in open ocean, which is a broken
    geotag rather than a place, and pooling them produced a single cell
    spanning 13,019 km.
    """
    groups: dict[str, list[int]] = {}
    labels: dict[str, str] = {}
    dropped: list[int] = []
    for i, (lat, lon) in enumerate(points):
        c = country_of(countries, lat, lon)
        if c is None:
            dropped.append(i)
            continue
        groups.setdefault(c.iso, []).append(i)
        labels[c.iso] = c.name

    # Absorb the countries too thin to be their own class.
    while True:
        small = [k for k, m in groups.items() if len(m) < min_count]
        if not small or len(groups) < 2:
            break
        victim = min(small, key=lambda k: len(groups[k]))
        vc = _centroid([points[i] for i in groups[victim]])
        others = [k for k in groups if k != victim]
        target = min(others, key=lambda k: _sq(
            _to_unit(*vc), _to_unit(*_centroid([points[i] for i in groups[k]]))))
        groups[target] += groups.pop(victim)
        labels[target] = f"{labels[target]} + {labels.pop(victim)}"

    cells, origins = [], []
    for key, members in sorted(groups.items()):
        n_sub = max(1, len(members) // target_per_cell)
        subs = _split(members, points, n_sub, iterations)
        # A split can leave a thin piece. Fold it into its nearest sibling
        # rather than shipping a class the head would memorise. Same country
        # either way, so no border is crossed.
        while len(subs) > 1 and min(len(x) for x in subs) < min_count:
            small = min(subs, key=len)
            subs.remove(small)
            here = _to_unit(*_centroid([points[i] for i in small]))
            nearest = min(subs, key=lambda o: _sq(
                here, _to_unit(*_centroid([points[i] for i in o]))))
            nearest += small
        for sub in subs:
            lat, lon = _centroid([points[i] for i in sub])
            radius = max(haversine(lat, lon, *points[i]) for i in sub)
            cells.append(Cell(len(cells), lat, lon, len(sub), radius))
            origins.append(labels[key])
    return cells, origins, dropped


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    unit = [_to_unit(la, lo) for la, lo in pts]
    return _to_latlon(sum(u[0] for u in unit) / len(unit),
                      sum(u[1] for u in unit) / len(unit),
                      sum(u[2] for u in unit) / len(unit))


def _split(members: list[int], points, k: int, iterations: int) -> list[list[int]]:
    """Lloyd's on the sphere, inside one country. Never crosses the border,
    because it only ever sees points already inside it."""
    if k <= 1 or len(members) <= k:
        return [members]
    unit = {i: _to_unit(*points[i]) for i in members}
    centres = [unit[members[0]]]
    far = {i: _sq(unit[i], centres[0]) for i in members}
    while len(centres) < k:
        pick = max(members, key=lambda i: far[i])
        if far[pick] <= 0:
            break
        centres.append(unit[pick])
        far = {i: min(far[i], _sq(unit[i], centres[-1])) for i in members}

    assign = {i: 0 for i in members}
    for _ in range(iterations):
        moved = False
        for i in members:
            best = min(range(len(centres)), key=lambda c: _sq(unit[i], centres[c]))
            if best != assign[i]:
                assign[i], moved = best, True
        if not moved:
            break
        for c in range(len(centres)):
            group = [unit[i] for i in members if assign[i] == c]
            if group:
                centres[c] = (sum(g[0] for g in group) / len(group),
                              sum(g[1] for g in group) / len(group),
                              sum(g[2] for g in group) / len(group))
    out = [[i for i in members if assign[i] == c] for c in range(len(centres))]
    return [g for g in out if g]
