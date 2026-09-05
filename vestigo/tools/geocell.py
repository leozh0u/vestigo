"""The geocell classifier, as a tool.

Every other evidence source in this project has its strength written by the
model citing it. That was the fault behind the first agent run overclaiming on
28% of answers: it could put 0.9 on "dry scrub" and push a claim through, and
the party grading the evidence had an interest in the answer.

This tool is the first source whose strength is measured. The head is
temperature scaled on held-out data, and its stated confidence tracks observed
accuracy to within two points below 0.6, so the probability it reports for a
cell is a number a claim may lean on exactly as far as it says. That is what
`max_strength` was for, and until now nothing could fill it honestly.

What it is not is a good locator. 21% cell accuracy and a median of about
1,000 km, against a frontier model call at 94 km on the same kind of imagery.
So it proposes its top cells as candidates, which costs nothing if they are
wrong because constraints and priors sort that out, and its real contribution
is a second opinion carrying a trustworthy number.

Loads lazily. The package imports fine without torch, and this tool refuses
politely if the model has not been trained.
"""
from __future__ import annotations

import json
import pathlib

from ..board import Level
from .base import CandidateProposal, Tool, ToolResult

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CHECKPOINT = ROOT / "ml/checkpoints/geocell_head.pt"
CELLS = ROOT / "ml/checkpoints/cells.json"

# A cell is a region roughly 130 km across, so a prediction is a region-level
# statement and nothing finer, whatever probability sits on it.
REACH = Level.REGION


class _Loaded:
    """Model, cells and preprocessing, loaded once per process."""

    model = None
    cells = None
    encoder = None
    preprocess = None
    temperature = 1.0


def _load():
    if _Loaded.model is not None:
        return
    import torch
    import torch.nn as nn

    if not CHECKPOINT.exists():
        raise FileNotFoundError(
            f"no classifier at {CHECKPOINT}. Run ml/embed.py then ml/train.py."
        )
    blob = torch.load(CHECKPOINT, map_location="cpu", weights_only=True)
    head = nn.Linear(blob["dim"], blob["n_cells"])
    head.load_state_dict(blob["state_dict"])
    head.eval()

    # The encoder the head was trained against, named in the checkpoint. Older
    # checkpoints do not carry it and fall back to the bridge's default.
    from ..ml_bridge import EncoderMismatch, load_encoder   # torch out of import time
    encoder, preprocess = load_encoder(blob.get("encoder"), blob.get("pretrained"))

    # Checked before the first image rather than discovered on it. A head
    # trained on 768-dimensional vectors against a 512-dimensional encoder
    # fails with "mat1 and mat2 shapes cannot be multiplied", once per image,
    # from inside torch, and the tool result says only that it failed. That
    # cost a whole eval run before anyone read the summaries.
    width = getattr(encoder.visual, "output_dim", None)
    if width is not None and width != blob["dim"]:
        raise EncoderMismatch(
            f"the head expects {blob['dim']}-dimensional vectors and "
            f"{blob.get('encoder', 'the default encoder')} produces {width}. "
            f"Re-run ml/train.py against the embeddings this encoder wrote, "
            f"or embed with the encoder the head was trained on."
        )

    _Loaded.encoder, _Loaded.preprocess = encoder, preprocess
    _Loaded.model = head
    _Loaded.temperature = float(blob.get("temperature", 1.0))
    _Loaded.cells = json.loads(CELLS.read_text())


class GeocellTool(Tool):
    """Predict which region of the world a photograph is in."""

    name = "geocell_classifier"
    version = "1"
    description = (
        "Run a trained geocell classifier over the photograph. Returns the most "
        "likely regions and a calibrated probability for each. The probability "
        "is measured against held-out data rather than asserted, so it can be "
        "trusted as stated. The classifier is coarse, roughly region level and "
        "often wrong about which region, so treat it as a second opinion that "
        "carries an honest number rather than as an answer."
    )
    deterministic = True
    input_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string",
                           "description": "Path to the photograph."},
            "top_k": {"type": "integer",
                      "description": "How many cells to return, 1 to 5."},
        },
        "required": ["image_path"],
    }

    def _run(self, image_path: str, top_k: int = 3) -> ToolResult:
        import torch
        from PIL import Image as PILImage

        _load()
        top_k = max(1, min(int(top_k), 5))
        image = PILImage.open(image_path).convert("RGB")
        batch = _Loaded.preprocess(image).unsqueeze(0)

        with torch.no_grad():
            feats = _Loaded.encoder.encode_image(batch)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            logits = _Loaded.model(feats.float())
            probs = torch.softmax(logits / _Loaded.temperature, dim=1)[0]

        best = torch.topk(probs, k=min(top_k, probs.numel()))
        picks = []
        candidates = []
        for score, idx in zip(best.values.tolist(), best.indices.tolist()):
            cell = _Loaded.cells[idx]
            # Full precision, not rounded. The same number becomes the
            # candidate prior and the evidence ceiling, and rounding it here
            # made two values that should be identical disagree in the seventh
            # decimal place. Round for display, never for the record.
            picks.append({"cell": cell["id"], "lat": cell["lat"], "lon": cell["lon"],
                          "radius_km": cell["radius_km"],
                          "probability": score})
            candidates.append(CandidateProposal(
                point=__import__("vestigo.geo", fromlist=["LatLon"]).LatLon(
                    cell["lat"], cell["lon"]),
                label=f"geocell {cell['id']}",
                # The prior is the calibrated probability, so a cell the
                # classifier is barely backing does not compete with a guess the
                # model is confident about.
                prior=score,
            ))

        top = picks[0]
        return self.result(
            value={"cells": picks, "temperature": _Loaded.temperature},
            summary=(f"classifier: region near {top['lat']:.1f},{top['lon']:.1f} "
                     f"at {top['probability']:.0%} (calibrated)"),
            candidates=tuple(candidates),
            resolves_to=REACH,
            # The one honest ceiling in the project. Every other source has a
            # number somebody chose; this one has a number that was measured.
            max_strength=float(top["probability"]),
        )
