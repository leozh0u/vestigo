"""Tests for geocell construction.

The two things that matter are that clustering happens on the sphere rather
than in raw degrees, and that seeding does not let a lopsided training set
swallow the sparse regions. Mapillary coverage is heavily Europe and North
America, so a scheme that only works on evenly spread data does not work here.
"""
import json

import pytest

from ml.geocells import assign_cell, build, describe, haversine, load, save


def europe(n=300):
    return [(45.0 + (i % 13), -3.0 + (i % 23)) for i in range(n)]


def scattered():
    """Four continents, deliberately lopsided the way the real data is."""
    pts = [(45.0 + (i % 13), -3.0 + (i % 23)) for i in range(700)]       # Europe
    pts += [(30.0 + (i % 15), -120.0 + (i % 45)) for i in range(200)]    # N America
    pts += [(-35.0 + (i % 15), -60.0 + (i % 15)) for i in range(60)]     # S America
    pts += [(-30.0 + (i % 15), 20.0 + (i % 12)) for i in range(40)]      # Africa
    return pts


def test_no_points_no_cells():
    assert build([]) == []


def test_cells_cover_every_point():
    cells = build(scattered(), n_cells=40)
    assert sum(c.count for c in cells) == len(scattered())


def test_an_empty_cell_is_not_a_cell():
    cells = build(europe(50), n_cells=40)
    assert all(c.count > 0 for c in cells)


def test_you_cannot_ask_for_more_cells_than_points():
    assert len(build([(0.0, 0.0), (10.0, 10.0)], n_cells=50)) <= 2


def test_sparse_regions_still_get_a_cell():
    """Random seeding on a set that is two thirds European produces two thirds
    European cells and leaves a continent inside one enormous one. Furthest
    point seeding is what stops that."""
    cells = build(scattered(), n_cells=40)
    african = [c for c in cells if -35 < c.lat < -10 and 15 < c.lon < 35]
    south_american = [c for c in cells if -40 < c.lat < -15 and -65 < c.lon < -40]
    assert african, "Africa was swallowed"
    assert south_american, "South America was swallowed"


def test_clustering_happens_on_the_sphere_not_in_degrees():
    """Two points either side of the dateline are neighbours. In raw degrees
    they are 358 apart and land in different cells."""
    pts = [(65.0, 179.0)] * 20 + [(65.0, -179.0)] * 20 + [(0.0, 0.0)] * 20
    cells = build(pts, n_cells=2)
    near_dateline = [c for c in cells if abs(c.lat - 65.0) < 5]
    assert len(near_dateline) == 1
    assert near_dateline[0].count == 40


def test_a_cell_centroid_sits_among_its_members():
    cells = build(scattered(), n_cells=30)
    for c in cells:
        assert c.radius_km > 0
        assert -90 <= c.lat <= 90 and -180 <= c.lon <= 180


def test_assignment_picks_the_nearest_centroid():
    cells = build(scattered(), n_cells=40)
    cid = assign_cell(cells, -33.9, 18.4)                    # Cape Town
    chosen = next(c for c in cells if c.id == cid)
    nearest = min(cells, key=lambda c: haversine(-33.9, 18.4, c.lat, c.lon))
    assert chosen.id == nearest.id


def test_assignment_with_no_cells_is_none():
    assert assign_cell([], 0.0, 0.0) is None


def test_the_same_points_give_the_same_cells():
    """Deterministic, so a model trained yesterday still means something."""
    a, b = build(scattered(), n_cells=25), build(scattered(), n_cells=25)
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]


def test_more_cells_means_tighter_ones():
    """The median radius is the floor on how precise this can ever be, since a
    prediction resolves to a centroid."""
    coarse = build(scattered(), n_cells=10)
    fine = build(scattered(), n_cells=60)
    med = lambda cs: sorted(c.radius_km for c in cs)[len(cs) // 2]
    assert med(fine) < med(coarse)


def test_cells_round_trip(tmp_path):
    cells = build(scattered(), n_cells=12)
    path = tmp_path / "cells.json"
    save(cells, path)
    assert [c.to_dict() for c in load(path)] == [c.to_dict() for c in cells]
    assert json.loads(path.read_text())[0]["id"] == 0


def test_describe_reports_the_precision_floor():
    text = describe(build(scattered(), n_cells=20))
    assert "cells" in text and "radius km" in text
    assert describe([]) == "no cells"


def test_haversine_agrees_with_the_package_version():
    from vestigo.geo import LatLon, haversine as vh
    assert haversine(20.45, -100.47, -1.29, 36.82) == pytest.approx(
        vh(LatLon(20.45, -100.47), LatLon(-1.29, 36.82)), rel=1e-9)
