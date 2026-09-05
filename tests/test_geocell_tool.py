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


def test_the_checkpoint_names_the_encoder_it_was_trained_against():
    """A head trained on 768-dimensional vectors is useless against a
    512-dimensional encoder, and the two lived in different files with nothing
    connecting them. Retraining on a larger backbone left inference silently
    mismatched: fifty-four calls failed identically inside a paid eval run and
    the summary said only that the tool had failed."""
    import torch
    blob = torch.load("ml/checkpoints/geocell_head.pt", map_location="cpu",
                      weights_only=True)
    assert blob["encoder"]
    assert blob["pretrained"]
    # As open_clip would be called, not the lowercased directory slug.
    # "vit-l-14" is not a model it will load.
    assert blob["encoder"] != blob["encoder"].lower() or "-" not in blob["encoder"]


def test_a_mismatched_encoder_is_named_rather_than_discovered_in_torch():
    """The failure should say which two things disagree. Left to torch it
    surfaces as 'mat1 and mat2 shapes cannot be multiplied (1x512 and
    768x245)', once per image, from inside a matrix multiply."""
    from vestigo.ml_bridge import EncoderMismatch
    assert issubclass(EncoderMismatch, RuntimeError)
    source = __import__("pathlib").Path("vestigo/tools/geocell.py").read_text()
    assert "EncoderMismatch" in source
    assert "output_dim" in source


def test_embeddings_carry_the_exact_names_they_were_made_with():
    """Parsing the directory name back gives a lowercased slug that fails at
    load time rather than at save time."""
    import json
    import pathlib
    for d in pathlib.Path("ml/embeddings").iterdir():
        if (d / "vectors.npy").exists() and (d / "encoder.json").exists():
            blob = json.loads((d / "encoder.json").read_text())
            assert blob["model"] and blob["pretrained"]
