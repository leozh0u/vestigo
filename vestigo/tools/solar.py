"""The solar tool.

Takes the instant the photograph was captured and what the light in it shows,
and returns constraints. It proposes no candidate locations, which is the point
of it: solar geometry cannot tell you where a photograph was taken, it can only
tell you where it was not.

The inputs are ordered by how reliably they can be read off an image. Whether a
photograph was taken in daylight is close to unmissable, so that constraint
carries almost full weight. How high the sun sits is a judgement, and which way
it lies needs the camera heading as well, so both of those get less.
"""
from __future__ import annotations

from ..board import Level
from ..solar import (
    HORIZON_DEG,
    NAUTICAL_TWILIGHT_DEG,
    SolarAzimuth,
    SolarElevation,
    _parse_utc,
)
from .base import Tool, ToolResult

# Elevation bands for the three readings a model can make about the height of
# the sun. They overlap on purpose, so a call made near a boundary costs
# ranking rather than deleting the answer.
ELEVATION_BANDS: dict[str, tuple[float, float]] = {
    "low": (HORIZON_DEG, 20.0),      # long shadows, light coming in sideways
    "mid": (15.0, 60.0),
    "high": (50.0, 90.0),            # short shadows, sun well up
}

LIGHTING_BANDS: dict[str, tuple[float, float]] = {
    "daylight": (HORIZON_DEG, 90.0),
    "twilight": (NAUTICAL_TWILIGHT_DEG, 6.0),
    "night": (-90.0, HORIZON_DEG),
}

# Where the sun is relative to where the camera points, as an offset in degrees
# from the camera heading.
RELATIVE_OFFSETS: dict[str, float] = {
    "front": 0.0,       # the scene is backlit, the sun is in or near the frame
    "back": 180.0,      # the scene is front-lit, the photographer's shadow leads
    "left": -90.0,
    "right": 90.0,
}

# How sure the tool is of each constraint, as opposed to how well a point
# satisfies it. Provisional until measured against annotated images, which is
# the next thing this tool needs. Day against night is close to unmissable; the
# other two rest on a judgement and a compass.
LIGHTING_WEIGHT = 0.97
ELEVATION_WEIGHT = 0.75
AZIMUTH_WEIGHT = 0.70


class SolarTool(Tool):
    """Rule out places where the sun could not have been where the photo says."""

    name = "solar_position"
    version = "1"
    description = (
        "Constrain where a photograph was taken using the position of the sun. "
        "Give the UTC capture time and what the light shows: whether it is "
        "daylight, how high the sun sits, and which way it lies relative to the "
        "camera. Returns constraints that rule out places where the sun could "
        "not have been in that position at that instant. Proposes no locations "
        "of its own, and is most useful on a photograph with no readable text "
        "or landmark, where it narrows the search rather than answering it."
    )
    deterministic = True
    input_schema = {
        "type": "object",
        "properties": {
            "captured_utc": {
                "type": "string",
                "description": (
                    "The capture instant, 'YYYY-MM-DD HH:MM:SS' or ISO 8601. "
                    "Pass it exactly as given and say which it is in time_basis. "
                    "Do not convert a local time to UTC yourself: that needs the "
                    "timezone, which needs the longitude, which is what this "
                    "tool is being asked to help find."
                ),
            },
            "time_basis": {
                "type": "string",
                "enum": ["utc", "local"],
                "description": (
                    "Whether that timestamp is UTC or a reading off a local "
                    "clock. A local time is still usable and gives a weaker "
                    "constraint, so say 'local' rather than declining to call "
                    "this tool."
                ),
            },
            "lighting": {
                "type": "string",
                "enum": ["daylight", "twilight", "night"],
                "description": "Whether the scene is lit by the sun, in twilight, or dark.",
            },
            "sun_elevation": {
                "type": "string",
                "enum": ["low", "mid", "high", "unknown"],
                "description": (
                    "How high the sun sits, from shadow length. 'low' is long "
                    "shadows near sunrise or sunset, 'high' is short shadows "
                    "with the sun well up. Say 'unknown' rather than guessing."
                ),
            },
            "camera_heading_deg": {
                "type": "number",
                "description": "Compass bearing the camera points, 0 north, 90 east.",
            },
            "sun_relative": {
                "type": "string",
                "enum": ["front", "back", "left", "right", "unknown"],
                "description": (
                    "Where the sun is relative to the camera, from shadow "
                    "direction. 'front' means it is in or near the frame and "
                    "the scene is backlit. Needs camera_heading_deg to be usable."
                ),
            },
        },
        "required": ["captured_utc", "lighting"],
    }

    def _run(
        self,
        captured_utc: str,
        lighting: str,
        sun_elevation: str = "unknown",
        camera_heading_deg: float | None = None,
        sun_relative: str = "unknown",
        time_basis: str = "utc",
    ) -> ToolResult:
        when = _parse_utc(captured_utc)          # raises if it will not parse
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")

        # A local clock is roughly longitude over fifteen, so the same forward
        # calculation works once each candidate pays for its own offset. Weaker
        # than real UTC, because timezone borders and daylight saving move it by
        # an hour or more, so the weights come down and the edges soften.
        #
        # Without this the tool was unusable on any photograph carrying local
        # time, which is every IM2GPS image. The model was right to decline
        # rather than convert, since converting needs the longitude it is trying
        # to find, and it declined on 93% of those runs.
        local = time_basis == "local"
        scale = 0.75 if local else 1.0
        slack = 2.0 if local else 1.0

        constraints = []
        notes = [] if not local else ["local clock"]

        lo, hi = LIGHTING_BANDS[lighting]
        constraints.append(SolarElevation(
            id="", description=f"{lighting} at {stamp} {time_basis}",
            weight=LIGHTING_WEIGHT * scale,
            captured_utc=stamp, lo_deg=lo, hi_deg=hi, soft_deg=3.0 * slack,
            basis=time_basis,
        ))
        notes.append(lighting)

        if sun_elevation in ELEVATION_BANDS:
            lo, hi = ELEVATION_BANDS[sun_elevation]
            constraints.append(SolarElevation(
                id="", description=f"sun {sun_elevation} at {stamp} {time_basis}",
                weight=ELEVATION_WEIGHT * scale,
                captured_utc=stamp, lo_deg=lo, hi_deg=hi, soft_deg=8.0 * slack,
                basis=time_basis,
            ))
            notes.append(f"sun {sun_elevation}")

        bearing = None
        if sun_relative in RELATIVE_OFFSETS and camera_heading_deg is not None:
            bearing = (camera_heading_deg + RELATIVE_OFFSETS[sun_relative]) % 360.0
            constraints.append(SolarAzimuth(
                id="", description=f"sun bearing near {bearing:.0f} deg at {stamp}",
                weight=AZIMUTH_WEIGHT * scale,
                captured_utc=stamp, bearing_deg=bearing,
                tolerance_deg=45.0 * slack, soft_deg=25.0 * slack,
                basis=time_basis,
            ))
            notes.append(f"sun to the {sun_relative}, bearing {bearing:.0f}")

        return self.result(
            value={
                "captured_utc": stamp,
                "lighting": lighting,
                "sun_elevation": sun_elevation,
                "time_basis": time_basis,
                "sun_bearing_deg": bearing,
                "constraints": len(constraints),
            },
            summary=f"{stamp} UTC, {', '.join(notes)}",
            constraints=tuple(constraints),
            # Solar geometry rules places out. It never rules one in, so no
            # claim may lean on it to reach past a country, and the constraints
            # it emits do the real work rather than this citation.
            resolves_to=Level.COUNTRY,
            max_strength=0.4,
        )
