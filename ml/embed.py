"""Turn photographs into vectors, once.

The encoder is frozen. Nothing here is trained. CLIP has already learned what
things look like, and the only question this project asks of it is which of its
directions correspond to places, which is what the classifier head in train.py
learns from these vectors.

Freezing is the simplification that makes the ML half runnable on a laptop.
PIGEON fine-tuned CLIP itself against synthetic geographic captions, which
needs real GPUs and weeks. A linear head on cached embeddings trains in seconds
and can be retrained fifty times an afternoon while the cells change, because
this step never has to run again.

Stated up front, since it bounds everything downstream: a frozen encoder can
only separate places that already look different to CLIP. Anything needing
geographic knowledge CLIP does not hold is out of reach, and the gap between
this and a fine-tuned model is the writeup rather than a failure.

    ./.venv/bin/python ml/embed.py

Resumable. Embeddings are keyed by filename, so adding images later only
embeds the new ones.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import time

import numpy as np
import torch
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "data/train_index.json"
OUT = ROOT / "ml/embeddings"

# ViT-B/32 on LAION-2B is the default because it runs on a laptop in minutes
# and it is the backbone the geolocation literature uses, so a comparison
# against published numbers is not confounded by a different encoder.
#
# It is also the smallest CLIP there is. Thirty-two-pixel patches mean it sees
# a photograph coarsely, and since the classifier on top is one linear layer,
# whatever these vectors fail to separate is not recoverable downstream. The
# encoder is the ceiling, which makes swapping it the cheapest large experiment
# available: no new data, no GPU rental, just laptop time.
#
# Worth trying, roughly in order of how much they cost to run:
#   ViT-L-14              laion2b_s32b_b82k     larger, 14-pixel patches, 768-d
#   ViT-SO400M-14-SigLIP  webli                 stronger again, slower
MODEL = "ViT-B-32"
PRETRAINED = "laion2b_s34b_b79k"


def _alive(pid: int) -> bool:
    """Whether a process is still running.

    Signal 0 performs the permission and existence checks without delivering
    anything, which is the standard way to ask. A process owned by somebody
    else raises PermissionError, and that still means it exists.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def slug(model: str, pretrained: str) -> str:
    """A directory name per encoder, so two of them cannot overwrite each other.

    Embeddings from different backbones are not interchangeable and have
    different widths. Writing them to one path would either crash on the
    dimension or, worse, load a mixture and train on it.
    """
    return f"{model}__{pretrained}".lower().replace("/", "-")


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")      # Apple GPU, roughly 5x the CPU here
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_model(dev: torch.device, model_name: str = MODEL,
               pretrained: str = PRETRAINED):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained)
    model = model.to(dev).eval()
    for p in model.parameters():
        p.requires_grad_(False)         # frozen, and said so in the code
    return model, preprocess


@torch.no_grad()
def embed_batch(model, tensors: list[torch.Tensor], dev) -> np.ndarray:
    batch = torch.stack(tensors).to(dev)
    feats = model.encode_image(batch)
    # Unit length, so the classifier learns from direction rather than from
    # however bright or contrasty a photograph happened to be.
    feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.float().cpu().numpy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--model", default=MODEL,
                    help="open_clip backbone. The ceiling on everything the "
                         "linear head can do, so this is the knob worth turning")
    ap.add_argument("--pretrained", default=PRETRAINED)
    ap.add_argument("--images", default="data/train")
    ap.add_argument("--index", default=str(INDEX))
    ap.add_argument("--out", help="defaults to ml/embeddings/<model slug>")
    args = ap.parse_args()
    if not args.out:
        args.out = str(OUT / slug(args.model, args.pretrained))

    index = json.loads(pathlib.Path(args.index).read_text())
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    vec_path, key_path = out / "vectors.npy", out / "keys.json"

    done: dict[str, int] = {}
    vectors = None
    if vec_path.exists() and key_path.exists():
        vectors = np.load(vec_path)
        done = {k: i for i, k in enumerate(json.loads(key_path.read_text()))}
        print(f"{len(done)} already embedded")

    # The exact strings open_clip was called with, beside the vectors they
    # produced. The directory name is a lowercased slug and "vit-l-14" is not a
    # model open_clip will load, so parsing the name back yields a string that
    # fails at load time rather than at save time.
    #
    # Written before the work rather than after it, because a rerun that finds
    # nothing to do still has to leave the marker: that is exactly the case
    # where an already-complete directory would otherwise never get one.
    (out / "encoder.json").write_text(json.dumps({
        "model": args.model, "pretrained": args.pretrained,
    }, indent=2) + "\n")

    # One writer per directory.
    #
    # Both the vectors and the key list are read-modify-write, so a second run
    # against the same output silently corrupts the first. The lock is a file
    # rather than anything cleverer because the failure it prevents is a person
    # starting the same command twice, which is what happened.
    lock = out / ".embedding.lock"
    if lock.exists():
        # The lock holds the writer's process id, so a lock left behind by a
        # run that was killed can be told apart from one held by a run that is
        # still going. Without the check, one Ctrl-C leaves a directory that
        # refuses every future run until somebody deletes a file by hand, and
        # the message telling them to do that is the message I wrote and then
        # had to follow myself.
        try:
            holder = int(lock.read_text().strip())
        except (ValueError, OSError):
            holder = None
        if holder is not None and _alive(holder):
            raise SystemExit(
                f"{lock} is held by process {holder}, which is running.\n"
                f"Two runs against one directory corrupt each other, so this "
                f"one will not start."
            )
        print(f"  clearing a lock from process {holder}, which is gone")
        lock.unlink(missing_ok=True)
    lock.write_text(f"{os.getpid()}\n")

    todo = [r for r in index if r["file"] not in done]
    if not todo:
        lock.unlink(missing_ok=True)
        print("nothing to do")
        return 0

    dev = device()
    print(f"embedding {len(todo)} images on {dev.type}")
    model, preprocess = load_model(dev, args.model, args.pretrained)

    keys, rows = list(done), []
    batch: list[torch.Tensor] = []
    batch_keys: list[str] = []
    started = time.perf_counter()
    skipped = 0

    def save() -> None:
        """Write what has been embedded so far.

        Called periodically, not only at the end. The first version wrote once
        after the last batch, so a run interrupted at fifty thousand images
        left an empty directory and forty minutes of GPU time bought nothing.
        `todo` is computed from what is already on disk, so a checkpoint is
        also a resume point: restart and it picks up from the last save.

        Vectors go to a temporary file first and are moved into place, because
        the alternative is a half-written .npy that loads as garbage and is
        worse than no file at all.
        """
        nonlocal rows, keys
        if not rows:
            return
        fresh = np.concatenate(rows)
        current = np.load(vec_path) if vec_path.exists() else None
        stacked = fresh if current is None else np.concatenate([current, fresh])

        # Refuse to write a file that cannot be right.
        #
        # Two runs of this script against one directory both append, and the
        # array ends up an interleaving of the two while keys.json holds
        # whatever the last writer had. That happened: 107,636 vectors for
        # 65,300 images, unrecoverable, two hours of GPU time gone. The lock
        # below stops it, and this stops anything else that would produce the
        # same shape of damage from being written to disk at all.
        if stacked.shape[0] != len(keys):
            raise RuntimeError(
                f"refusing to write {vec_path}: {stacked.shape[0]} vectors "
                f"against {len(keys)} keys. Something else has written to this "
                f"directory. Delete it and start again rather than trusting a "
                f"file that cannot be indexed."
            )
        # Through a handle, not a path: np.save appends ".npy" to any path
        # that does not already end in it, so saving to "vectors.npy.tmp"
        # silently writes "vectors.npy.tmp.npy" and the move then fails on a
        # file that was never created. Caught by a test rather than by the
        # first checkpoint of a forty-minute run.
        tmp = vec_path.with_suffix(".npy.tmp")
        with open(tmp, "wb") as fh:
            np.save(fh, stacked)
        tmp.replace(vec_path)
        key_path.write_text(json.dumps(keys) + "\n")
        rows = []                       # already on disk, do not write twice

    # Roughly every few thousand images. Often enough that an interrupt costs
    # minutes rather than the run, rare enough that rewriting the array is a
    # rounding error against the GPU time.
    checkpoint_every = max(args.batch * 8, 2000)
    since_save = 0

    try:
        for i, record in enumerate(todo):
            path = pathlib.Path(args.images) / record["file"]
            try:
                batch.append(preprocess(Image.open(path).convert("RGB")))
                batch_keys.append(record["file"])
            except Exception:
                skipped += 1            # a truncated download is not a crash
                continue
            if len(batch) >= args.batch or i == len(todo) - 1:
                rows.append(embed_batch(model, batch, dev))
                keys.extend(batch_keys)
                since_save += len(batch_keys)
                batch, batch_keys = [], []
                seen = len(keys) - len(done)
                if seen and seen % (args.batch * 8) < args.batch:
                    rate = seen / (time.perf_counter() - started)
                    print(f"  {seen}/{len(todo)}  {rate:.0f}/s", flush=True)
                if since_save >= checkpoint_every:
                    save()
                    since_save = 0
    except KeyboardInterrupt:
        # Ctrl-C is a normal way to stop a long job, so it saves and reports
        # rather than discarding the work and printing a stack trace.
        save()
        print(f"\ninterrupted at {len(keys) - len(done)} images, saved. "
              f"Rerun the same command to continue.")
        return 130
    finally:
        lock.unlink(missing_ok=True)

    save()
    vectors = np.load(vec_path)

    print(f"\n{vectors.shape[0]} vectors of {vectors.shape[1]} dimensions -> {vec_path}")
    if skipped:
        print(f"  {skipped} images could not be read and were skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
