"""The gazetteer tool: text off a sign, turned into places that carry it.

Every tool built so far tells the agent something it already knew. Solar
geometry rules out latitudes a frontier model rules out anyway; the classifier
guesses a region the model guesses better; the observation extractor is the
model reading its own image. Four eval runs measured the same flat line, and
the reason is structural rather than a bug: a scaffold around a model can only
win by supplying information the model does not hold.

A gazetteer holds exactly that. No model memorises where every bakery in
Oaxaca is. OpenStreetMap does, and it is free to ask.

## What the count is, and what it is not

The first version of this file set the granularity of the answer from how many
matches came back, on the reasoning that a name shared by four hundred streets
is country-level evidence and a name shared by one is a point. The reasoning is
right and the implementation was wrong, which a live call caught before any of
it was written up.

Searching for "Hauptstrasse", one of the most common street names in Germany,
returns **two** matches, both in Indiana. Nominatim is a geocoder: it ranks by
prominence and hands back the prominent ones. It does not enumerate the world,
and an individual German Hauptstrasse has almost no prominence. Reading "two
matches, 400 m apart" as "this name identifies a point" would have been the
precise error this project exists to avoid, dressed up as a measurement.

So the count is a lower bound on ambiguity and is reported as one. What sets
the granularity instead is `addresstype`: OpenStreetMap's own statement of what
kind of thing it matched. A country is a country, a road is a road, a fuel
station is a point. That is a fact from the data rather than an inference from
a ranking, and it is what `resolves_to` now reads.

The spread of the matches still gets a say, but only downward. If the prominent
matches for a name sit on two continents, nothing citing the top one is a
point-level fact however confidently OSM types it.

## Why there is no country filter

Nominatim will happily restrict a search to a country code, and offering that
would be the obvious convenience. It is left out on purpose.

The value of this tool is that it does not know what the model thinks. Hand it
the model's country guess and the result stops being independent evidence and
becomes an echo: the board would count the model's prior twice, once as a
first-pass claim and once as a lookup steered by it. `derived_from` exists to
catch that, but only when the correlation is recorded, and a filter buried in a
tool input is a correlation nobody records. Constraints narrow candidates
downstream, which is the right place for a country belief to act.

## The ceiling

Nothing here goes above 0.9. The tool can confirm a name exists at a place; it
cannot confirm the model read the sign correctly, and a misread name that
happens to match somewhere real is the failure mode this ceiling is for.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..board import Level
from ..geo import LatLon, haversine
from ..scoring import LEVEL_RADIUS_KM
from .base import CandidateProposal, Tool, ToolResult

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy asks for an identifying agent and at most one
# request a second. Both are conditions of using it for free, so both are met
# here rather than left to whoever runs the eval.
USER_AGENT = "vestigo/0.1 (photo geolocation research; github.com/leozh0u/vestigo)"
MIN_INTERVAL_S = 1.1
TIMEOUT_S = 20.0

# How many matches to ask for. Large enough to see a name's spread, small
# enough that one lookup stays one lookup.
LIMIT = 20

# The most any claim may lean on a name match. See the module docstring.
CEILING = 0.9

# What OpenStreetMap says it matched, mapped onto the board's ladder. This is
# the tool's main signal, so the mapping is explicit rather than clever: an
# unlisted type falls back to CITY, which is coarse enough to be safe and fine
# enough to be worth having.
ADDRESSTYPE_LEVEL: dict[str, Level] = {
    "country": Level.COUNTRY,
    "state": Level.REGION,
    "province": Level.REGION,
    "region": Level.REGION,
    "state_district": Level.REGION,
    "county": Level.REGION,
    "municipality": Level.CITY,
    "city": Level.CITY,
    "town": Level.CITY,
    "village": Level.CITY,
    "hamlet": Level.DISTRICT,
    "borough": Level.DISTRICT,
    "city_district": Level.DISTRICT,
    "district": Level.DISTRICT,
    "suburb": Level.DISTRICT,
    "neighbourhood": Level.DISTRICT,
    "quarter": Level.DISTRICT,
    "road": Level.DISTRICT,
    "railway": Level.DISTRICT,
    "postcode": Level.DISTRICT,
    "house": Level.POINT,
    "house_number": Level.POINT,
    "building": Level.POINT,
    "amenity": Level.POINT,
    "shop": Level.POINT,
    "office": Level.POINT,
    "tourism": Level.POINT,
    "leisure": Level.POINT,
    "man_made": Level.POINT,
    "historic": Level.POINT,
    "aeroway": Level.POINT,
}
FALLBACK_LEVEL = Level.CITY

_lock = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    """Hold the one-request-a-second line across threads."""
    global _last_call
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _search(name: str, limit: int = LIMIT) -> list[dict]:
    query = urllib.parse.urlencode({
        "q": name,
        "format": "jsonv2",
        "limit": limit,
        "addressdetails": 1,
    })
    req = urllib.request.Request(f"{NOMINATIM}?{query}",
                                 headers={"User-Agent": USER_AGENT})
    _throttle()
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode())


def level_for_spread(km: float) -> Level:
    """The finest level whose radius still contains every match.

    Distances are measured from the top match rather than from the centroid,
    because the top match is the one a claim would cite. The question is "how
    wrong could citing this be", and a centroid answers a different one.
    """
    for level in sorted(LEVEL_RADIUS_KM, reverse=True):
        if km <= LEVEL_RADIUS_KM[level]:
            return level
    return Level.CONTINENT


def level_for_type(row: dict) -> Level:
    """What OSM says the match is, as a granularity.

    `addresstype` first, since it is the normalised field. `category` second,
    which covers the tagging families (amenity, shop, tourism) that reach the
    same answer by a different route.
    """
    for key in ("addresstype", "category", "type"):
        value = (row.get(key) or "").lower()
        if value in ADDRESSTYPE_LEVEL:
            return ADDRESSTYPE_LEVEL[value]
    return FALLBACK_LEVEL


def _importance(row: dict) -> float:
    """Nominatim's own prominence score, defaulting low when absent.

    Derived largely from Wikipedia linkage, so it ranks a capital above a
    hamlet and knows nothing about which one is in this photograph. Used only
    to order and weight matches, never as a confidence.
    """
    try:
        return max(0.0, float(row.get("importance", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _point(row: dict) -> LatLon | None:
    try:
        return LatLon(float(row["lat"]), float(row["lon"]))
    except (KeyError, TypeError, ValueError):
        return None


class PlaceLookup(Tool):
    """Ask OpenStreetMap which places carry a name."""

    name = "place_lookup"
    version = "2"
    description = (
        "Look up a place name, business name, street name or landmark in "
        "OpenStreetMap and get back real-world locations that carry it. Use "
        "this for any text legible in the image: a shop sign, a street sign, a "
        "plaque, a bus destination board, a postcode. Give the text as "
        "written, in its own language and accents, and do not translate it. "
        "Include a town or city name if one is legible, because a bare street "
        "name matches almost nothing useful while a street plus a town matches "
        "a block. If the full text finds nothing, the tool retries with the "
        "most distinctive part on its own. Do not add a country or region you "
        "have inferred rather than read: a match found without your help is "
        "worth more than one found with it, and the search covers the whole "
        "world on purpose."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The text as it appears, not translated.",
            },
        },
        "required": ["name"],
    }

    # The gazetteer is a live service, but one that changes over months while
    # an eval is rerun over days, and rerunning the eval is the largest cost in
    # the project. Results are cached, and `version` is the lever for throwing
    # that away when it stops being true.
    deterministic = True

    # How many matches become candidates on the board. Past a handful, extra
    # candidates dilute ranking without adding a place anyone would name.
    max_candidates = 5

    def _run(self, name: str) -> ToolResult:
        text = name.strip()
        if not text:
            raise ValueError("name is empty")

        rows = _search(text)
        used = text
        # An over-specified query fails outright rather than degrading: the
        # bakery name alone matches two places, and the same name with its town
        # appended matches none. One retry on the leading segment recovers
        # that, and costs a request only when the first attempt found nothing.
        if not rows and "," in text:
            used = text.split(",", 1)[0].strip()
            if used and used != text:
                rows = _search(used)

        matches = [(row, pt) for row in rows if (pt := _point(row)) is not None]

        if not matches:
            # A real answer, and a useful one: a name absent from OSM is either
            # misread or too small to be mapped, and either way nothing should
            # lean on it.
            return self.result(
                value={"query": text, "searched": used, "count": 0, "matches": []},
                summary=f"no place in OpenStreetMap matches {text!r}",
                resolves_to=None,
                max_strength=0.0,
            )

        top_row, top_point = matches[0]
        spread = max(haversine(top_point, pt) for _, pt in matches)

        # Two ceilings, and the answer is the lower. What OSM matched sets the
        # finest this could be; how far apart the prominent matches sit stops
        # a well-typed match from claiming more than its neighbours allow.
        typed = level_for_type(top_row)
        spread_cap = level_for_spread(spread)
        level = Level(min(int(typed), int(spread_cap)))

        # How much of the name's prominence sits on the best match. One match
        # takes the whole ceiling; a name split evenly across twenty places
        # gives its best match a twentieth of it. Both numbers come out of the
        # returned set rather than out of a judgement about it.
        weights = [_importance(row) for row, _ in matches]
        total = sum(weights)
        share = weights[0] / total if total > 0 else 1.0 / len(matches)
        strength = CEILING * share

        candidates = tuple(
            CandidateProposal(
                point=pt,
                label=row.get("display_name", used)[:120],
                prior=(weights[i] / total) if total > 0 else 1.0 / len(matches),
            )
            for i, (row, pt) in enumerate(matches[:self.max_candidates])
        )

        trimmed = [
            {
                "display_name": row.get("display_name", ""),
                "addresstype": row.get("addresstype", ""),
                "category": row.get("category", ""),
                "type": row.get("type", ""),
                "country": (row.get("address") or {}).get("country", ""),
                "lat": pt.lat,
                "lon": pt.lon,
                "importance": _importance(row),
            }
            for row, pt in matches
        ]

        n = len(matches)
        countries = sorted({m["country"] for m in trimmed if m["country"]})
        saturated = " at least" if n >= LIMIT else ""
        where = (f" in {countries[0]}" if len(countries) == 1
                 else f" across {len(countries)} countries" if countries else "")
        summary = (
            f"{used!r} matches{saturated} {n} "
            f"{'place' if n == 1 else 'places'}{where}, best is a "
            f"{top_row.get('addresstype') or top_row.get('type') or 'place'}"
            f"{f' spread over {spread:.0f} km' if n > 1 else ''}, "
            f"which is {level.name.lower()}-level evidence"
        )

        return self.result(
            value={
                "query": text,
                "searched": used,
                "count": n,
                "count_is_lower_bound": n >= LIMIT,
                "spread_km": round(spread, 1),
                "countries": countries,
                "matches": trimmed,
            },
            summary=summary,
            candidates=candidates,
            resolves_to=level,
            max_strength=round(strength, 4),
        )
