"""Tests for the geocell classifier as a tool.

The suite must run on a machine with no ML stack, so anything needing torch is
skipped rather than failing. What is checked unconditionally is the contract:
the tool exists, declares a region-level reach, and cannot reach past it.
"""
import pytest

from vestigo.board import Board, Level, Support
from vestigo.tools.base import attach
from vestigo.tools.geocell import REACH, GeocellTool

torch = pytest.importorskip("torch", reason="needs the ML stack")
CHECKPOINT_MISSING = not __import__("pathlib").Path(
    "ml/checkpoints/geocell_head.pt").exists()
needs_model = pytest.mark.skipif(CHECKPOINT_MISSING, reason="classifier not trained")


def test_the_tool_declares_itself_region_level():
    """A cell is roughly 130 km across, so a prediction is a region-level
    statement whatever probability sits on it."""
    assert REACH is Level.REGION
    spec = GeocellTool().spec()
    assert set(spec) == {"name", "description", "input_schema"}
    assert "calibrated" in spec["description"]


def test_a_missing_image_comes_back_as_a_failed_result():
    result = GeocellTool()(image_path="does/not/exist.jpg")
    assert result.ok is False
    assert result.error


@needs_model
def test_it_returns_cells_with_calibrated_probabilities():
    result = GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg", top_k=3)
    assert result.ok
    cells = result.value["cells"]
    assert len(cells) == 3
    assert cells == sorted(cells, key=lambda c: -c["probability"])
    assert all(0.0 <= c["probability"] <= 1.0 for c in cells)


@needs_model
def test_top_k_is_clamped():
    assert len(GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg",
                             top_k=99).value["cells"]) <= 5
    assert len(GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg",
                             top_k=0).value["cells"]) == 1


@needs_model
def test_the_strength_ceiling_is_the_measured_probability():
    """The point of this tool. Every other evidence source in the project has a
    strength somebody chose; this one has a number that was measured against
    held-out data, so a claim may lean on it exactly as far as it says."""
    result = GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg")
    assert result.max_strength == pytest.approx(result.value["cells"][0]["probability"])

    board = Board("t")
    ev = attach(board, result)
    assert board.evidence[ev.id].max_strength == pytest.approx(result.max_strength)
    # A claim citing it cannot be worth more than the classifier's own confidence.
    claim = board.add_claim(Level.REGION, "somewhere",
                            supports=[Support(ev.id, 0.99)])
    assert claim.supports[0].strength == pytest.approx(result.max_strength)


@needs_model
def test_it_cannot_support_a_claim_finer_than_a_region():
    result = GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg")
    board = Board("t")
    ev = attach(board, result)
    claim = board.add_claim(Level.POINT, "a precise spot",
                            supports=[Support(ev.id, 0.9)])
    assert claim.level is Level.REGION
    assert "capped from point" in claim.note


@needs_model
def test_its_cells_become_candidates_weighted_by_confidence():
    """A cell the classifier is barely backing should not compete with a guess
    the model is confident about."""
    result = GeocellTool()(image_path="data/images/rural_7ee09e498b.jpg", top_k=3)
    board = Board("t")
    attach(board, result)
    priors = [c.prior for c in board.candidates.values()]
    assert len(priors) == 3
    assert all(0.0 < p <= 1.0 for p in priors)
    assert max(priors) == pytest.approx(result.max_strength)
