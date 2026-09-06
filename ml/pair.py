"""Join two encoders' embeddings into one set, for training a head on both.

    ./.venv/bin/python ml/pair.py vit-so400m-14-siglip__webli vit-so400m-14-siglip2__webli

Written because the measurement was worth acting on. Trained separately on the
same split, the two SigLIP encoders land in much the same place — 51.6% cell
accuracy against 50.7%, 142 km median against 148. Concatenated they do
considerably better than either:

    encoder        cells  accuracy  median   within 200 km  within 750 km
    SigLIP           245    51.6%   142 km       57.8%          77.5%
    SigLIP2          245    50.7%   148 km       56.8%          77.4%
    both             245    55.8%   127 km       62.0%          81.3%

Four points of accuracy and fifteen kilometres of median, for no new training
data and no architecture change, because the head is one linear layer and its
ceiling is the representation underneath it. Two encoders that were trained
differently disagree about different photographs, and a linear map over both
gets to use the disagreement.

The cost is real and worth stating: inference has to run both encoders, so a
query image is embedded twice. On one image per request that is latency nobody
notices, and it is the reason this is a script rather than the default.

## Why each half is normalised first

Embeddings from different encoders have no obligation to be the same length. If
one comes out systematically larger, it dominates the gradients of the layer
above for a reason that has nothing to do with what it knows. Normalising each
half to unit length first means the layer weighs them on what they contain.
"""
from __future__ import annotations

import argparse
import json
import pathlib


import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
EMB = ROOT / "ml/embeddings"


def load(name: str) -> tuple[np.ndarray, list[str], dict]:
    d = EMB / name
    if not d.is_dir():
        raise SystemExit(f"no embeddings at {d.relative_to(ROOT)}")
    keys = json.loads((d / "keys.json").read_text())
    vectors = np.load(d / "vectors.npy")
    encoder = json.loads((d / "encoder.json").read_text()) if (d / "encoder.json").exists() else {}
    return vectors, keys, encoder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("encoders", nargs="+",
                    help="directory names under ml/embeddings, in order")
    ap.add_argument("--out", default="siglip-pair",
                    help="directory name to write under ml/embeddings")
    args = ap.parse_args()

    if len(args.encoders) < 2:
        raise SystemExit("give at least two encoders to join")

    halves, keys, encoders = [], None, []
    for name in args.encoders:
        vectors, k, meta = load(name)
        if keys is None:
            keys = k
        elif k != keys:
            # Same images in the same order, or the rows do not describe the
            # same photograph and the concatenation is meaningless.
            raise SystemExit(f"{name} has different keys from {args.encoders[0]}")
        norm = np.linalg.norm(vectors, axis=1, keepdims=True)
        halves.append((vectors / np.maximum(norm, 1e-12)).astype(np.float32))
        encoders.append(meta)
        print(f"  {name}  {vectors.shape[0]} x {vectors.shape[1]}")

    joined = np.hstack(halves)
    out = EMB / args.out
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "vectors.npy", joined)
    (out / "keys.json").write_text(json.dumps(keys))
    """The encoders, in the order their halves were concatenated.

    Written as a list rather than as one model, because the head trained on this
    needs both at inference and needs them in this order — a query embedded in
    the other order is a different vector and the layer has never seen it.
    """
    (out / "encoder.json").write_text(json.dumps({"encoders": encoders}, indent=2) + "\n")

    print(f"\nwrote {out.relative_to(ROOT)}  {joined.shape[0]} x {joined.shape[1]}")
    print("  train on it with:")
    print(f"    ./.venv/bin/python ml/train.py --embeddings {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
