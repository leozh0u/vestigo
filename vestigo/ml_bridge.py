"""The one place the package touches torch.

Kept apart so `import vestigo` still works on a machine with no ML stack
installed, which every test in this suite relies on. Only the geocell tool
reaches through here, and only when it is actually called.
"""
from __future__ import annotations

MODEL = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"

_cache: dict = {}


def load_encoder():
    """The frozen CLIP encoder and its preprocessing, loaded once."""
    if "encoder" not in _cache:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL, pretrained=PRETRAINED)
        model = model.eval()
        for p in model.parameters():
            p.requires_grad_(False)
        _cache["encoder"] = (model, preprocess)
        _cache["torch"] = torch
    return _cache["encoder"]
