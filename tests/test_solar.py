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
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from vestigo.board import Board, Constraint
from vestigo.geo import LatLon
from vestigo.solar import (
    HORIZON_DEG,
    SolarAzimuth,
    SolarElevation,
    _parse_utc,
    _refraction,
    bearing_difference,
    julian_day,
    solar_noon_utc,
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


# -- swept over the planet and the year ------------------------------------
#
# The checks above pin the model at named instants. These sweep it, because a
# sign error or a hemisphere assumption can sit quietly inside a formula that
# is right at the one date anyone checked. Every one of these is an identity
# the geometry has to satisfy everywhere, so they need no reference values.

SWEEP_DATES = [date(2024, m, 15) for m in range(1, 13)]
SWEEP_LATS = [-80, -60, -45, -23, -10, 0, 10, 23, 45, 60, 80]
SWEEP_LONS = [-170, -100, -30, 0, 45, 120, 179]


def test_at_solar_noon_the_sun_is_due_south_or_due_north_by_the_declination():
    """The subtlety that makes hemisphere shorthand wrong inside the tropics.

    "Sun in the south means northern hemisphere" holds outside the tropics and
    fails inside them. What the bearing at noon actually reports is which side
    of the subsolar latitude you stand on, and that latitude swings 23.4
    degrees either way across the year. Swept over 132 place-dates so the rule
    is checked where it is easy and where it is not.
    """
    checked = 0
    for day in SWEEP_DATES:
        for lat in SWEEP_LATS:
            point = LatLon(lat, 0.0)
            noon = solar_noon_utc(point, day)
            sun = sun_position(point, noon)
            if abs(lat - sun.declination_deg) < 2.0:
                continue                 # sun overhead, bearing stops meaning much
            expected = 180.0 if lat > sun.declination_deg else 0.0
            assert bearing_difference(sun.azimuth_deg, expected) < 0.5, (
                f"{lat}N on {day}: bearing {sun.azimuth_deg:.1f}, declination "
                f"{sun.declination_deg:.1f}"
            )
            checked += 1
    assert checked > 100


def test_noon_elevation_matches_its_closed_form_everywhere():
    """Geometry and refraction together, to a hundredth of a degree.

    The closed form gives the true elevation. What `sun_position` reports is
    the apparent one, so the prediction is the closed form plus refraction, and
    checking against the closed form alone fails by exactly the refraction
    every time. Tightened to 0.01 rather than loosened, because with refraction
    included there is nothing left to absorb.
    """
    for day in SWEEP_DATES:
        for lat in SWEEP_LATS:
            point = LatLon(lat, 0.0)
            sun = sun_position(point, solar_noon_utc(point, day))
            true_elevation = 90.0 - abs(lat - sun.declination_deg)
            if true_elevation < 5.0:
                continue                 # refraction turns steep below this
            expected = true_elevation + _refraction(true_elevation)
            assert sun.elevation_deg == pytest.approx(expected, abs=0.01)


def test_solar_noon_lands_on_a_zero_hour_angle_at_every_longitude():
    for lon in SWEEP_LONS:
        point = LatLon(40.0, lon)
        sun = sun_position(point, solar_noon_utc(point, date(2024, 8, 19)))
        assert abs(sun.hour_angle_deg) < 0.02, lon


def test_the_sun_is_always_as_far_down_at_the_antipode_as_it_is_up_here():
    """True everywhere the sun is clear of the horizon at both ends.

    It stops being true at the terminator, and that is refraction rather than a
    fault in the geometry. See the test below, which pins the failure instead
    of hiding it.
    """
    when = _parse_utc(MEXICO_CAPTURE)
    checked = 0
    for lat in SWEEP_LATS:
        for lon in SWEEP_LONS:
            here = sun_position(LatLon(lat, lon), when)
            there = sun_position(LatLon(-lat, lon + 180.0), when)
            if min(abs(here.elevation_deg), abs(there.elevation_deg)) < 10.0:
                continue
            # Take refraction back off both ends. What is left is pure
            # geometry, and it cancels to five decimal places.
            a = here.elevation_deg - _refraction(here.elevation_deg)
            b = there.elevation_deg - _refraction(there.elevation_deg)
            assert a + b == pytest.approx(0.0, abs=0.005)
            checked += 1
    assert checked > 50


def test_refraction_breaks_the_antipode_symmetry_at_the_terminator():
    """Both ends of the terminator are lifted, so they no longer cancel.

    Worth a test rather than an exclusion, because the daylight constraint
    lives exactly here. Sunrise happens before the sun geometrically clears the
    horizon, and a constraint that used unrefracted elevations would call a
    place dark for the last few minutes in which it is demonstrably light.
    """
    when = _parse_utc(MEXICO_CAPTURE)
    sums = []
    for lat in range(-89, 90):
        for lon in range(-180, 180, 2):
            here = sun_position(LatLon(lat, lon), when)
            there = sun_position(LatLon(-lat, lon + 180.0), when)
            if max(abs(here.elevation_deg), abs(there.elevation_deg)) > 3.0:
                continue
            sums.append(here.elevation_deg + there.elevation_deg)
    assert len(sums) > 500
    # Every pair sums positive rather than to zero, because the atmosphere
    # lifts both ends of the terminator instead of cancelling.
    assert min(sums) > 0.3
    assert max(sums) < 1.1


def test_half_the_earth_is_lit_at_any_instant_of_the_year():
    """Not exactly half, because refraction and the sun's disc push the
    terminator out a little, which is why this is a band and not a point."""
    for day in SWEEP_DATES:
        when = datetime(day.year, day.month, day.day, 7, 43, tzinfo=timezone.utc)
        lit = total = 0.0
        for lat in range(-89, 90, 3):
            weight = math.cos(math.radians(lat))
            for lon in range(-180, 180, 6):
                total += weight
                if sun_position(LatLon(lat, lon), when).elevation_deg > HORIZON_DEG:
                    lit += weight
        assert 0.49 < lit / total < 0.53, f"{day}: {lit / total:.3f}"


def test_the_sun_peaks_at_solar_noon_and_falls_away_either_side():
    for lat in (-45, 0, 45):
        point = LatLon(lat, 0.0)
        noon = solar_noon_utc(point, date(2024, 8, 19))
        peak = sun_position(point, noon).elevation_deg
        for offset in (-180, -60, -20, 20, 60, 180):
            other = sun_position(point, noon + timedelta(minutes=offset)).elevation_deg
            assert other < peak, f"{lat}N, {offset} min from noon"


def test_solar_rules_places_out_without_ruling_one_in():
    """It emits constraints, and constraints eliminate. No claim may lean on
    the citation itself to reach past a country."""
    from vestigo.board import Board, Level, Support
    result = SolarTool()(captured_utc=MEXICO_CAPTURE, lighting="daylight")
    assert result.resolves_to == int(Level.COUNTRY)
    assert result.max_strength == pytest.approx(0.4)

    board = Board("t")
    ev = attach(board, result)
    claim = board.add_claim(Level.CITY, "Queretaro", supports=[Support(ev.id, 0.9)])
    assert claim.level is Level.COUNTRY
    assert claim.supports[0].strength == pytest.approx(0.4)
