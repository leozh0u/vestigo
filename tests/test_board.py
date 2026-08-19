"""Tests for the evidence board.

Several of these are the Phase 0 results written down as regressions. The
Thailand and Mexico cases are the two images that showed why a constraint
cannot be modelled as another point estimate, so if the behaviour they describe
ever breaks, the reason the Constraint type exists has broken with it.

Coordinates are the real ground truth from data/manifest.json.
"""
import json

import pytest

from vestigo.board import (
    Board,
    BoundingBox,
    LatitudeBand,
    Level,
    LongitudeBand,
    NearPoint,
    RegionSet,
    Support,
)
from vestigo.geo import LatLon, haversine

THAILAND = LatLon(14.836242, 100.249282)     # rural_cb06bab2f5
MEXICO = LatLon(20.450895, -100.467564)      # rural_7ee09e498b
NAIROBI = LatLon(-1.286389, 36.817223)       # where arm A2 flipped to


def one_evidence(board, source="tool", **kw):
    return board.add_evidence(source, "something happened", **kw)


# -- the "does not count" rule ---------------------------------------------

def test_a_claim_with_no_evidence_scores_zero():
    board = Board("t")
    claim = board.add_claim(Level.COUNTRY, "Mexico", stated_confidence="high")
    assert board.confidence(claim) == 0.0
    assert not claim.grounded
    assert board.resolve().answer is None


def test_an_unsupported_claim_cannot_be_talked_up_by_stated_confidence():
    board = Board("t")
    ev = one_evidence(board)
    weak = board.add_claim(Level.CITY, "Somewhere",
                           supports=[Support(ev.id, 0.1)], stated_confidence="high")
    assert board.confidence(weak) == pytest.approx(0.1)
    assert board.resolve().answer is None


def test_citing_evidence_that_is_not_on_the_board_raises():
    board = Board("t")
    with pytest.raises(KeyError):
        board.add_claim(Level.COUNTRY, "Mexico", supports=[Support("e99", 0.9)])


# -- independence ----------------------------------------------------------

def test_independent_evidence_compounds():
    board = Board("t")
    a = board.add_evidence("plates", "EU plate format")
    b = board.add_evidence("vegetation", "Mediterranean scrub")
    claim = board.add_claim(Level.COUNTRY, "Spain",
                            supports=[Support(a.id, 0.5), Support(b.id, 0.5)])
    # Noisy-OR over two unrelated signals.
    assert board.confidence(claim) == pytest.approx(0.75)


def test_correlated_evidence_counts_once():
    board = Board("t")
    root = board.add_evidence("observe", "a signboard, partly legible",
                              kind="observation")
    a = board.add_evidence("ocr", "reads 'PANADERIA'", derived_from=[root.id])
    b = board.add_evidence("lang", "Spanish word", derived_from=[a.id])
    claim = board.add_claim(Level.COUNTRY, "Mexico",
                            supports=[Support(a.id, 0.5), Support(b.id, 0.5)])
    # Both readings come off the same signboard, so it is one signal at its
    # strongest, not two compounding.
    assert board.confidence(claim) == pytest.approx(0.5)


def test_a_mix_of_correlated_and_independent_evidence():
    board = Board("t")
    root = board.add_evidence("observe", "signboard")
    a = board.add_evidence("ocr", "text", derived_from=[root.id])
    b = board.add_evidence("lang", "Spanish", derived_from=[root.id])
    c = board.add_evidence("solar", "latitude band")
    claim = board.add_claim(
        Level.COUNTRY, "Mexico",
        supports=[Support(a.id, 0.5), Support(b.id, 0.4), Support(c.id, 0.5)],
    )
    # The signboard pair collapses to 0.5, then compounds with solar at 0.5.
    assert board.confidence(claim) == pytest.approx(0.75)


def test_refuting_evidence_discounts_the_claim():
    board = Board("t")
    a = board.add_evidence("vegetation", "acacia scrub")
    b = board.add_evidence("solar", "solar time near -100 longitude")
    claim = board.add_claim(Level.COUNTRY, "Kenya",
                            supports=[Support(a.id, 0.8),
                                      Support(b.id, 0.5, supports=False)])
    assert board.confidence(claim) == pytest.approx(0.8 * 0.5)


# -- constraints act on candidates, they do not vote -----------------------

def test_thailand_a_correct_band_leaves_a_satisfying_guess_alone():
    """The Phase 0 failure this type exists to prevent.

    The model derived a longitude band containing the truth, then chose a point
    inside it six times worse than its own image-only guess. Here the band is
    the same and the image-only guess satisfies it, so the guess is untouched
    and stays top ranked. A constraint that cannot move a candidate it admits
    is the whole point.
    """
    board = Board("rural_cb06bab2f5")
    ev = board.add_evidence("solar", "local solar noon puts longitude near 100E")
    board.add_constraint(LongitudeBand(id="", description="solar time",
                                       lo=95.0, hi=105.0, soft_deg=3.0,
                                       evidence_ids=(ev.id,)))
    guess = board.add_candidate(LatLon(15.2, 100.6), label="image-only guess",
                                prior=1.0, origin="model")
    scored = board.rank_candidates()
    assert scored[0].candidate.id == guess.id
    assert scored[0].admissibility == 1.0
    assert haversine(scored[0].point, THAILAND) < 60


def test_mexico_a_constraint_removes_the_candidate_that_flipped_continents():
    """The other Phase 0 case.

    Between two identical no-metadata runs the answer moved from Mexico to
    Kenya, 14,951 km apart. With the capture timestamp the model ruled out East
    Africa on solar grounds. The timestamp did not improve the Mexico estimate,
    it stopped the Kenya one being chosen, so the constraint has to show up as
    elimination rather than displacement.
    """
    board = Board("rural_7ee09e498b")
    ev = board.add_evidence(
        "solar", "21:35 UTC front-lit on an easterly heading forces longitude near -100",
        inputs={"captured_utc": "2024-04-20 21:35:52", "compass_angle": 94.5},
    )
    board.add_constraint(LongitudeBand(id="", description="solar time",
                                       lo=-115.0, hi=-85.0, soft_deg=10.0,
                                       weight=0.9, evidence_ids=(ev.id,)))
    mx = board.add_candidate(MEXICO, label="Queretaro", prior=0.5, origin="run 1")
    ke = board.add_candidate(NAIROBI, label="Nairobi", prior=0.5, origin="run 2")

    ranked = {s.candidate.id: s for s in board.rank_candidates()}
    assert ranked[mx.id].admissibility == 1.0        # the truth is not moved at all
    assert ranked[ke.id].admissibility == pytest.approx(0.1)
    assert ranked[mx.id].score > ranked[ke.id].score * 8


def test_a_constraint_short_of_certain_cannot_delete_a_candidate():
    """A tool that measured something off a soft input should not be able to
    rule out the truth outright. Weight is the certainty in the constraint
    itself, and below 1.0 it leaves a residue."""
    board = Board("t")
    ev = board.add_evidence("solar", "shadow angle read off a blurry edge")
    board.add_constraint(LatitudeBand(id="", description="wrong band",
                                      lo=40.0, hi=50.0, weight=0.8,
                                      evidence_ids=(ev.id,)))
    truth = board.add_candidate(MEXICO, label="truth", prior=1.0)
    other = board.add_candidate(LatLon(45.0, -100.0), label="inside the band", prior=0.05)
    ranked = {s.candidate.id: s for s in board.rank_candidates()}
    assert ranked[truth.id].admissibility == pytest.approx(0.2)
    assert ranked[truth.id].score > ranked[other.id].score      # prior still wins


def test_a_certain_constraint_does_delete():
    board = Board("t")
    ev = board.add_evidence("plates", "left-hand traffic")
    board.add_constraint(LatitudeBand(id="", description="hard", lo=40.0, hi=50.0,
                                      weight=1.0, evidence_ids=(ev.id,)))
    dead = board.add_candidate(MEXICO, prior=1.0)
    ranked = {s.candidate.id: s for s in board.rank_candidates()}
    assert ranked[dead.id].admissibility == 0.0


def test_soft_edges_penalise_rather_than_cut():
    board = Board("t")
    ev = board.add_evidence("solar", "band")
    board.add_constraint(LatitudeBand(id="", description="soft", lo=10.0, hi=20.0,
                                      soft_deg=5.0, evidence_ids=(ev.id,)))
    inside = board.add_candidate(LatLon(15.0, 0.0))
    edge = board.add_candidate(LatLon(22.5, 0.0))
    far = board.add_candidate(LatLon(30.0, 0.0))
    r = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert r[inside.id] == 1.0
    assert r[edge.id] == pytest.approx(0.5)
    assert r[far.id] == 0.0


# -- abstention ------------------------------------------------------------

def test_a_constraint_that_cannot_be_evaluated_abstains():
    """An unevaluated constraint must never quietly veto the right answer."""
    board = Board("t")
    ev = board.add_evidence("meta", "left-hand traffic")
    board.add_constraint(RegionSet(id="", description="LHT countries",
                                   codes=frozenset({"GB", "TH", "JP"}),
                                   evidence_ids=(ev.id,)))     # no resolver
    board.add_candidate(MEXICO, prior=1.0)
    assert board.rank_candidates()[0].admissibility == 1.0


def test_region_set_excludes_once_it_has_a_resolver():
    board = Board("t")
    ev = board.add_evidence("meta", "left-hand traffic")
    codes = {MEXICO: "MX", THAILAND: "TH"}
    board.add_constraint(RegionSet(id="", description="LHT countries",
                                   codes=frozenset({"GB", "TH", "JP"}),
                                   evidence_ids=(ev.id,),
                                   resolver=lambda p: codes.get(p)))
    mx = board.add_candidate(MEXICO, prior=0.5)
    th = board.add_candidate(THAILAND, prior=0.5)
    r = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert r[th.id] == 1.0
    assert r[mx.id] == 0.0


def test_region_set_can_be_negative():
    """The Mexico case in set form: not East Africa."""
    board = Board("t")
    ev = board.add_evidence("solar", "solar time rules out East Africa")
    codes = {MEXICO: "MX", NAIROBI: "KE"}
    board.add_constraint(RegionSet(id="", description="not East Africa",
                                   codes=frozenset({"KE", "TZ", "UG"}),
                                   inside=False, evidence_ids=(ev.id,),
                                   resolver=lambda p: codes.get(p)))
    mx = board.add_candidate(MEXICO, prior=0.5)
    ke = board.add_candidate(NAIROBI, prior=0.5)
    r = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert r[mx.id] == 1.0
    assert r[ke.id] == 0.0


def test_a_claim_with_no_point_is_scored_on_evidence_alone():
    board = Board("t")
    ev = board.add_evidence("ocr", "reads PANADERIA")
    board.add_constraint(LatitudeBand(id="", description="far away",
                                      lo=60.0, hi=70.0, evidence_ids=(ev.id,)))
    claim = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(ev.id, 0.8)])
    assert board.confidence(claim) == pytest.approx(0.8)


# -- the dateline ----------------------------------------------------------

def test_a_band_across_the_dateline_takes_the_short_way():
    board = Board("t")
    ev = board.add_evidence("solar", "band")
    board.add_constraint(LongitudeBand(id="", description="dateline",
                                       lo=170.0, hi=-170.0, evidence_ids=(ev.id,)))
    fiji = board.add_candidate(LatLon(-17.7, 178.0))
    london = board.add_candidate(LatLon(51.5, 0.0))
    r = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert r[fiji.id] == 1.0
    assert r[london.id] == 0.0


# -- resolve ---------------------------------------------------------------

def test_resolve_stops_at_the_granularity_the_evidence_supports():
    """The design idea in one test. Country at high confidence beats a
    confidently wrong street address, so the answer is the country."""
    board = Board("t")
    strong = board.add_evidence("plates", "Mexican plate format, clearly legible")
    weak = board.add_evidence("guess", "looks like it could be Queretaro")
    country = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(strong.id, 0.9)])
    board.add_claim(Level.POINT, "20.45N 100.47W", point=MEXICO,
                    supports=[Support(weak.id, 0.3)], parent=country.id)

    res = board.resolve()
    assert res.answer is not None
    assert res.answer.level is Level.COUNTRY
    assert res.answer.value == "Mexico"
    assert [c.level for c in res.chain] == [Level.COUNTRY]


def test_resolve_reaches_a_point_when_the_evidence_is_there():
    board = Board("t")
    a = board.add_evidence("ocr", "town name on a shopfront")
    b = board.add_evidence("overpass", "only one match within 300 m")
    country = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(a.id, 0.9)])
    city = board.add_claim(Level.CITY, "Queretaro", supports=[Support(a.id, 0.8)],
                           parent=country.id)
    board.add_claim(Level.POINT, "20.45N 100.47W", point=MEXICO,
                    supports=[Support(a.id, 0.7), Support(b.id, 0.8)],
                    parent=city.id)

    res = board.resolve()
    assert res.answer.level is Level.POINT
    assert [c.level for c in res.chain] == [Level.COUNTRY, Level.CITY, Level.POINT]


def test_resolve_follows_the_parent_chain_rather_than_stacking_best_guesses():
    board = Board("t")
    a = board.add_evidence("ocr", "town name")
    weak_country = board.add_claim(Level.COUNTRY, "Kenya", supports=[Support(a.id, 0.99)])
    real_country = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(a.id, 0.9)])
    board.add_claim(Level.CITY, "Queretaro", supports=[Support(a.id, 0.9)],
                    parent=real_country.id)

    res = board.resolve()
    # Kenya scores higher at country level, but the city claim declares Mexico
    # as its parent, so the chain has to stay coherent.
    assert [c.value for c in res.chain] == ["Mexico", "Queretaro"]
    assert res.confidences[weak_country.id] > res.confidences[real_country.id]


def test_constraints_can_only_lower_a_claim():
    board = Board("t")
    ev = board.add_evidence("ocr", "town name")
    claim = board.add_claim(Level.POINT, "here", point=MEXICO,
                            supports=[Support(ev.id, 0.9)])
    before = board.confidence(claim)
    board.add_constraint(BoundingBox(id="", description="somewhere else",
                                     south=40.0, west=0.0, north=50.0, east=20.0,
                                     weight=0.5, evidence_ids=(ev.id,)))
    assert board.confidence(claim) < before
    assert board.confidence(claim) <= board.evidence_confidence(claim)


def test_near_point_both_ways():
    board = Board("t")
    ev = board.add_evidence("coast", "no sea visible, and the horizon is land")
    board.add_constraint(NearPoint(id="", description="not near the coast",
                                   center=LatLon(20.0, -105.6), radius_km=80.0,
                                   inside=False, evidence_ids=(ev.id,)))
    inland = board.add_candidate(MEXICO, prior=0.5)
    coastal = board.add_candidate(LatLon(20.6, -105.25), prior=0.5)
    r = {s.candidate.id: s.admissibility for s in board.rank_candidates()}
    assert r[inland.id] == 1.0
    assert r[coastal.id] == 0.0


# -- persistence -----------------------------------------------------------

def test_a_board_round_trips_through_json():
    board = Board("rural_7ee09e498b")
    ev = board.add_evidence("solar", "solar time near -100",
                            inputs={"utc": "2024-04-20 21:35:52"},
                            result={"lon_lo": -115, "lon_hi": -85})
    board.add_constraint(LongitudeBand(id="", description="solar time",
                                       lo=-115.0, hi=-85.0, soft_deg=10.0,
                                       weight=0.9, evidence_ids=(ev.id,)))
    board.add_constraint(NearPoint(id="", description="inland",
                                   center=LatLon(20.0, -105.6), radius_km=80.0,
                                   inside=False, evidence_ids=(ev.id,)))
    board.add_constraint(RegionSet(id="", description="not East Africa",
                                   codes=frozenset({"KE", "TZ"}), inside=False,
                                   evidence_ids=(ev.id,)))
    country = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(ev.id, 0.8)])
    board.add_claim(Level.POINT, "truth", point=MEXICO,
                    supports=[Support(ev.id, 0.5)], parent=country.id)
    board.add_candidate(MEXICO, label="Queretaro", prior=0.5)
    board.add_candidate(NAIROBI, label="Nairobi", prior=0.5)

    revived = Board.from_dict(json.loads(json.dumps(board.to_dict())))

    assert revived.subject == board.subject
    assert [s.score for s in revived.rank_candidates()] == \
           [s.score for s in board.rank_candidates()]
    assert {c.id: revived.confidence(c) for c in revived.claims.values()} == \
           {c.id: board.confidence(c) for c in board.claims.values()}
    assert revived.resolve().answer.value == board.resolve().answer.value


def test_ids_are_sequential_so_two_runs_can_be_diffed():
    board = Board("t")
    assert [board.add_evidence("x", "y").id for _ in range(3)] == ["e1", "e2", "e3"]
    assert board.add_candidate(MEXICO).id == "n1"
