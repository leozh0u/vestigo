"""The one place the package touches torch.

Kept apart so `import vestigo` still works on a machine with no ML stack
installed, which every test in this suite relies on. Only the geocell tool
reaches through here, and only when it is actually called.
"""
from __future__ import annotations

# Fallbacks only, for a checkpoint written before checkpoints named their
# encoder. The live value comes from the checkpoint itself.
MODEL = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"

_cache: dict = {}


class EncoderMismatch(RuntimeError):
    """The head was trained on a different backbone than the one loaded.

    Raised early and by name. Without it the mismatch surfaces as
    `mat1 and mat2 shapes cannot be multiplied (1x512 and 768x245)` from deep
    inside torch, which is what happened when the head was retrained on
    ViT-L/14 and inference kept embedding with ViT-B/32: fifty-four calls
    failed identically inside a paid eval run and the summary line said only
    that the tool had failed.
    """


def load_encoder(model_name: str | None = None, pretrained: str | None = None):
    """The frozen CLIP encoder and its preprocessing, loaded once.

    The names come from the checkpoint that will use it, so the head and the
    encoder cannot drift apart. Two different encoders in one process are
    cached separately rather than silently sharing the first one loaded.
    """
    name = model_name or MODEL
    weights = pretrained or PRETRAINED
    key = f"encoder:{name}:{weights}"
    if key not in _cache:
        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            name, pretrained=weights)
        model = model.eval()
        for p in model.parameters():
            p.requires_grad_(False)
        _cache[key] = (model, preprocess)
        _cache["torch"] = torch
    return _cache[key]
