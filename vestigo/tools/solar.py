"""Solar geometry: recover latitude and hemisphere from the sun's position.

This is trigonometry, not a model. Given when a photograph was taken and where
the sun sits in it, the observer's latitude is determined by spherical geometry
and either checks out or does not.

It matters most where nothing else works. Text extraction needs signage, map
queries need mapped features, a learned classifier needs training images from
the region. Antarctica, the Sahara and the Amazon interior have none of those.
The sun behaves identically everywhere.

Two outputs, in order of how reliable they are:

  hemisphere  A binary. At local noon the sun stands due south in the northern
              hemisphere and due north in the southern, so it separates
              landscapes that are otherwise interchangeable across the equator:
              arctic from antarctic tundra, Canadian from Patagonian steppe, and
              the five mediterranean biomes from one another.

  latitude    A band, never a point. Width follows directly from how precisely
              the sun's position can be read off the image.

The output is deliberately a constraint rather than an estimate. Measurement
showed a model handed a correct solar band will pick a point inside it worse
than the guess it had already made from the image, so this returns something
that eliminates candidates instead of competing with them.

Angle conventions throughout: degrees, latitude positive north, longitude
positive east, azimuth clockwise from true north, elevation above the horizon.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

__all__ = [
    "Hemisphere",
    "LatitudeBand",
    "LatitudeConstraint",
    "declination_deg",
    "equation_of_time_min",
    "sun_position",
    "hemisphere_from_sun",
    "latitude_constraint",
]

Hemisphere = Literal["north", "south", "unknown"]

# Fitted Fourier series from NOAA's solar position algorithm. Good to about
# 0.2 degrees on declination, which is well inside the error of reading the
# sun's position off a photograph.
_DECL_COS = (0.006918, -0.399912, -0.006758, -0.002697)
_DECL_SIN = (0.0, 0.070257, 0.000907, 0.00148)
_EQT_COS = (0.000075, 0.001868, -0.014615)
_EQT_SIN = (0.0, -0.032077, -0.040849)


def _fractional_year_rad(when: datetime) -> float:
    """Angle around the orbit, in radians, for the NOAA series."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    yday = when.timetuple().tm_yday
    hours = when.hour + when.minute / 60 + when.second / 3600
    return 2 * math.pi / 365.0 * (yday - 1 + (hours - 12) / 24)


def declination_deg(when: datetime) -> float:
    """Sun's declination: the latitude directly beneath it, +-23.44 degrees."""
    g = _fractional_year_rad(when)
    rad = sum(c * math.cos(i * g) for i, c in enumerate(_DECL_COS)) + sum(
        s * math.sin(i * g) for i, s in enumerate(_DECL_SIN)
    )
    return math.degrees(rad)


def equation_of_time_min(when: datetime) -> float:
    """Minutes by which true solar time leads mean clock time."""
    g = _fractional_year_rad(when)
    return 229.18 * (
        sum(c * math.cos(i * g) for i, c in enumerate(_EQT_COS))
        + sum(s * math.sin(i * g) for i, s in enumerate(_EQT_SIN))
    )


def sun_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Forward model: where the sun is, seen from a known place and time.

    Returns (elevation, azimuth) in degrees. Exists to generate ground truth for
    testing the inverse solve, and to check a candidate location against an
    observation.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    decl = math.radians(declination_deg(when))
    phi = math.radians(lat)

    utc_min = when.hour * 60 + when.minute + when.second / 60
    true_solar_min = utc_min + equation_of_time_min(when) + 4 * lon
    hour_angle = math.radians(true_solar_min / 4 - 180)

    cos_zenith = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    elevation = 90.0 - math.degrees(zenith)

    sin_zenith = math.sin(zenith)
    if sin_zenith < 1e-9 or abs(math.cos(phi)) < 1e-9:
        # Sun at the zenith, or observer at a pole: azimuth is undefined.
        return elevation, 0.0

    # The leading minus puts azimuth clockwise from true north: without it the
    # sun comes out due north at noon in the northern hemisphere.
    cos_az = -(math.sin(phi) * math.cos(zenith) - math.sin(decl)) / (math.cos(phi) * sin_zenith)
    azimuth = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    # acos loses the sign; the hour angle says which side of the meridian.
    if math.sin(hour_angle) > 0:
        azimuth = 360.0 - azimuth
    return elevation, azimuth % 360.0


def _reproduces_azimuth(
    lat: float, elev_rad: float, azim_rad: float, decl_rad: float, tol_deg: float = 1.0
) -> bool:
    """Does a candidate latitude actually produce the azimuth that was observed?

    The elevation fixes the hour angle up to sign, and the hour angle fixes the
    azimuth. A root that satisfies the algebra but not this check is spurious.
    """
    phi = math.radians(lat)
    if abs(math.cos(phi)) < 1e-9 or abs(math.cos(decl_rad)) < 1e-9:
        return True  # degenerate at the poles; do not discard on a weak test

    cos_h = (math.sin(elev_rad) - math.sin(phi) * math.sin(decl_rad)) / (
        math.cos(phi) * math.cos(decl_rad)
    )
    if abs(cos_h) > 1:
        return False  # the sun never reaches that elevation from this latitude
    hour_angle = math.acos(cos_h)

    zenith = math.pi / 2 - elev_rad
    sin_z = math.sin(zenith)
    if sin_z < 1e-9:
        return True
    cos_az = -(math.sin(phi) * math.cos(zenith) - math.sin(decl_rad)) / (
        math.cos(phi) * sin_z
    )
    predicted = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))

    observed = math.degrees(azim_rad) % 360.0
    # acos folds east and west together, so accept either side of the meridian.
    for candidate in (predicted, 360.0 - predicted):
        if abs((candidate - observed + 180) % 360 - 180) <= tol_deg:
            return True
    return False


@dataclass(frozen=True, slots=True)
class LatitudeBand:
    """A latitude constraint. Eliminates candidates, does not estimate a point."""

    low: float
    high: float
    hemisphere: Hemisphere

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"empty band: {self.low} > {self.high}")

    @property
    def width_deg(self) -> float:
        return self.high - self.low

    @property
    def width_km(self) -> float:
        return self.width_deg * 111.32  # one degree of latitude, near enough

    def contains(self, lat: float) -> bool:
        return self.low <= lat <= self.high

    def __str__(self) -> str:
        def fmt(v: float) -> str:
            return f"{abs(v):.1f} {'N' if v >= 0 else 'S'}"

        return f"{fmt(self.low)} to {fmt(self.high)} ({self.width_deg:.1f} deg wide)"


def hemisphere_from_sun(
    azimuth_deg: float, elevation_deg: float, when: datetime
) -> Hemisphere:
    """Which hemisphere the observer is in, where the sun can settle it.

    The common shorthand, sun in the south means northern hemisphere, is only
    true outside the tropics. What the azimuth actually reveals is which side of
    the *subsolar latitude* the observer is on, and the subsolar latitude moves
    between 23.4 north and 23.4 south over the year. At 1.3 south in December
    the sun stands in the southern sky and the observer is still southern
    hemisphere.

    So the rule needs the declination:

        sun to the south  -> observer is north of the subsolar latitude
        sun to the north  -> observer is south of it

    That pins a hemisphere only when the subsolar latitude is on the far side of
    the equator, or on it. Otherwise the honest answer is that it cannot tell,
    and within the tropics it frequently cannot.
    """
    if elevation_deg < 10:
        return "unknown"  # low sun; the arc has not committed to a side yet
    decl = declination_deg(when)

    if 100 <= azimuth_deg <= 260:
        # Sun to the south, so the observer lies north of the subsolar latitude.
        return "north" if decl >= 0 else "unknown"
    if azimuth_deg <= 80 or azimuth_deg >= 280:
        # Sun to the north, so the observer lies south of the subsolar latitude.
        return "south" if decl <= 0 else "unknown"
    return "unknown"  # near due east or west: ambiguous by construction


@dataclass(frozen=True, slots=True)
class LatitudeConstraint:
    """One or more disjoint latitude bands, plus a hemisphere call.

    Usually one band. Solving for latitude from an elevation and an azimuth is
    the spherical form of the side-side-angle case, which is genuinely
    ambiguous, so some geometries admit a second latitude far from the first.
    Both are real: an observer at either one sees that sun on that date.

    Reporting both is the honest result and still eliminates everything between
    them. Other evidence, or the hemisphere call, decides which applies.
    """

    bands: tuple[LatitudeBand, ...]
    hemisphere: Hemisphere

    def contains(self, lat: float) -> bool:
        return any(b.contains(lat) for b in self.bands)

    @property
    def is_ambiguous(self) -> bool:
        return len(self.bands) > 1

    @property
    def total_width_deg(self) -> float:
        """How much latitude survives. Lower is a more useful constraint."""
        return sum(b.width_deg for b in self.bands)

    def excludes(self, lat: float) -> bool:
        return not self.contains(lat)

    def __str__(self) -> str:
        inner = " or ".join(str(b) for b in self.bands)
        return f"{inner} [{self.hemisphere}]"


def latitude_constraint(
    elevation_deg: float,
    azimuth_deg: float,
    when: datetime,
    *,
    uncertainty_deg: float = 5.0,
) -> LatitudeConstraint:
    """Invert the sun's position to a latitude constraint.

    Spherical trigonometry gives, for observer latitude phi:

        sin(declination) = sin(elevation) sin(phi) + cos(elevation) cos(azimuth) cos(phi)

    which is a sin(phi) + b cos(phi) = c, solvable in closed form. The band comes
    from evaluating that solve across the corners of the stated measurement
    uncertainty rather than by linearising, since the relation is not linear near
    the solstices.

    `uncertainty_deg` is how precisely the sun's elevation and azimuth can be
    read from the image. Five degrees is a fair default for a clear shadow.
    """
    if not -90 <= elevation_deg <= 90:
        raise ValueError(f"elevation out of range: {elevation_deg}")
    if uncertainty_deg < 0:
        raise ValueError("uncertainty must be non-negative")

    decl = math.radians(declination_deg(when))
    solutions: list[float] = []

    for d_elev in (-uncertainty_deg, 0.0, uncertainty_deg):
        for d_azim in (-uncertainty_deg, 0.0, uncertainty_deg):
            elev = math.radians(max(-90.0, min(90.0, elevation_deg + d_elev)))
            azim = math.radians(azimuth_deg + d_azim)

            a = math.sin(elev)
            b = math.cos(elev) * math.cos(azim)
            r = math.hypot(a, b)
            if r < 1e-12:
                continue
            ratio = math.sin(decl) / r
            if abs(ratio) > 1:
                continue  # geometry inconsistent with this date; no observer sees it

            # a sin(phi) + b cos(phi) = c has two roots. Both satisfy the
            # equation, so pick between them by forward verification rather
            # than by branch: only one generally reproduces the observed
            # azimuth. Near the poles the wrong root is off by a hemisphere.
            psi = math.atan2(b, a)
            base = math.asin(ratio)
            for phi in (base - psi, math.pi - base - psi):
                phi = math.atan2(math.sin(phi), math.cos(phi))
                if abs(phi) > math.pi / 2 + 1e-9:
                    continue
                lat = math.degrees(phi)
                if _reproduces_azimuth(lat, elev, azim, decl):
                    solutions.append(lat)

    if not solutions:
        raise ValueError("no latitude is consistent with that sun position and date")

    # Group the roots into contiguous bands. A gap wider than the measurement
    # slack means two genuinely separate solutions, not one spread.
    gap = max(2 * uncertainty_deg, 2.0)
    solutions.sort()
    groups: list[list[float]] = [[solutions[0]]]
    for value in solutions[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)

    hemisphere = hemisphere_from_sun(azimuth_deg, elevation_deg, when)
    # Always pad a little. A zero width band is not a constraint, and the solve
    # runs through trigonometry, so an exact root lands a hair off its own edge.
    pad = max(uncertainty_deg / 2, 0.01)
    bands = tuple(
        LatitudeBand(
            low=max(-90.0, min(g) - pad),
            high=min(90.0, max(g) + pad),
            hemisphere=hemisphere,
        )
        for g in groups
    )
    return LatitudeConstraint(bands=bands, hemisphere=hemisphere)
