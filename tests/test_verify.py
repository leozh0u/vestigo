"""Tests for the refutation pass.

Everything before this step in a run builds. This is the only one that tries to
knock something down, and it exists because of where the errors actually are: a
frontier model's median on this data is 2.6 km and its tail holds 1,545 km,
7,400 km and 16,753 km, with nothing in the response separating them.

The behaviour these pin, in order of how much they matter:

  A refuted claim falls and its coarser parent survives. The first version
  expressed refutations as constraints on the point, which killed the correct
  country claim along with the wrong city one, turning a usable answer into no
  answer at all.

  A check that cannot reach a claim reports `unsupported`, which is not a mark
  against it. Absence of confirmation is not refutation.

  A weak source may not refute. The classifier is right a third of the time,
  and letting it overturn claims would replace one overconfident voice with two.
"""
import pytest

from vestigo.board import Board, Level, Support
from vestigo.geo import LatLon
from vestigo.verify import (
    TRUST,
    Verdict,
    check_against_constraints,
    check_against_gazetteer,
    tolerance_km,
    verify,
)


def board_with(claim_point, lookup_points, *, level=Level.CITY, strength=0.95):
    b = Board("t.jpg")
    e1 = b.add_evidence("first_pass", "a courthouse", kind="observation",
                        resolves_to=Level.POINT)
    b.add_candidate(claim_point, label="guess", prior=1.0,
                    origin="first_pass", evidence_ids=(e1.id,))
    e2 = b.add_evidence(
        "place_lookup", "a name was looked up",
        result={"matches": [{"lat": p.lat, "lon": p.lon, "display_name": n}
                            for p, n in lookup_points]},
        resolves_to=Level.POINT, max_strength=strength)
    b.add_claim(Level.COUNTRY, "United States",
                supports=(Support(e1.id, 0.9), Support(e2.id, 0.9)))
    b.add_claim(level, "Chestertown", parent="c1", point=claim_point,
                supports=(Support(e1.id, 0.9), Support(e2.id, 0.9)))
    return b


# --------------------------------------------------------------------------
# The behaviour the pass exists for
# --------------------------------------------------------------------------

def test_a_refuted_claim_falls_and_its_parent_survives():
    """The case that made the first design wrong. A claim that cannot defend a
    city can still defend a country, and the answer should degrade to the
    country rather than to nothing."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")])
    assert b.resolve().answer.level is Level.CITY
    verify(b)
    after = b.resolve()
    assert after.answer is not None
    assert after.answer.level is Level.COUNTRY


def test_a_confirmed_claim_is_left_alone():
    b = board_with(LatLon(39.21, -76.07), [(LatLon(39.22, -76.06), "Chestertown")])
    before = b.resolve().answer.level
    v = verify(b)
    assert not v.refuted
    assert v.refutations_applied == 0
    assert b.resolve().answer.level is before


def test_one_nearby_match_clears_a_claim_even_when_others_are_far():
    """A run that looked up four names has three the claim was never about.
    Refuting on the furthest would refute nearly everything."""
    b = board_with(LatLon(39.21, -76.07),
                   [(LatLon(41.88, -87.63), "Chicago"),
                    (LatLon(39.22, -76.06), "Chestertown"),
                    (LatLon(-33.9, 151.2), "Sydney")])
    check = check_against_gazetteer(b, b.claims["c2"])
    assert check.verdict is Verdict.CONFIRMED


def test_the_refutation_is_recorded_as_evidence_that_can_be_read():
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")])
    verify(b)
    written = [e for e in b.evidence.values() if e.source == "verify"]
    assert len(written) == 1
    assert "refutes" in written[0].summary
    assert ("refutation", "c2") in b.journal


def test_a_refutation_reaches_no_further_than_the_claim_it_refutes():
    """It is not a statement about where the photograph is, so nothing else may
    cite it as one."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")])
    verify(b)
    written = next(e for e in b.evidence.values() if e.source == "verify")
    assert written.resolves_to is Level.CITY
    assert written.max_strength <= TRUST["place_lookup"]


# --------------------------------------------------------------------------
# Tolerance
# --------------------------------------------------------------------------

def test_a_coarse_claim_gets_more_slack_than_a_fine_one():
    assert tolerance_km(Level.COUNTRY) > tolerance_km(Level.CITY)
    assert tolerance_km(Level.CITY) > tolerance_km(Level.POINT)


def test_a_city_claim_pinned_at_the_town_hall_is_not_refuted_by_a_match_at_the_station():
    """A checker that cannot tell those apart refutes everything."""
    b = board_with(LatLon(39.210, -76.070), [(LatLon(39.240, -76.100), "the station")])
    assert check_against_gazetteer(b, b.claims["c2"]).verdict is Verdict.CONFIRMED


def test_the_same_gap_refutes_a_point_claim_and_clears_a_country_claim():
    """One distance, two verdicts, because the claims promise different things."""
    far = [(LatLon(40.0, -76.07), "somewhere 88 km north")]
    point_board = board_with(LatLon(39.21, -76.07), far, level=Level.POINT)
    country_board = board_with(LatLon(39.21, -76.07), far, level=Level.CONTINENT)
    assert check_against_gazetteer(point_board, point_board.claims["c2"]).verdict \
        is Verdict.REFUTED
    assert check_against_gazetteer(country_board, country_board.claims["c2"]).verdict \
        is Verdict.CONFIRMED


# --------------------------------------------------------------------------
# What a check may not do
# --------------------------------------------------------------------------

def test_nothing_to_check_against_is_not_a_refutation():
    """Absence of confirmation is not refutation, and a run with no lookups
    must not be punished for it."""
    b = Board("t.jpg")
    e = b.add_evidence("first_pass", "a field", resolves_to=Level.COUNTRY)
    b.add_candidate(LatLon(0.0, 0.0), prior=1.0, origin="first_pass",
                    evidence_ids=(e.id,))
    b.add_claim(Level.COUNTRY, "Nowhere", supports=(Support(e.id, 0.9),))
    v = verify(b)
    assert not v.refuted
    assert v.refutations_applied == 0


def test_the_classifier_is_not_trusted_to_refute_anything():
    """Right about a third of the time. Letting it overturn claims replaces one
    overconfident voice with two."""
    assert TRUST["geocell_classifier"] == 0.0


def test_a_zero_weight_refutation_is_reported_but_not_applied():
    """A check may say it disagrees without being entitled to act."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")],
                   strength=0.0)
    v = verify(b)
    assert v.refuted
    assert v.refutations_applied == 0
    assert b.resolve().answer.level is Level.CITY


def test_a_refutation_cannot_be_worth_more_than_its_evidence():
    """Same clamp as everywhere else: whoever writes the number does not get to
    decide what the evidence is worth."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")],
                   strength=0.2)
    check = check_against_gazetteer(b, b.claims["c2"])
    assert check.weight == pytest.approx(0.2)


def test_constraint_checks_report_without_charging_twice():
    """Admissibility already multiplies into confidence. Adding a refutation on
    top would price the same disagreement twice."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(39.22, -76.06), "Chestertown")])
    check = check_against_constraints(b, b.claims["c2"])
    assert check is None or check.weight == 0.0


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------

def test_no_check_sees_a_refutation_another_check_produced():
    """Checks that weaken each other's inputs mid-pass would make the outcome
    depend on the order they happen to be listed in."""
    b = board_with(LatLon(39.21, -76.07), [(LatLon(41.88, -87.63), "Chicago")])
    seen: list[int] = []

    def nosy(board, claim):
        seen.append(len([e for e in board.evidence.values() if e.source == "verify"]))
        return None

    verify(b, checks=(check_against_gazetteer, nosy))
    assert seen == [0] * len(seen)
