"""Tests for solar position and the constraints built on it.

The algorithm is checked against things that are true by definition rather than
against a table I would have to trust: the Julian day at the J2000 epoch, the
declination at the equinoxes and solstices, the elevation at local solar noon,
and the fact that the sun is as far below the horizon at a point's antipode as
it is above it here.

The Mexico case gets its own test, because it is the reason this tool was built
before the others.
"""
import json
from datetime import datetime, timezone

import pytest

from vestigo.board import Board, Constraint
from vestigo.geo import LatLon
from vestigo.solar import (
    HORIZON_DEG,
    SolarAzimuth,
    SolarElevation,
    _parse_utc,
    bearing_difference,
    julian_day,
    sun_position,
)
from vestigo.tools.base import ToolInputError, attach
from vestigo.tools.solar import SolarTool

QUERETARO = LatLon(20.450895, -100.467564)
NAIROBI = LatLon(-1.286389, 36.817223)
MEXICO_CAPTURE = "2024-04-20 21:35:52"      # straight out of data/manifest.json


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


# -- the algorithm ---------------------------------------------------------

def test_julian_day_at_the_j2000_epoch():
    assert julian_day(datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)) == 2451545.0


def test_a_naive_datetime_is_read_as_utc():
    assert julian_day(datetime(2000, 1, 1, 12, 0)) == 2451545.0


def test_declination_is_zero_at_the_equinoxes():
    for moment in ("2024-03-20 03:06", "2024-09-22 12:44"):
        decl = sun_position(LatLon(0.0, 0.0), utc(moment)).declination_deg
        assert abs(decl) < 0.01, moment


def test_declination_reaches_the_obliquity_at_the_solstices():
    june = sun_position(LatLon(0.0, 0.0), utc("2024-06-20 20:51")).declination_deg
    december = sun_position(LatLon(0.0, 0.0), utc("2024-12-21 09:21")).declination_deg
    assert june == pytest.approx(23.44, abs=0.01)
    assert december == pytest.approx(-23.44, abs=0.01)


def test_the_equation_of_time_stays_inside_its_known_range():
    """It runs from about -14 minutes in February to +16 in early November."""
    values = [sun_position(LatLon(0.0, 0.0), utc(f"2024-{m:02d}-15 12:00")).equation_of_time_min
              for m in range(1, 13)]
    assert min(values) > -15.0 and max(values) < 17.0
    assert max(values) - min(values) > 25.0     # it does move, a lot


def test_at_solar_noon_the_sun_is_due_south_from_the_northern_hemisphere():
    # 2024-04-20 at Greenwich. Solar noon is 12:00 less the equation of time.
    point = LatLon(51.5, 0.0)
    eqt = sun_position(point, utc("2024-04-20 12:00")).equation_of_time_min
    noon = datetime(2024, 4, 20, 12, 0, tzinfo=timezone.utc) - _minutes(eqt)
    sun = sun_position(point, noon)
    assert abs(sun.hour_angle_deg) < 0.2
    assert sun.azimuth_deg == pytest.approx(180.0, abs=0.5)


def _minutes(m):
    from datetime import timedelta
    return timedelta(minutes=m)


def test_noon_elevation_is_ninety_less_the_distance_to_the_declination():
    point = LatLon(51.5, 0.0)
    eqt = sun_position(point, utc("2024-04-20 12:00")).equation_of_time_min
    sun = sun_position(point, datetime(2024, 4, 20, 12, 0, tzinfo=timezone.utc) - _minutes(eqt))
    expected = 90.0 - abs(point.lat - sun.declination_deg)
    # Refraction lifts it a little, which is why this is not exact.
    assert sun.elevation_deg == pytest.approx(expected, abs=0.1)


def test_the_sun_is_as_far_down_at_the_antipode_as_it_is_up_here():
    when = _parse_utc(MEXICO_CAPTURE)
    here = sun_position(QUERETARO, when)
    antipode = sun_position(LatLon(-QUERETARO.lat, QUERETARO.lon + 180.0), when)
    assert antipode.elevation_deg == pytest.approx(-here.elevation_deg, abs=0.6)


def test_refraction_lifts_the_sun_near_the_horizon():
    """Sunrise happens before the sun geometrically clears the horizon."""
    from vestigo.solar import _refraction
    assert _refraction(0.0) == pytest.approx(0.48, abs=0.05)
    assert _refraction(45.0) < 0.02
    assert _refraction(89.0) == 0.0


def test_declination_does_not_depend_on_where_you_stand():
    when = _parse_utc(MEXICO_CAPTURE)
    a = sun_position(QUERETARO, when).declination_deg
    b = sun_position(NAIROBI, when).declination_deg
    assert a == pytest.approx(b, abs=1e-9)


def test_bearing_difference_wraps():
    assert bearing_difference(10.0, 350.0) == pytest.approx(20.0)
    assert bearing_difference(350.0, 10.0) == pytest.approx(20.0)
    assert bearing_difference(0.0, 180.0) == pytest.approx(180.0)


def test_parse_accepts_both_formats():
    a = _parse_utc("2024-04-20 21:35:52")
    b = _parse_utc("2024-04-20T21:35:52Z")
    c = _parse_utc("2024-04-20T21:35:52+00:00")
    assert a == b == c and a.tzinfo is timezone.utc


# -- the case the tool was built for ---------------------------------------

def test_mexico_is_in_daylight_and_kenya_is_in_the_dark_at_the_same_instant():
    """Phase 0 in one assertion.

    Two identical no-metadata runs put this photograph 14,951 km apart, in
    Mexico and then in Kenya. At the capture instant the sun is 47 degrees up
    over Queretaro and 79 degrees below the horizon over Nairobi. A photograph
    taken in daylight cannot have been taken in Kenya, and no shadow
    measurement is needed to say so.
    """
    when = _parse_utc(MEXICO_CAPTURE)
    mexico = sun_position(QUERETARO, when)
    kenya = sun_position(NAIROBI, when)
    assert mexico.elevation_deg == pytest.approx(47.2, abs=0.5)
    assert mexico.is_daylight
    assert kenya.elevation_deg < -70.0
    assert not kenya.is_daylight


# -- the constraints -------------------------------------------------------

def test_solar_elevation_admits_the_truth_and_rejects_the_night():
    c = SolarElevation(id="k1", description="daylight", weight=1.0,
                       captured_utc=MEXICO_CAPTURE, lo_deg=HORIZON_DEG, hi_deg=90.0)
    assert c.admits(QUERETARO) == 1.0
    assert c.admits(NAIROBI) == 0.0


def test_solar_elevation_abstains_without_a_point():
    c = SolarElevation(id="k1", description="daylight", captured_utc=MEXICO_CAPTURE,
                       lo_deg=HORIZON_DEG, hi_deg=90.0)
    assert c.admits(None) == 1.0


def test_a_soft_edge_penalises_a_near_miss():
    c = SolarElevation(id="k1", description="sun high", weight=1.0,
                       captured_utc=MEXICO_CAPTURE, lo_deg=50.0, hi_deg=90.0,
                       soft_deg=8.0)
    # The sun is 47.2 degrees up at Queretaro, so it misses a 50 degree floor
    # by under three degrees and should be marked down rather than deleted.
    assert 0.5 < c.admits(QUERETARO) < 1.0


def test_solar_azimuth_abstains_in_the_dark():
    """Nothing to compare a bearing against at night, and the elevation
    constraint has already ruled on that point. Scoring it twice would count
    one observation as two."""
    c = SolarAzimuth(id="k1", description="sun to the west", weight=1.0,
                     captured_utc=MEXICO_CAPTURE, bearing_deg=266.0)
    assert c.admits(QUERETARO) == 1.0
    assert c.admits(NAIROBI) == 1.0
    assert c.raw_admits(NAIROBI) is None


def test_solar_azimuth_rejects_a_bearing_that_does_not_fit():
    c = SolarAzimuth(id="k1", description="sun to the east", weight=1.0,
                     captured_utc=MEXICO_CAPTURE, bearing_deg=90.0,
                     tolerance_deg=45.0, soft_deg=25.0)
    # The sun bears 266 at Queretaro, which is 176 degrees off.
    assert c.admits(QUERETARO) == 0.0


def test_solar_constraints_round_trip_through_json():
    """They live outside board.py, so this also checks they registered."""
    for original in (
        SolarElevation(id="k1", description="daylight", weight=0.97,
                       captured_utc=MEXICO_CAPTURE, lo_deg=HORIZON_DEG, hi_deg=90.0),
        SolarAzimuth(id="k2", description="sun west", weight=0.7,
                     captured_utc=MEXICO_CAPTURE, bearing_deg=266.0),
    ):
        revived = Constraint.from_dict(json.loads(json.dumps(original.to_dict())))
        assert type(revived) is type(original)
        assert revived.admits(QUERETARO) == original.admits(QUERETARO)
        assert revived.admits(NAIROBI) == original.admits(NAIROBI)


# -- the tool --------------------------------------------------------------

def test_the_tool_proposes_no_locations():
    """Solar geometry cannot say where a photograph was taken, only where it
    was not, and the result should show that."""
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight")
    assert result.ok
    assert result.candidates == ()
    assert len(result.constraints) == 1


def test_each_reading_adds_its_own_constraint():
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight",
                         sun_elevation="mid", camera_heading_deg=94.5,
                         sun_relative="back")
    kinds = [c.kind for c in result.constraints]
    assert kinds == ["solar_elevation", "solar_elevation", "solar_azimuth"]
    assert result.value["sun_bearing_deg"] == pytest.approx(274.5)


def test_the_daylight_constraint_carries_more_weight_than_the_others():
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight",
                         sun_elevation="mid", camera_heading_deg=94.5,
                         sun_relative="back")
    lighting, elevation, azimuth = result.constraints
    assert lighting.weight > elevation.weight
    assert lighting.weight > azimuth.weight


def test_a_sun_direction_with_no_heading_produces_no_bearing():
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight",
                         sun_relative="back")
    assert [c.kind for c in result.constraints] == ["solar_elevation"]
    assert result.value["sun_bearing_deg"] is None


def test_night_inverts_the_constraint():
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="night")
    board = Board("t")
    attach(board, result)
    mx = board.add_candidate(QUERETARO, label="Queretaro")
    ke = board.add_candidate(NAIROBI, label="Nairobi")
    scored = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert scored[ke.id] == 1.0
    assert scored[mx.id] < 0.05


def test_a_bad_timestamp_comes_back_as_a_failed_result():
    result = SolarTool()(captured_utc="last tuesday", lighting="daylight")
    assert result.ok is False
    assert "ValueError" in result.error


def test_the_lighting_reading_is_required():
    with pytest.raises(ToolInputError):
        SolarTool()(captured_utc=MEXICO_CAPTURE)


def test_an_invented_lighting_value_is_rejected():
    with pytest.raises(ToolInputError):
        SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="dusky")


def test_the_mexico_case_end_to_end():
    """The tool, the board and the constraint together, on real metadata."""
    board = Board("rural_7ee09e498b")
    attach(board, SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight"))
    mx = board.add_candidate(QUERETARO, label="Queretaro", prior=0.5)
    ke = board.add_candidate(NAIROBI, label="Nairobi", prior=0.5)
    ranked = {s.candidate.id: s for s in board.rank_candidates()}
    assert ranked[mx.id].admissibility == 1.0        # the truth is untouched
    assert ranked[ke.id].admissibility == pytest.approx(0.03)
    assert ranked[mx.id].score > 0.95
