"""Tests for the observation layer.

The point of this module is deciding which readings are the same reading, so
most of these are about that. The rest check that a malformed extractor reply
raises rather than quietly dropping an observation, since a dropped observation
is a claim losing its support with nothing in the output to say so.
"""
import json

import pytest

from vestigo.board import Board, Level, Support
from vestigo.observe import (
    OBSERVATION_SCHEMA,
    SAME_OBJECT_IOU,
    Modality,
    Observation,
    ObservationSet,
    Region,
    attach_observations,
    parse_observations,
)

SIGN = Region(0.10, 0.10, 0.30, 0.20)
SIGN_AGAIN = Region(0.11, 0.11, 0.31, 0.21)     # the same sign, boxed slightly differently
VERGE = Region(0.60, 0.60, 0.90, 0.95)


# -- regions ---------------------------------------------------------------

def test_a_region_overlapping_itself_is_one():
    assert SIGN.iou(SIGN) == pytest.approx(1.0)


def test_regions_that_do_not_touch_score_zero():
    assert SIGN.iou(VERGE) == 0.0


def test_two_boxes_round_the_same_sign_overlap_heavily():
    assert SIGN.iou(SIGN_AGAIN) > SAME_OBJECT_IOU


def test_iou_is_symmetric():
    assert SIGN.iou(SIGN_AGAIN) == pytest.approx(SIGN_AGAIN.iou(SIGN))


def test_an_inverted_or_out_of_range_region_is_rejected():
    for bad in ((0.5, 0.1, 0.2, 0.9), (-0.1, 0.0, 0.5, 0.5), (0.0, 0.0, 1.5, 0.5)):
        with pytest.raises(ValueError):
            Region(*bad)


# -- the same-object test --------------------------------------------------

def test_two_readings_of_one_sign_are_the_same_object():
    a = Observation("o1", Modality.TEXT, "blue enamel street sign", SIGN)
    b = Observation("o2", Modality.TEXT, "the lettering is Spanish", SIGN_AGAIN)
    assert a.same_object_as(b)


def test_different_modalities_in_the_same_place_are_not():
    """A shop sign and the building behind it sit in the same box and are two
    separate pieces of evidence."""
    a = Observation("o1", Modality.TEXT, "shop fascia", SIGN)
    b = Observation("o2", Modality.ARCHITECTURE, "stuccoed facade", SIGN)
    assert not a.same_object_as(b)


def test_the_same_modality_somewhere_else_is_not():
    """Region alone would merge every tree in a forest."""
    a = Observation("o1", Modality.VEGETATION, "agave", SIGN)
    b = Observation("o2", Modality.VEGETATION, "agave", VERGE)
    assert not a.same_object_as(b)


def test_an_observation_with_no_region_cannot_be_matched():
    a = Observation("o1", Modality.TEXT, "a sign", None)
    b = Observation("o2", Modality.TEXT, "a sign", SIGN)
    assert not a.same_object_as(b)
    assert not b.same_object_as(a)


# -- linking ---------------------------------------------------------------

def build_set():
    s = ObservationSet()
    s.observe(Modality.TEXT, "blue enamel street sign", region=SIGN,
              text="CALLE MAYOR", certainty=0.9)
    s.observe(Modality.TEXT, "the lettering is Spanish", region=SIGN_AGAIN,
              certainty=0.8)
    s.observe(Modality.VEGETATION, "agave in the verge", region=VERGE, certainty=0.7)
    return s


def test_a_second_reading_of_one_object_is_linked_to_the_first():
    s = build_set()
    assert s["o2"].parent == "o1"
    assert s["o3"].parent is None


def test_groups_cluster_by_object():
    s = build_set()
    assert [[o.id for o in g] for g in s.groups()] == [["o1", "o2"], ["o3"]]
    assert len(s) == 3


def test_a_third_reading_joins_the_same_root_rather_than_chaining():
    s = build_set()
    s.observe(Modality.TEXT, "white capitals on blue", region=SIGN, certainty=0.6)
    assert s["o4"].parent == "o1"
    assert s.root_of("o4") == "o1"


def test_an_explicit_parent_is_respected():
    s = ObservationSet()
    s.observe(Modality.SKY, "long shadows to the left", region=VERGE)
    s.observe(Modality.SKY, "so the sun is low and to the right",
              region=SIGN, parent="o1")
    assert s.root_of("o2") == "o1"


def test_an_unknown_parent_is_an_error():
    s = ObservationSet()
    with pytest.raises(KeyError):
        s.observe(Modality.TEXT, "x", region=SIGN, parent="o99")


def test_a_duplicate_id_is_an_error():
    s = ObservationSet()
    s.add(Observation("o1", Modality.TEXT, "a", SIGN))
    with pytest.raises(ValueError):
        s.add(Observation("o1", Modality.TEXT, "b", VERGE))


def test_root_of_survives_a_cycle():
    """Nothing here builds one, and a hand-edited file could."""
    s = ObservationSet()
    s._by_id["o1"] = Observation("o1", Modality.TEXT, "a", SIGN, parent="o2")
    s._by_id["o2"] = Observation("o2", Modality.TEXT, "b", SIGN, parent="o1")
    assert s.root_of("o1") in {"o1", "o2"}


# -- what the board does with them -----------------------------------------

def test_two_readings_of_one_sign_count_once_on_the_board():
    """The rule the whole module exists to support. Without the link these two
    would look like independent corroboration and reach 0.75."""
    board = Board("t")
    attach_observations(board, build_set())
    claim = board.add_claim(Level.COUNTRY, "Mexico",
                            supports=[Support("e1", 0.5), Support("e2", 0.5)])
    assert board.confidence(claim) == pytest.approx(0.5)


def test_a_sign_and_a_plant_compound():
    board = Board("t")
    attach_observations(board, build_set())
    claim = board.add_claim(Level.COUNTRY, "Mexico",
                            supports=[Support("e1", 0.5), Support("e3", 0.5)])
    assert board.confidence(claim) == pytest.approx(0.75)


def test_evidence_ids_run_parallel_to_observation_ids():
    board = Board("t")
    written = attach_observations(board, build_set())
    assert [e.id for e in written] == ["e1", "e2", "e3"]
    assert board.evidence["e2"].derived_from == ("e1",)
    assert board.evidence["e3"].derived_from == ()


def test_the_record_keeps_the_modality_and_the_verbatim_text():
    board = Board("t")
    attach_observations(board, build_set())
    assert board.evidence["e1"].inputs["modality"] == "text"
    assert board.evidence["e1"].result["text"] == "CALLE MAYOR"
    assert board.evidence["e1"].kind == "observation"


# -- accessors -------------------------------------------------------------

def test_texts_are_verbatim_deduplicated_and_ordered():
    s = build_set()
    s.observe(Modality.TEXT, "the same sign again", region=SIGN, text="CALLE MAYOR")
    s.observe(Modality.ROAD, "route marker", region=VERGE, text="MEX 45")
    assert s.texts() == ["CALLE MAYOR", "MEX 45"]


def test_by_modality_filters():
    s = build_set()
    assert len(s.by_modality(Modality.TEXT)) == 2
    assert len(s.by_modality("vegetation")) == 1
    assert s.by_modality(Modality.SKY) == []


# -- validation ------------------------------------------------------------

def test_certainty_is_bounded():
    with pytest.raises(ValueError):
        Observation("o1", Modality.TEXT, "a", SIGN, certainty=1.5)


def test_an_observation_needs_a_description():
    with pytest.raises(ValueError):
        Observation("o1", Modality.TEXT, "   ", SIGN)


# -- the extractor contract ------------------------------------------------

def test_the_schema_demands_a_region():
    """An extractor that omits regions turns every duplicate reading into
    fresh corroboration, silently."""
    item = OBSERVATION_SCHEMA["properties"]["observations"]["items"]
    assert "region" in item["required"]
    assert "certainty" in item["required"]


def test_the_schema_lists_every_modality():
    listed = set(OBSERVATION_SCHEMA["properties"]["observations"]
                 ["items"]["properties"]["modality"]["enum"])
    assert listed == {str(m) for m in Modality}


def test_parse_links_duplicates_the_same_way():
    payload = {"observations": [
        {"modality": "text", "what": "street sign", "certainty": 0.9,
         "text": "CALLE MAYOR", "region": SIGN.to_dict()},
        {"modality": "text", "what": "Spanish lettering", "certainty": 0.8,
         "region": SIGN_AGAIN.to_dict()},
        {"modality": "vegetation", "what": "agave", "certainty": 0.7,
         "region": VERGE.to_dict()},
    ]}
    s = parse_observations(payload)
    assert len(s) == 3
    assert s["o2"].parent == "o1"
    assert s.texts() == ["CALLE MAYOR"]


def test_a_malformed_reply_raises_rather_than_dropping_the_observation():
    for payload in (
        {},
        {"observations": "not a list"},
        {"observations": [{"what": "no modality", "certainty": 1.0}]},
        {"observations": [{"modality": "text"}]},
        {"observations": [{"modality": "wingdings", "what": "x"}]},
        {"observations": ["not an object"]},
    ):
        with pytest.raises(ValueError):
            parse_observations(payload)


def test_a_missing_region_parses_but_can_never_be_matched():
    s = parse_observations({"observations": [
        {"modality": "text", "what": "a sign somewhere", "certainty": 0.5},
        {"modality": "text", "what": "another sign somewhere", "certainty": 0.5},
    ]})
    assert len(s.groups()) == 2


# -- persistence -----------------------------------------------------------

def test_a_set_round_trips_and_keeps_its_links():
    s = build_set()
    revived = ObservationSet.from_list(json.loads(json.dumps(s.to_list())))
    assert len(revived) == len(s)
    assert revived["o2"].parent == "o1"
    assert [[o.id for o in g] for g in revived.groups()] == \
           [[o.id for o in g] for g in s.groups()]


def test_adding_to_a_revived_set_does_not_reuse_an_id():
    s = ObservationSet.from_list(build_set().to_list())
    assert s.observe(Modality.ROAD, "yellow centre line", region=VERGE).id == "o4"


# -- how far an observation can locate a photograph -------------------------

def test_text_reaches_further_than_scenery():
    """Phase 0 measured why: nearly every street-level answer in the baseline
    came from reading something. Vegetation narrows a continent."""
    from vestigo.board import Board, Level
    board = Board("t")
    s = ObservationSet()
    s.observe(Modality.TEXT, "sign reading BAN KRUT", region=SIGN, text="BAN KRUT")
    s.observe(Modality.VEGETATION, "acacia scrub", region=VERGE)
    attach_observations(board, s)
    assert board.evidence["e1"].resolves_to is Level.DISTRICT
    assert board.evidence["e2"].resolves_to is Level.COUNTRY


def test_illegible_text_reaches_no_further_than_the_scene():
    """A sign nobody could read is a sign, not a place name."""
    from vestigo.board import Board, Level
    board = Board("t")
    s = ObservationSet()
    s.observe(Modality.TEXT, "a sign, too blurred to read", region=SIGN)
    attach_observations(board, s)
    assert board.evidence["e1"].resolves_to is Level.COUNTRY


def test_certainty_becomes_the_strength_ceiling():
    """Seeing something faintly cannot support a claim as strongly as seeing it
    clearly, whatever number gets written on the citation."""
    from vestigo.board import Board, Level, Support
    board = Board("t")
    s = ObservationSet()
    s.observe(Modality.VEGETATION, "possibly agave, hard to tell",
              region=VERGE, certainty=0.3)
    attach_observations(board, s)
    claim = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support("e1", 0.95)])
    assert claim.supports[0].strength == pytest.approx(0.3)


def test_a_point_claim_off_scenery_is_capped_to_country():
    """The failure this exists to stop: six point-level claims in the first
    agent run were backed by nothing that could locate a point."""
    from vestigo.board import Board, Level, Support
    board = Board("t")
    s = ObservationSet()
    s.observe(Modality.VEGETATION, "dry scrub", region=VERGE, certainty=0.9)
    attach_observations(board, s)
    claim = board.add_claim(Level.POINT, "a precise spot", supports=[Support("e1", 0.9)])
    assert claim.level is Level.COUNTRY
