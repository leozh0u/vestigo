"""Tests for the board replay.

The property that matters is that a trace is a recording rather than a
reconstruction. Every step has to be a state the board genuinely passed
through, in the order it passed through it, or the site built on top of it is
an animation of something that never happened.
"""
import json

import pytest

from vestigo.board import Board, Level, Support
from vestigo.geo import LatLon
from vestigo.solar import SolarElevation
from vestigo.trace import GRID_DEG, SCHEMA, admissible_grid, trace, write_trace


def band(evidence_id, lo=0.0, hi=25.0):
    return SolarElevation(
        id="", description=f"sun {lo:.0f} to {hi:.0f} deg",
        captured_utc="2024-06-21T18:00:00Z",
        lo_deg=lo, hi_deg=hi, weight=1.0, evidence_ids=(evidence_id,),
    )


@pytest.fixture
def board():
    b = Board("t.jpg")
    e1 = b.add_evidence("first_pass", "guesses Chile", kind="observation",
                        resolves_to=Level.COUNTRY)
    b.add_candidate(LatLon(-41.5, -72.9), label="Puerto Montt", prior=1.0,
                    origin="first_pass", evidence_ids=(e1.id,))
    e2 = b.add_evidence("place_lookup", "two matches far apart",
                        resolves_to=Level.CONTINENT, max_strength=0.45)
    b.add_candidate(LatLon(19.4, -99.1), label="Mexico City", prior=0.45,
                    origin="place_lookup", evidence_ids=(e2.id,))
    e3 = b.add_evidence("solar_position", "sun low in the north")
    b.add_constraint(band(e3.id))
    b.add_claim(Level.COUNTRY, "Chile",
                supports=(Support(evidence_id=e1.id, strength=0.7),),
                stated_confidence="medium")
    return b


# --------------------------------------------------------------------------
# The journal
# --------------------------------------------------------------------------

def test_the_journal_records_everything_in_arrival_order(board):
    kinds = [k for k, _ in board.journal]
    assert kinds == ["evidence", "candidate", "evidence", "candidate",
                     "evidence", "constraint", "claim"]


def test_the_journal_survives_a_round_trip(board):
    again = Board.from_dict(json.loads(json.dumps(board.to_dict())))
    assert again.journal == board.journal


def test_a_board_with_no_journal_refuses_to_be_replayed():
    """A board written before journals existed cannot be replayed, and a
    replay in a guessed order would look exactly as convincing as a real one."""
    b = Board("old.jpg")
    b.add_evidence("x", "y")
    b.journal.clear()
    with pytest.raises(ValueError, match="no journal"):
        trace(b)


# --------------------------------------------------------------------------
# The replay
# --------------------------------------------------------------------------

def test_one_step_per_journal_entry_in_the_same_order(board):
    t = trace(board)
    assert t["schema"] == SCHEMA
    assert [(s["kind"], s["id"]) for s in t["steps"]] == board.journal


def test_replayed_ids_match_the_original(board):
    """Counters are sequential and the order is preserved, so a step's id is
    the id the real board used. Without that, nothing in a trace can be
    cross-referenced against a board."""
    t = trace(board)
    assert {s["id"] for s in t["steps"] if s["kind"] == "evidence"} == set(board.evidence)
    assert {s["id"] for s in t["steps"] if s["kind"] == "claim"} == set(board.claims)


def test_the_final_state_matches_the_board_it_came_from(board):
    t = trace(board)
    assert t["final"]["answer"]["value"] == board.resolve().answer.value
    assert t["final"]["evidence"] == len(board.evidence)


def test_a_competing_candidate_visibly_costs_the_first_guess(board):
    """Scores are normalised across the candidate set, so a second candidate
    takes share from the first. That drop is the thing the site animates."""
    t = trace(board)
    before = t["steps"][1]["candidates"][0]["score"]
    after = t["steps"][3]["candidates"][0]["score"]
    assert before == pytest.approx(1.0)
    assert after < before


def test_a_claim_step_is_where_an_answer_first_appears(board):
    t = trace(board)
    claim_step = next(s for s in t["steps"] if s["kind"] == "claim")
    assert all(s["answer"] is None for s in t["steps"] if s["i"] < claim_step["i"])
    assert claim_step["answer"]["value"] == "Chile"


def test_a_capped_claim_says_so_in_its_note():
    """Asking for a point off country-level evidence gets country, and the
    trace has to carry the reason or the site cannot explain the refusal."""
    b = Board("t.jpg")
    e = b.add_evidence("first_pass", "guesses Chile", resolves_to=Level.COUNTRY)
    b.add_claim(Level.POINT, "Chile", supports=(Support(evidence_id=e.id, strength=0.9),))
    step = trace(b)["steps"][-1]
    assert step["level"] == "country"
    assert "capped" in step["note"].lower()


# --------------------------------------------------------------------------
# The region
# --------------------------------------------------------------------------

def test_an_unconstrained_board_has_no_region_to_draw():
    b = Board("t.jpg")
    b.add_evidence("first_pass", "guesses Chile")
    assert admissible_grid(b) == []


def test_the_grid_covers_the_globe_at_the_stated_resolution(board):
    t = trace(board)
    rows, cols = t["grid"]["rows"], t["grid"]["cols"]
    assert (rows, cols) == (int(180 / GRID_DEG), int(360 / GRID_DEG))
    assert len(t["final"]["admissible"]) == rows * cols


def test_the_grid_samples_cell_centres_not_corners(board):
    """Off by half a cell is how a heatmap ends up shifted against the
    coastlines drawn under it."""
    g = trace(board)["grid"]
    assert g["lat0"] == -90.0 + GRID_DEG / 2
    assert g["lon0"] == -180.0 + GRID_DEG / 2


def test_a_constraint_rules_out_part_of_the_world_and_not_all_of_it(board):
    grid = trace(board)["final"]["admissible"]
    assert 0 < sum(1 for v in grid if v > 50) < len(grid)


def test_the_region_is_emitted_only_when_a_constraint_changes_it(board):
    """Repeating four thousand identical numbers on every step would make the
    file large enough that the site would have to fetch it lazily."""
    t = trace(board)
    carriers = [s for s in t["steps"] if "admissible" in s]
    assert len(carriers) == 1
    assert carriers[0]["kind"] == "constraint"


def test_values_are_integers_a_shader_can_read(board):
    grid = trace(board)["final"]["admissible"]
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in grid)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def test_a_written_trace_is_json_the_site_can_load(board, tmp_path):
    path = write_trace(board, tmp_path / "runs" / "t.json")
    loaded = json.loads(path.read_text())
    assert loaded["schema"] == SCHEMA
    assert loaded["subject"] == "t.jpg"
    assert len(loaded["steps"]) == len(board.journal)


# --------------------------------------------------------------------------
# Replaying a board that has been verified
# --------------------------------------------------------------------------

def refuted_board():
    from vestigo.verify import verify
    b = Board("t.jpg")
    e1 = b.add_evidence("first_pass", "a courthouse", resolves_to=Level.POINT)
    b.add_candidate(LatLon(39.21, -76.07), prior=1.0, origin="first_pass",
                    evidence_ids=(e1.id,))
    e2 = b.add_evidence(
        "place_lookup", "a name was looked up",
        result={"matches": [{"lat": 41.88, "lon": -87.63, "display_name": "Chicago"}]},
        resolves_to=Level.POINT, max_strength=0.95)
    b.add_claim(Level.COUNTRY, "US",
                supports=(Support(e1.id, 0.9), Support(e2.id, 0.9)))
    b.add_claim(Level.CITY, "Chestertown", parent="c1", point=LatLon(39.21, -76.07),
                supports=(Support(e1.id, 0.9), Support(e2.id, 0.9)))
    verify(b)
    return b


def test_a_verified_board_still_replays():
    """A claim carries its refutations, and those cite evidence added later in
    the journal. Replaying the claim with its current supports fails on
    evidence the replay has not reached yet."""
    t = trace(refuted_board())
    assert [k for k, _ in refuted_board().journal][-1] == "refutation"
    assert t["steps"][-1]["kind"] == "refutation"


def test_the_replay_ends_where_the_board_ended():
    """The property that makes a trace a recording rather than a story."""
    b = refuted_board()
    t = trace(b)
    assert t["final"]["answer"]["value"] == b.resolve().answer.value
    assert t["final"]["answer"]["level"] == b.resolve().answer.level.label


def test_the_refusal_is_visible_as_a_step():
    """The answer drops from the city back to the country, which is the moment
    the site exists to show."""
    t = trace(refuted_board())
    levels = [s["answer"]["level"] for s in t["steps"] if s["answer"]]
    assert "city" in levels
    assert levels[-1] == "country"


def test_two_refutations_of_one_claim_stay_distinguishable():
    """A journal entry naming only the claim would produce two identical
    entries and a replay could not tell which support each one added."""
    b = refuted_board()
    e = b.add_evidence("verify", "a second check disagrees",
                       resolves_to=Level.CITY, max_strength=0.5)
    b.refute("c2", e.id, 0.5)
    entries = [ident for kind, ident in b.journal if kind == "refutation"]
    assert len(entries) == 2
    assert len(set(entries)) == 2
    assert trace(b)["final"]["answer"]["value"] == b.resolve().answer.value
