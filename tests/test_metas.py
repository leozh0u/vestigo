"""Tests for the country-property constraints.

These exist because of what the eighth eval run found: a candidate scores as
prior times admissibility, the model's own guess is seeded at prior 1.0, and
constraints were the only thing that could push it down. Solar geometry was the
only one and it abstains on most points, so admissibility came out at 1.0 for
nearly everything and no tool could ever outrank the first guess.

So the property that matters here is not that a constraint is *correct*. It is
that it **discriminates** — that a wrong country scores materially below a right
one. A constraint that penalises everyone equally is worse than none, because it
looks like it is working.
"""
import pytest

from vestigo.board import Board, Level
from vestigo.geo import LatLon
from vestigo.metas import (
    LEFT_HAND_TRAFFIC,
    METAS,
    SCRIPTS,
    constraint_for,
    country_resolver,
)
from vestigo.tools.base import attach
from vestigo.tools.metas import MetaTool

TOKYO, LONDON, PARIS = LatLon(35.68, 139.69), LatLon(51.51, -0.13), LatLon(48.86, 2.35)
OSLO, DENVER, SANTIAGO = LatLon(59.91, 10.75), LatLon(39.74, -104.99), LatLon(-33.45, -70.67)
PACIFIC = LatLon(0.0, -150.0)


def fake_resolver(mapping):
    """A resolver with no boundary file behind it, for the pure-logic tests."""
    def resolve(point):
        for p, code in mapping:
            if abs(p.lat - point.lat) < 0.01 and abs(p.lon - point.lon) < 0.01:
                return code
        return None
    return resolve


@pytest.fixture(scope="module")
def resolve():
    """The real Natural Earth resolver, when the boundaries are on disk.

    They are a 4 MB download that scripts/fetch_boundaries.py fetches and
    .gitignore keeps out of the repository, so a fresh checkout does not have
    them and neither does CI. Without this the seven tests below do not fail —
    they *error*, which is louder, less informative, and turns the whole run red
    over a missing input rather than a broken behaviour.

    Skipped with a reason instead. The rules these check are about geometry, and
    geometry needs the geometry.
    """
    try:
        return country_resolver()
    except FileNotFoundError as missing:
        pytest.skip(f"no boundary data: {missing.filename} "
                    "(run scripts/fetch_boundaries.py)")


# --------------------------------------------------------------------------
# The property the whole thing is for
# --------------------------------------------------------------------------

def test_a_constraint_separates_right_countries_from_wrong_ones(resolve):
    """The failure mode being guarded against is a constraint that scores every
    candidate the same, which cannot change a ranking and looks like it works."""
    c = constraint_for("traffic_left", resolver=resolve)
    assert c.admits(TOKYO) > c.admits(PARIS) * 5
    assert c.admits(LONDON) > c.admits(DENVER) * 5


def test_the_iso_codes_in_the_table_match_the_ones_the_resolver_returns(resolve):
    """The first version failed silently here: the resolver returned two-letter
    codes and the table held three-letter ones, so nothing ever matched and
    every country was penalised identically."""
    assert resolve(TOKYO) == "JPN"
    assert resolve(LONDON) == "GBR"
    assert resolve(TOKYO) in LEFT_HAND_TRAFFIC


def test_countries_natural_earth_labels_minus_99_still_resolve(resolve):
    """France, Norway, Kosovo and five others carry '-99' in ISO_A2 and ISO_A3.
    Reading those fields directly merges all eight into one country."""
    assert resolve(PARIS) == "FRA"
    assert resolve(OSLO) == "NOR"


def test_a_point_at_sea_makes_the_constraint_abstain(resolve):
    """A photograph taken on a ferry is not evidence against any country, and a
    constraint that cannot be evaluated must never quietly veto the answer."""
    c = constraint_for("traffic_left", resolver=resolve)
    assert resolve(PACIFIC) is None
    assert c.admits(PACIFIC) == 1.0


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

def test_left_and_right_hand_traffic_are_the_same_set_read_both_ways(resolve):
    left = constraint_for("traffic_left", resolver=resolve)
    right = constraint_for("traffic_right", resolver=resolve)
    assert left.admits(TOKYO) > right.admits(TOKYO)
    assert right.admits(PARIS) > left.admits(PARIS)


def test_the_road_marking_rule_is_trusted_less_than_the_traffic_rule():
    """Countries change marking standards and old paint outlives them. Driving
    side does not change without a national announcement."""
    assert METAS["centre_line_yellow"].weight < METAS["traffic_left"].weight


def test_every_script_maps_to_at_least_one_country():
    assert all(codes for codes in SCRIPTS.values())


def test_no_meta_claims_to_locate_anything_finer_than_a_country():
    """Left-hand traffic narrows the world and says nothing about which street."""
    assert all(m.reach is Level.COUNTRY for m in METAS.values())


def test_no_rule_is_certain():
    """A misread should cost ranking, not delete the answer."""
    assert all(0.0 < m.weight < 1.0 for m in METAS.values())


def test_an_unknown_meta_is_an_error_not_a_silent_no_op():
    with pytest.raises(KeyError, match="no meta named"):
        constraint_for("plug_socket_type_g")


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------

def test_three_visible_properties_can_narrow_the_world_to_one_country():
    r = MetaTool(resolver=fake_resolver([]))(
        traffic_side="left", scripts=["kana", "han"])
    assert r.ok
    assert r.value["narrowed_to"] == ["JPN"]
    assert len(r.constraints) == 3


def test_the_tool_proposes_no_candidates_ever():
    """A photograph showing left-hand traffic is not evidence for any one of
    the seventy-four countries that qualify."""
    r = MetaTool(resolver=fake_resolver([]))(traffic_side="left")
    assert r.candidates == ()


def test_nothing_may_cite_a_meta_as_evidence_for_a_place():
    """These constrain. Citing one as support for a location would let 'drives
    on the left' argue for Japan specifically."""
    r = MetaTool(resolver=fake_resolver([]))(traffic_side="left")
    assert r.max_strength == 0.0


def test_reporting_nothing_visible_is_a_result_not_a_failure():
    r = MetaTool(resolver=fake_resolver([]))()
    assert r.ok
    assert r.constraints == ()
    assert r.resolves_to is None


def test_an_unknown_script_is_rejected_by_the_schema():
    from vestigo.tools.base import ToolInputError
    with pytest.raises(ToolInputError):
        MetaTool(resolver=fake_resolver([]))(scripts=["elvish"])


def test_the_description_warns_against_entering_a_guess():
    """A value inferred from where the model already thinks it is will
    eliminate the right country as readily as the wrong one."""
    text = MetaTool.description.lower()
    assert "only from what you can actually see" in text
    assert "do not infer" in text


def test_constraints_reach_the_board_citing_the_tool_call(resolve):
    board = Board("t.jpg")
    result = MetaTool(resolver=resolve)(traffic_side="left")
    evidence = attach(board, result)
    assert len(board.constraints) == 1
    constraint = next(iter(board.constraints.values()))
    assert evidence.id in constraint.evidence_ids


def test_a_meta_constraint_demotes_a_wrong_candidate_on_the_board(resolve):
    """End to end, and the reason any of this exists: the answer's ranking has
    to move."""
    board = Board("t.jpg")
    e = board.add_evidence("first_pass", "a street", resolves_to=Level.COUNTRY)
    board.add_candidate(PARIS, label="Paris", prior=1.0, origin="first_pass",
                        evidence_ids=(e.id,))
    board.add_candidate(TOKYO, label="Tokyo", prior=1.0, origin="first_pass",
                        evidence_ids=(e.id,))
    assert board.rank_candidates()[0].candidate.label in ("Paris", "Tokyo")

    attach(board, MetaTool(resolver=resolve)(traffic_side="left"))
    assert board.rank_candidates()[0].candidate.label == "Tokyo"
