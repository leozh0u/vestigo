"""Facts about countries that a photograph can reveal, as constraints.

The eighth eval run found that no tool has ever moved an answer, because a
candidate scores as `prior x admissibility`, the model's unaided guess is
seeded at prior 1.0, and constraints were the only thing that could push it
down. Solar geometry was the only constraint that existed and it abstains on
most points, so admissibility came out at 1.0 for nearly every candidate and
nothing could ever outrank the first guess.

This is the missing half. Not another tool that proposes a place, which would
measure flat for the same reason the last four did. A set of facts that
*eliminate* places.

## Why these and not "GeoGuessr metas" generally

Competitive players read camera generation, car blur, the Google car's shadow,
and where the coverage vehicle has driven. Those are artifacts of Street View,
not facts about the world, and this system's photographs are Flickr and
Mapillary. Learning them would be meta-gaming a game this project is not
playing.

What survives the move off Street View is the part that is true about the
place: which side people drive on, what script the signs use, what colour the
centre line is. Those are properties of countries, they are documented, and
they are checkable by anyone who doubts the table below.

## The asymmetry that makes these worth having

A frontier model already knows that Japan drives on the left. What it does not
do reliably is *act* on it: it will read left-hand traffic, say so in its
reasoning, and then answer with a right-hand-traffic country anyway, because
nothing forces the two to agree.

A constraint forces it. Left-hand traffic alone eliminates roughly 150
countries, and it does so by multiplying their admissibility toward zero rather
than by asking the model to remember. That is the difference between knowledge
and a check.

## Weights, and why none of them is 1.0

Each entry carries how sure the *table* is, which is separate from how sure the
reading is. Driving side is close to certain per country and the uncertainty is
almost entirely in whether the photograph shows it. Road marking colour is
messier: countries change standards, and older paint survives. A soft edge on
every constraint means a misread costs ranking rather than deleting the answer.
"""
from __future__ import annotations

import functools
import pathlib
from dataclasses import dataclass

from .board import Constraint, Level, RegionSet
from .geo import LatLon

BOUNDARIES = pathlib.Path("data/boundaries/ne_50m_admin_0_countries.geojson")


# --------------------------------------------------------------------------
# Resolving a point to a country
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _countries():
    """Natural Earth polygons, loaded once per process.

    Imported lazily. `ml/` is the only place that needs a heavy dependency
    tree, and `vestigo/` must stay importable on a machine with no ML stack.
    """
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from ml.admin_cells import load_countries
    return load_countries(BOUNDARIES)


def country_resolver():
    """A callable turning a coordinate into an ISO 3166 alpha-3 code.

    Returns None offshore, which makes `RegionSet` abstain rather than
    exclude. A photograph taken on a ferry is not evidence against any country.
    """
    from ml.admin_cells import country_of

    countries = _countries()

    def resolve(point: LatLon) -> str | None:
        hit = country_of(countries, point.lat, point.lon)
        return hit.iso if hit and hit.iso not in ("-99", "") else None

    return resolve


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

# Countries where traffic keeps left. The single most discriminative thing a
# photograph of a road can show: it cuts the world roughly in a 1:3 ratio and
# the fact never changes without a national announcement.
#
# Verifiable against any published list, which is the point of writing it out
# rather than asking a model to recall it.
LEFT_HAND_TRAFFIC = frozenset({
    "AIA", "ATG", "AUS", "BHS", "BGD", "BRB", "BMU", "BTN", "BWA", "BRN",
    "CYM", "CXR", "CCK", "COK", "CYP", "DMA", "TLS", "FLK", "FJI", "GRD",
    "GGY", "GUY", "HKG", "IND", "IDN", "IRL", "IMN", "JAM", "JPN", "JEY",
    "KEN", "KIR", "LSO", "MAC", "MWI", "MYS", "MDV", "MLT", "MUS", "MSR",
    "MOZ", "NAM", "NRU", "NPL", "NZL", "NIU", "NFK", "PAK", "PNG", "PCN",
    "WSM", "SYC", "SGP", "SLB", "ZAF", "LKA", "SHN", "KNA", "LCA", "VCT",
    "SUR", "SWZ", "TZA", "THA", "TON", "TTO", "TCA", "TUV", "UGA", "GBR",
    "VGB", "VIR", "ZMB", "ZWE",
})

# Scripts and where signage uses them. Deliberately not a language map: a
# photograph shows letterforms, not grammar, and several languages share a
# script. Sets are small because a script is only worth encoding when it is
# unmistakable to look at.
SCRIPTS: dict[str, frozenset[str]] = {
    "cyrillic": frozenset({"RUS", "UKR", "BLR", "BGR", "SRB", "MKD", "MNE",
                           "KAZ", "KGZ", "TJK", "MNG"}),
    "greek": frozenset({"GRC", "CYP"}),
    "hebrew": frozenset({"ISR"}),
    "arabic": frozenset({"SAU", "ARE", "QAT", "KWT", "BHR", "OMN", "YEM",
                         "JOR", "SYR", "IRQ", "EGY", "LBY", "TUN", "DZA",
                         "MAR", "SDN", "MRT", "IRN", "AFG", "PAK"}),
    "devanagari": frozenset({"IND", "NPL"}),
    "thai": frozenset({"THA"}),
    "lao": frozenset({"LAO"}),
    "khmer": frozenset({"KHM"}),
    "burmese": frozenset({"MMR"}),
    "han": frozenset({"CHN", "TWN", "HKG", "MAC", "SGP", "JPN"}),
    "kana": frozenset({"JPN"}),
    "hangul": frozenset({"KOR", "PRK"}),
    "georgian": frozenset({"GEO"}),
    "armenian": frozenset({"ARM"}),
    "ethiopic": frozenset({"ETH", "ERI"}),
    "sinhala": frozenset({"LKA"}),
    "tamil": frozenset({"IND", "LKA", "SGP", "MYS"}),
}

# Countries whose road centre line is normally yellow. Everywhere else it is
# usually white, which makes this useful in both directions. Weaker than the
# other two: standards change and old paint outlives them.
YELLOW_CENTRE_LINE = frozenset({
    "USA", "CAN", "MEX", "GTM", "BLZ", "SLV", "HND", "NIC", "CRI", "PAN",
    "COL", "VEN", "ECU", "PER", "BOL", "CHL", "ARG", "URY", "PRY", "BRA",
    "JPN", "KOR", "PHL", "IDN", "IND", "NPL", "LKA", "ZAF", "NZL",
})


@dataclass(frozen=True, slots=True)
class Meta:
    """One observable property, the countries it implies, and how sure the
    table is about the implication."""

    key: str
    description: str
    codes: frozenset[str]
    inside: bool
    weight: float
    reach: Level


# `weight` is confidence in the rule, not in the reading. A misread is the
# caller's problem and is priced by the soft edge on the constraint.
METAS: dict[str, Meta] = {
    "traffic_left": Meta(
        "traffic_left", "traffic keeps left", LEFT_HAND_TRAFFIC, True, 0.9,
        Level.COUNTRY),
    "traffic_right": Meta(
        "traffic_right", "traffic keeps right", LEFT_HAND_TRAFFIC, False, 0.9,
        Level.COUNTRY),
    "centre_line_yellow": Meta(
        "centre_line_yellow", "the centre line is yellow", YELLOW_CENTRE_LINE,
        True, 0.6, Level.COUNTRY),
    "centre_line_white": Meta(
        "centre_line_white", "the centre line is white", YELLOW_CENTRE_LINE,
        False, 0.5, Level.COUNTRY),
}

for _name, _codes in SCRIPTS.items():
    METAS[f"script_{_name}"] = Meta(
        key=f"script_{_name}",
        description=f"signage uses {_name} script",
        codes=_codes,
        inside=True,
        # A script on a sign is close to unmistakable, and the set it implies
        # is small. This is the strongest family in the table.
        weight=0.85,
        reach=Level.COUNTRY,
    )


def constraint_for(key: str, evidence_ids=(), resolver=None) -> Constraint:
    """Turn one observed property into a constraint on the answer."""
    if key not in METAS:
        raise KeyError(f"no meta named {key!r}. Known: {sorted(METAS)}")
    meta = METAS[key]
    return RegionSet(
        id="",
        description=(f"{meta.description}, so the answer is "
                     f"{'in' if meta.inside else 'not in'} "
                     f"{len(meta.codes)} countries"),
        weight=meta.weight,
        evidence_ids=tuple(evidence_ids),
        codes=meta.codes,
        inside=meta.inside,
        resolver=resolver if resolver is not None else country_resolver(),
    )


def describe_table() -> str:
    """The table as text, for the README and for anyone checking it."""
    lines = []
    for key, meta in sorted(METAS.items()):
        lines.append(f"{key:<22} {len(meta.codes):>3} countries  "
                     f"weight {meta.weight:.2f}  "
                     f"{'in' if meta.inside else 'not in'}")
    return "\n".join(lines)
