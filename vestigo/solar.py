"""Where the sun was, and what that rules out.

The one tool that either checks out or does not. No model in the loop and no
service to call, just the NOAA solar position algorithm, which is accurate to
about a hundredth of a degree between 1900 and 2100. Given an instant in UTC
and a coordinate it returns the sun's elevation and compass bearing as seen
from there.

The plan had this working backwards: measure a shadow, invert the equations,
get a latitude band. That is the harder half of the problem and it throws away
the azimuth, which is the half that carries longitude. Since a constraint is
asked `admits(point)` one point at a time, the equations can run forwards
instead. Compute where the sun would have been at the candidate, compare it to
what the photograph shows, and score. Forward is exact where inversion is
approximate, and it needs no algebra at all.

What falls out of that is cheaper than the plan assumed. The strongest single
constraint needs no shadow measurement and no sun in frame. It needs only that
the photograph was taken in daylight, which any model reads correctly. Fix the
instant and daylight alone rules out roughly half the planet, because the other
half is in the dark.

Reference: NOAA Global Monitoring Laboratory solar calculator, itself following
Meeus, "Astronomical Algorithms", 2nd edition.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone

from .board import Constraint, register_constraint, soft_score
from .geo import LatLon

# Elevation of the sun's centre at the boundaries astronomers use. Sunrise is
# at -0.833 rather than 0 because the sun's disc has a radius and the
# atmosphere bends its light over the horizon.
HORIZON_DEG = -0.833
CIVIL_TWILIGHT_DEG = -6.0
NAUTICAL_TWILIGHT_DEG = -12.0


@dataclass(frozen=True, slots=True)
class SunPosition:
    """Where the sun is, seen from one place at one instant."""

    elevation_deg: float        # above the horizon, refraction included
    azimuth_deg: float          # compass bearing, 0 north, 90 east
    declination_deg: float      # latitude the sun is overhead, same for everyone
    hour_angle_deg: float       # 0 at local solar noon, +15 per hour after
    equation_of_time_min: float

    @property
    def is_daylight(self) -> bool:
        return self.elevation_deg > HORIZON_DEG

    def __str__(self) -> str:
        return f"elev {self.elevation_deg:+.1f} deg, bearing {self.azimuth_deg:.0f} deg"


def julian_day(when: datetime) -> float:
    """Julian day for a UTC instant. Meeus chapter 7."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    year, month = when.year, when.month
    day = (when.day
           + (when.hour + (when.minute + (when.second + when.microsecond / 1e6) / 60) / 60) / 24)
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (year + 4716))
            + math.floor(30.6001 * (month + 1))
            + day + b - 1524.5)


def _refraction(true_elevation_deg: float) -> float:
    """Atmospheric refraction in degrees, which lifts the sun near the horizon.

    Worth a couple of tenths of a degree at 5 degrees up and about half a
    degree at the horizon itself, which is why sunrise happens before the sun
    geometrically clears it.
    """
    te = true_elevation_deg
    if te > 85.0:
        return 0.0
    t = math.tan(math.radians(te))
    if te > 5.0:
        r = 58.1 / t - 0.07 / t**3 + 0.000086 / t**5
    elif te > -0.575:
        r = 1735.0 + te * (-518.2 + te * (103.4 + te * (-12.79 + te * 0.711)))
    else:
        r = -20.772 / t
    return r / 3600.0


def sun_position(point: LatLon, when: datetime) -> SunPosition:
    """The sun's elevation and bearing at `point` at the UTC instant `when`."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    jd = julian_day(when)
    t = (jd - 2451545.0) / 36525.0                      # Julian centuries since J2000

    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)

    m = math.radians(mean_anom)
    centre = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * m) * (0.019993 - 0.000101 * t)
              + math.sin(3 * m) * 0.000289)

    true_long = mean_long + centre
    omega = 125.04 - 1934.136 * t
    apparent_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    mean_obliquity = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    obliquity = math.radians(mean_obliquity + 0.00256 * math.cos(math.radians(omega)))

    declination = math.asin(math.sin(obliquity) * math.sin(math.radians(apparent_long)))

    # Equation of time: how far ahead or behind clock time the sun runs, from
    # the tilt of the axis and the eccentricity of the orbit. Up to 16 minutes,
    # which is four degrees of longitude, so it is not optional.
    y = math.tan(obliquity / 2) ** 2
    l0 = math.radians(mean_long)
    eq_time = 4.0 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * eccentricity * math.sin(m)
        + 4 * eccentricity * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * eccentricity * eccentricity * math.sin(2 * m)
    )

    minutes_utc = when.hour * 60 + when.minute + when.second / 60 + when.microsecond / 6e7
    true_solar_minutes = (minutes_utc + eq_time + 4.0 * point.lon) % 1440.0
    hour_angle = true_solar_minutes / 4.0 - 180.0
    if hour_angle < -180.0:
        hour_angle += 360.0

    lat = math.radians(point.lat)
    ha = math.radians(hour_angle)
    cos_zenith = min(1.0, max(-1.0,
                              math.sin(lat) * math.sin(declination)
                              + math.cos(lat) * math.cos(declination) * math.cos(ha)))
    zenith = math.acos(cos_zenith)
    true_elevation = 90.0 - math.degrees(zenith)

    denom = math.cos(lat) * math.sin(zenith)
    if abs(denom) > 1e-9:
        ratio = min(1.0, max(-1.0, (math.sin(lat) * cos_zenith - math.sin(declination)) / denom))
        a = math.degrees(math.acos(ratio))
        azimuth = (a + 180.0) % 360.0 if hour_angle > 0 else (540.0 - a) % 360.0
    else:
        # Directly under the sun, or at a pole, where bearing stops meaning much.
        azimuth = 180.0 if point.lat > 0 else 0.0

    return SunPosition(
        elevation_deg=true_elevation + _refraction(true_elevation),
        azimuth_deg=azimuth,
        declination_deg=math.degrees(declination),
        hour_angle_deg=hour_angle,
        equation_of_time_min=eq_time,
    )


def solar_noon_utc(point: LatLon, day: _date) -> datetime:
    """The UTC instant of local solar noon at `point`, on the given UTC date.

    Solar noon is when the hour angle is zero, which is 12:00 local apparent
    time less the equation of time and less four minutes per degree of
    longitude. The equation of time barely moves within a day, so one
    refinement pass converges to well under a second.

    Useful on its own, and it is what makes the forward model testable across
    the whole planet and the whole year: at solar noon the sun's elevation and
    bearing both have closed forms to check against.
    """
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    guess = midnight + timedelta(hours=12)
    for _ in range(2):
        eq_time = sun_position(point, guess).equation_of_time_min
        guess = midnight + timedelta(minutes=720.0 - eq_time - 4.0 * point.lon)
    return guess


def bearing_difference(a: float, b: float) -> float:
    """Smallest angle between two compass bearings, 0 to 180."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _parse_utc(value: str) -> datetime:
    """Accept the manifest's format and ISO 8601, both meaning UTC."""
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


# --------------------------------------------------------------------------
# Constraints
# --------------------------------------------------------------------------

@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class SolarElevation(Constraint):
    """The sun was this high at this instant, so the answer is where that holds.

    Daylight on its own is the cheap version and it is worth more than it
    sounds. Fix the instant and the half of the earth facing away from the sun
    is gone, which is what would have stopped the Mexico image being answered
    with Kenya.
    """

    kind = "solar_elevation"

    captured_utc: str
    lo_deg: float
    hi_deg: float
    soft_deg: float = 3.0
    # Whether the timestamp is UTC or a reading off a local clock. Getting this
    # wrong is not a small error: a local time treated as UTC is out by the
    # timezone offset, three hours for Argentina, which is 45 degrees of
    # longitude. That mistake made this constraint reject correct answers at
    # 0.03 on every IM2GPS image, because those carry local capture time and
    # the tool input was named for UTC.
    basis: str = "utc"

    def _instant(self, point: LatLon):
        when = _parse_utc(self.captured_utc)
        if self.basis != "local":
            return when
        # A local clock is roughly longitude over fifteen, so the same forward
        # calculation works once the candidate pays for its own offset. Weaker
        # than real UTC, because timezone borders and daylight saving move it
        # by an hour or more, which is what the softer edges are for.
        return when - timedelta(hours=round(point.lon / 15.0))

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        elevation = sun_position(point, self._instant(point)).elevation_deg
        if elevation < self.lo_deg:
            excess = self.lo_deg - elevation
        elif elevation > self.hi_deg:
            excess = elevation - self.hi_deg
        else:
            return 1.0
        return soft_score(excess, self.soft_deg)

    def _params(self) -> dict:
        return {"captured_utc": self.captured_utc, "lo_deg": self.lo_deg,
                "hi_deg": self.hi_deg, "soft_deg": self.soft_deg,
                "basis": self.basis}


@register_constraint
@dataclass(frozen=True, kw_only=True, slots=True)
class SolarAzimuth(Constraint):
    """The sun lay in this compass direction at this instant.

    This is the half that carries longitude, since the bearing of the sun turns
    fifteen degrees an hour and local solar time is what fixes it. It needs the
    camera heading and a reading of where the light comes from, both softer
    inputs than "is it daylight", so it should not be given a weight near one.
    """

    kind = "solar_azimuth"

    captured_utc: str
    bearing_deg: float
    tolerance_deg: float = 30.0
    soft_deg: float = 20.0
    basis: str = "utc"

    def raw_admits(self, point: LatLon | None) -> float | None:
        if point is None:
            return None
        when = _parse_utc(self.captured_utc)
        if self.basis == "local":
            when = when - timedelta(hours=round(point.lon / 15.0))
        sun = sun_position(point, when)
        if not sun.is_daylight:
            # No bearing to compare against in the dark. Leave that judgement
            # to the elevation constraint rather than double counting it.
            return None
        off = bearing_difference(sun.azimuth_deg, self.bearing_deg)
        return soft_score(off - self.tolerance_deg, self.soft_deg)

    def _params(self) -> dict:
        return {"captured_utc": self.captured_utc, "bearing_deg": self.bearing_deg,
                "tolerance_deg": self.tolerance_deg, "soft_deg": self.soft_deg,
                "basis": self.basis}
