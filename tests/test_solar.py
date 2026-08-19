"""Verify the solar solver by round trip: known place -> sun -> recover place.

The tool cannot yet be tested end to end on a photograph, because that needs the
sun's position read out of the image and no vision component exists. Round
tripping against the forward model is the stronger test anyway: it checks the
geometry across the whole planet and the whole year without any model in the
loop to blame.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from vestigo.tools.solar import (
    LatitudeBand,
    declination_deg,
    hemisphere_from_sun,
    latitude_constraint,
    sun_position,
)

UTC = timezone.utc


# --- the astronomy agrees with known values -------------------------------

@pytest.mark.parametrize(
    "when, expected",
    [
        (datetime(2024, 3, 20, 12, tzinfo=UTC), 0.0),    # March equinox
        (datetime(2024, 6, 21, 12, tzinfo=UTC), 23.44),  # June solstice
        (datetime(2024, 9, 22, 12, tzinfo=UTC), 0.0),    # September equinox
        (datetime(2024, 12, 21, 12, tzinfo=UTC), -23.44),  # December solstice
    ],
)
def test_declination_matches_the_seasons(when: datetime, expected: float) -> None:
    assert declination_deg(when) == pytest.approx(expected, abs=0.6)


def test_sun_is_overhead_at_the_tropic_on_the_solstice() -> None:
    """At local noon on the June solstice the sun stands at the zenith at 23.44N."""
    elevation, _ = sun_position(23.44, 0.0, datetime(2024, 6, 21, 12, 2, tzinfo=UTC))
    assert elevation == pytest.approx(90.0, abs=1.0)


def test_polar_night_gives_a_sun_below_the_horizon() -> None:
    elevation, _ = sun_position(-85.0, 0.0, datetime(2024, 6, 21, 12, tzinfo=UTC))
    assert elevation < 0


# --- the inverse solve recovers the latitude it started from --------------

def _round_trip(lat: float, lon: float, when: datetime):
    """Recover a constraint from the sun as seen at a known place and time."""
    elevation, azimuth = sun_position(lat, lon, when)
    if elevation < 5:
        return None  # sun too low to read reliably; excluded by design
    return latitude_constraint(elevation, azimuth, when, uncertainty_deg=0.0)


@pytest.mark.parametrize("lat", [-75, -55, -35, -15, 0, 15, 35, 55, 75])
@pytest.mark.parametrize("lon", [-150, -60, 0, 60, 150])
@pytest.mark.parametrize(
    "when",
    [
        datetime(2024, 3, 20, 10, tzinfo=UTC),
        datetime(2024, 6, 21, 14, tzinfo=UTC),
        datetime(2024, 9, 22, 8, tzinfo=UTC),
        datetime(2024, 12, 21, 16, tzinfo=UTC),
    ],
)
def test_inverse_recovers_latitude_worldwide(lat: float, lon: float, when: datetime) -> None:
    """Two-part pass condition, and both halves matter.

    Correctness: the constraint must contain the true latitude. Usefulness: it
    must be narrow enough to be worth having. A tool that always answers
    "somewhere between 20 and 60 north" is never wrong and never helps, so
    soundness alone is not a passing grade.
    """
    con = _round_trip(lat, lon, when)
    if con is None:
        pytest.skip("sun below the usable horizon")
    assert con.contains(lat), f"true latitude {lat} outside {con}"
    assert con.total_width_deg < 6, f"constraint too wide to be useful: {con}"


def test_uncertainty_widens_the_band_and_still_contains_the_truth() -> None:
    lat, lon = 41.45, -4.49  # one of the rural baseline images, in Spain
    when = datetime(2024, 5, 3, 12, 55, tzinfo=UTC)
    elevation, azimuth = sun_position(lat, lon, when)

    tight = latitude_constraint(elevation, azimuth, when, uncertainty_deg=1.0)
    loose = latitude_constraint(elevation, azimuth, when, uncertainty_deg=10.0)

    assert tight.contains(lat) and loose.contains(lat)
    assert loose.total_width_deg > tight.total_width_deg
    # A constraint has to be narrow enough to be worth having, not merely correct.
    assert tight.total_width_deg < 10


# --- the hemisphere call is the high value output -------------------------

@pytest.mark.parametrize(
    "lat, lon, when, expected",
    [
        (52.0, 0.0, datetime(2024, 6, 21, 12, tzinfo=UTC), "north"),   # England, summer
        (-35.0, -71.0, datetime(2024, 12, 21, 16, tzinfo=UTC), "south"),  # Chile, summer
        (20.45, -100.47, datetime(2024, 4, 20, 19, tzinfo=UTC), "north"),  # Mexico
    ],
)
def test_hemisphere_from_a_real_place(lat: float, lon: float, when: datetime, expected: str) -> None:
    elevation, azimuth = sun_position(lat, lon, when)
    assert elevation > 10, "test case needs the sun well clear of the horizon"
    assert hemisphere_from_sun(azimuth, elevation, when) == expected


def test_hemisphere_declines_to_answer_when_it_cannot_tell() -> None:
    june = datetime(2024, 6, 21, 12, tzinfo=UTC)
    assert hemisphere_from_sun(180.0, 3.0, june) == "unknown"   # sun too low
    assert hemisphere_from_sun(90.0, 45.0, june) == "unknown"   # due east
    assert hemisphere_from_sun(270.0, 45.0, june) == "unknown"  # due west


def test_hemisphere_declines_inside_the_tropics_when_ambiguous() -> None:
    """The Kenya case. Sun in the southern sky, observer in the south anyway.

    In December the subsolar latitude is 23.4 south, so an observer at 1.3 south
    is north of it and sees the sun to the south. That looks like the northern
    hemisphere and is not. The honest answer is that the sun cannot settle it.
    """
    december = datetime(2024, 12, 21, 9, tzinfo=UTC)
    elevation, azimuth = sun_position(-1.29, 36.82, december)
    assert hemisphere_from_sun(azimuth, elevation, december) == "unknown"


def test_mexico_and_kenya_separate_on_hemisphere_alone() -> None:
    """The failure this tool exists to prevent.

    Two runs of a vision model on the same photograph of semi-arid thornscrub
    returned Mexico once and Kenya the next, 14,970 km apart. The landscapes are
    interchangeable; the hemispheres are not.
    """
    when = datetime(2024, 4, 20, 19, tzinfo=UTC)
    mx_elev, mx_azim = sun_position(20.45, -100.47, when)
    ke_elev, ke_azim = sun_position(-1.29, 36.82, when)

    mx = hemisphere_from_sun(mx_azim, mx_elev, when)
    ke = hemisphere_from_sun(ke_azim, ke_elev, when)
    assert mx == "north"
    assert ke in ("south", "unknown")
    assert mx != ke


# --- the band is a constraint, and behaves like one ------------------------

def test_band_rejects_an_impossible_range() -> None:
    with pytest.raises(ValueError):
        LatitudeBand(low=40.0, high=10.0, hemisphere="north")


def test_band_reports_width_in_km() -> None:
    band = LatitudeBand(low=40.0, high=45.0, hemisphere="north")
    assert band.width_km == pytest.approx(556.6, abs=1.0)


def test_rejects_a_nonsensical_elevation() -> None:
    with pytest.raises(ValueError):
        latitude_constraint(120.0, 180.0, datetime(2024, 6, 21, 12, tzinfo=UTC))


def test_ambiguous_geometry_reports_two_bands_and_excludes_the_middle() -> None:
    """Side-side-angle ambiguity is real, so say so rather than average it away."""
    when = datetime(2024, 12, 21, 16, tzinfo=UTC)
    elevation, azimuth = sun_position(15.0, 0.0, when)
    con = latitude_constraint(elevation, azimuth, when, uncertainty_deg=0.0)

    assert con.contains(15.0)
    if con.is_ambiguous:
        # Whatever else it admits, it must still rule out the middle.
        assert con.excludes(0.0) or con.excludes(-45.0)
        assert con.total_width_deg < 20  # two narrow bands, not one wide one
