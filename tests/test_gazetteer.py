"""Tests for the OpenStreetMap name lookup.

Nearly all of these replace the network call, because what is being tested is
the reading of a response rather than Nominatim's uptime, and a suite that
needs the internet is a suite people stop running. The one live test is opt-in.

The case worth reading is `test_a_common_street_name_does_not_become_a_point`.
The first version of this tool set granularity from the number of matches, and
a live call showed that "Hauptstrasse", one of the commonest street names in
Germany, comes back as two roads in Indiana. A geocoder ranks by prominence; it
does not count. That test is there so the reasoning cannot come back.
"""
import os

import pytest

from vestigo.board import Board, Level
from vestigo.geo import LatLon, haversine
from vestigo.tools import gazetteer
from vestigo.tools.base import attach
from vestigo.tools.gazetteer import CEILING, PlaceLookup, level_for_spread, level_for_type


def row(lat, lon, *, addresstype="town", importance=0.4, name="Somewhere",
        category="place", country="Testland"):
    return {
        "lat": str(lat), "lon": str(lon),
        "addresstype": addresstype, "category": category, "type": addresstype,
        "importance": importance, "display_name": name,
        "address": {"country": country},
    }


@pytest.fixture
def fake(monkeypatch):
    """Swap the network call for a scripted one, and record what was asked."""
    calls: list[str] = []
    box: dict[str, list] = {"rows": []}

    def _search(name, limit=gazetteer.LIMIT):
        calls.append(name)
        rows = box["rows"]
        return rows.pop(0) if rows and isinstance(rows[0], list) else rows

    monkeypatch.setattr(gazetteer, "_search", _search)
    return type("Fake", (), {"calls": calls, "box": box})


# --------------------------------------------------------------------------
# Granularity
# --------------------------------------------------------------------------

def test_what_osm_matched_sets_the_level():
    assert level_for_type(row(0, 0, addresstype="country")) is Level.COUNTRY
    assert level_for_type(row(0, 0, addresstype="state")) is Level.REGION
    assert level_for_type(row(0, 0, addresstype="town")) is Level.CITY
    assert level_for_type(row(0, 0, addresstype="road")) is Level.DISTRICT
    assert level_for_type(row(0, 0, addresstype="amenity")) is Level.POINT


def test_an_unknown_type_falls_back_to_city_rather_than_to_a_point():
    """Guessing coarse costs ranking. Guessing fine invents a coordinate."""
    assert level_for_type(row(0, 0, addresstype="wormhole")) is Level.CITY


def test_the_level_falls_back_through_category_when_addresstype_is_missing():
    r = {"lat": "0", "lon": "0", "category": "shop", "type": "bakery"}
    assert level_for_type(r) is Level.POINT


def test_spread_maps_onto_the_scoring_bands():
    assert level_for_spread(0.0) is Level.POINT
    assert level_for_spread(3.0) is Level.DISTRICT
    assert level_for_spread(100.0) is Level.REGION
    assert level_for_spread(9_000.0) is Level.CONTINENT


def test_spread_only_ever_lowers_the_level(fake):
    """A shop is a point-level object. Two shops on opposite sides of the
    world share a name and locate nothing finer than a continent."""
    fake.box["rows"] = [row(19.4, -99.1, addresstype="amenity", name="A"),
                        row(52.5, 13.4, addresstype="amenity", name="B")]
    result = PlaceLookup()(name="Cafe Central")
    assert result.ok
    assert result.resolves_to == int(Level.CONTINENT)


def test_a_common_street_name_does_not_become_a_point(fake):
    """The regression the live call caught. Two prominent matches 400 m apart
    is not evidence that only two exist, so nothing here may read a small count
    as precision: a road is district-level however few came back."""
    fake.box["rows"] = [row(39.3, -85.2, addresstype="road", name="Haupt Strasse"),
                        row(39.3, -85.2, addresstype="road", name="Haupt Strasse")]
    result = PlaceLookup()(name="Hauptstraße")
    assert result.resolves_to == int(Level.DISTRICT)


# --------------------------------------------------------------------------
# Strength
# --------------------------------------------------------------------------

def test_a_single_match_gets_the_whole_ceiling_and_no_more(fake):
    """0.9, not 1.0. The tool checks that a name exists somewhere, never that
    the model read the sign correctly."""
    fake.box["rows"] = [row(48.8, 2.3, addresstype="country", importance=0.98)]
    result = PlaceLookup()(name="France")
    assert result.max_strength == pytest.approx(CEILING)


def test_prominence_is_shared_out_among_the_matches(fake):
    fake.box["rows"] = [row(0, 0, importance=0.3, name="A"),
                        row(0.1, 0.1, importance=0.3, name="B"),
                        row(0.2, 0.2, importance=0.3, name="C")]
    result = PlaceLookup()(name="Springfield")
    assert result.max_strength == pytest.approx(CEILING / 3, abs=1e-3)


def test_matches_with_no_prominence_split_it_evenly(fake):
    """Nominatim omits importance for some objects. Dividing by zero there
    would be a crash; treating the top one as certain would be worse."""
    fake.box["rows"] = [row(0, 0, importance=0.0, name="A"),
                        row(0.01, 0.01, importance=0.0, name="B")]
    result = PlaceLookup()(name="Nowhere")
    assert result.max_strength == pytest.approx(CEILING / 2)


def test_a_name_that_matches_nothing_carries_no_strength(fake):
    fake.box["rows"] = []
    result = PlaceLookup()(name="Kwik-E-Mart Springfield")
    assert result.ok
    assert result.max_strength == 0.0
    assert result.resolves_to is None
    assert result.candidates == ()


# --------------------------------------------------------------------------
# Query handling
# --------------------------------------------------------------------------

def test_an_over_specified_query_retries_on_its_leading_segment(fake):
    """The bakery name alone matches two places; the same name with its town
    appended matches none. One retry recovers that."""
    fake.box["rows"] = [[], [row(19.9, -97.9, addresstype="shop", name="Panadería")]]
    result = PlaceLookup()(name="Panadería La Espiga de Oro, Zacatlán")
    assert result.ok
    assert fake.calls == ["Panadería La Espiga de Oro, Zacatlán",
                          "Panadería La Espiga de Oro"]
    assert result.value["searched"] == "Panadería La Espiga de Oro"


def test_a_query_without_a_comma_is_not_retried(fake):
    fake.box["rows"] = []
    PlaceLookup()(name="Nowhereville")
    assert fake.calls == ["Nowhereville"]


def test_an_empty_name_is_a_failed_result_not_a_crash():
    result = PlaceLookup()(name="   ")
    assert result.ok is False
    assert result.error


def test_the_tool_takes_no_country_hint():
    """Deliberate. A filter set from the model's own guess turns independent
    evidence into an echo of the prior, and nothing records the correlation."""
    props = PlaceLookup().input_schema["properties"]
    assert set(props) == {"name"}


def test_rows_without_coordinates_are_dropped_not_crashed_on(fake):
    fake.box["rows"] = [{"display_name": "broken"},
                        row(1.0, 1.0, name="fine")]
    result = PlaceLookup()(name="Mixed")
    assert result.ok
    assert result.value["count"] == 1


def test_a_full_result_set_is_reported_as_a_lower_bound(fake):
    fake.box["rows"] = [row(i * 0.01, 0, name=f"n{i}") for i in range(gazetteer.LIMIT)]
    result = PlaceLookup()(name="Common")
    assert result.value["count_is_lower_bound"] is True
    assert "at least" in result.summary


# --------------------------------------------------------------------------
# What reaches the board
# --------------------------------------------------------------------------

def test_matches_land_on_the_board_as_candidates_citing_the_lookup(fake):
    fake.box["rows"] = [row(51.5, -0.1, importance=0.6, name="A"),
                        row(48.9, 2.4, importance=0.2, name="B")]
    board = Board("test.jpg")
    result = PlaceLookup()(name="Victoria")
    evidence = attach(board, result)
    assert len(board.candidates) == 2
    for cand in board.candidates.values():
        assert evidence.id in cand.evidence_ids
    assert evidence.max_strength == result.max_strength


def test_no_more_than_five_candidates_reach_the_board(fake):
    fake.box["rows"] = [row(i * 0.01, 0, name=f"n{i}") for i in range(gazetteer.LIMIT)]
    result = PlaceLookup()(name="Common")
    assert len(result.candidates) == PlaceLookup.max_candidates


def test_the_tool_proposes_candidates_and_never_a_claim(fake):
    fake.box["rows"] = [row(0, 0)]
    board = Board("test.jpg")
    attach(board, PlaceLookup()(name="Anywhere"))
    assert board.candidates
    assert not board.claims


# --------------------------------------------------------------------------
# Live, opt-in
# --------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("VESTIGO_LIVE"),
                    reason="hits Nominatim; set VESTIGO_LIVE=1 to run")
def test_live_france_is_a_country():
    result = PlaceLookup()(name="France")
    assert result.ok
    assert result.resolves_to == int(Level.COUNTRY)
    top = result.value["matches"][0]
    assert haversine(LatLon(top["lat"], top["lon"]), LatLon(46.6, 2.4)) < 300
