"""Train a geocell classifier on frozen CLIP embeddings, then calibrate it.

The model is one linear layer. That is not a placeholder. The embeddings are
already a learned representation, and the only question left is which
directions in that space correspond to which places, which is exactly what a
linear map answers. Anything deeper mostly memorises 20,000 photographs.

Two things here matter more than the architecture.

**The split is by seed location, not random.** The fetcher drew several images
from each 10 km box, so a random split puts near-duplicates on both sides and
reports an accuracy that is mostly recall. Whole locations go to train or to
validation, never both, which makes the number lower and worth reading.

**Temperature scaling is the point of the exercise.** A softmax out of a
classifier is usually overconfident: it says 95% and is right 70% of the time.
One number, fitted on held-out data, divides the logits until stated confidence
matches observed accuracy. That number is the whole calibration thesis in a
form small enough to check, and it is what lets a cell probability become the
confidence on a claim the board can act on.

The textbook expectation did not hold here. Every cell count tried came back
with a temperature near 0.7, which means the head was *under*confident and the
scaling sharpens its probabilities rather than softening them. Worth reporting
rather than filing off: an assumption stated in a comment is still an
assumption, and this one was wrong on this data.

    ./.venv/bin/python ml/train.py
"""
from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np
import torch
import torch.nn as nn

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ml.geocells import assign_cell, build, haversine, save as save_cells  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
EMB = ROOT / "ml/embeddings"
OUT = ROOT / "ml/checkpoints"


def load_data(n_cells: int, min_count: int, mode: str = "cluster",
              per_cell: int = 300):
    """Embeddings, labels and the group each image belongs to.

    Two ways to draw the cells. `cluster` puts boundaries where the training
    data thins out, which needs nothing but the points. `admin` puts them on
    national borders and splits inside a country by density, which is closer to
    what the pictures look like: road paint, plate shapes and signage script all
    change at a border and nowhere else.
    """
    index = {r["file"]: r for r in json.loads((ROOT / "data/train_index.json").read_text())}
    keys = json.loads((EMB / "keys.json").read_text())
    vectors = np.load(EMB / "vectors.npy")

    rows = [(i, index[k]) for i, k in enumerate(keys) if k in index]
    points = [(r["lat"], r["lon"]) for _, r in rows]

    if mode == "admin":
        from ml.admin_cells import build as build_admin, load_countries
        cells, origins, dropped = build_admin(
            points, load_countries(), target_per_cell=per_cell, min_count=min_count)
        if dropped:
            keep = sorted(set(range(len(rows))) - set(dropped))
            rows = [rows[i] for i in keep]
            points = [points[i] for i in keep]
            print(f"  {len(dropped)} points dropped as geotags in open ocean")
    else:
        cells = build(points, n_cells=n_cells, min_count=min_count)
        origins = [""] * len(cells)

    X = vectors[[i for i, _ in rows]]
    y = np.array([assign_cell(cells, la, lo) for la, lo in points])
    # The seed box each image came from. Two images from one box are the same
    # stretch of road, so they must not straddle the split.
    groups = np.array([f"{r['seed'][0]},{r['seed'][1]}" for _, r in rows])
    return X, y, groups, np.array(points), cells, origins


def split_by_location(groups: np.ndarray, frac: float, seed: int):
    """Hold out whole seed locations.

    A random split would put photographs taken metres apart on both sides and
    report a number that is mostly recall of the training set. This is the
    single most important line in the file.
    """
    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    rng.shuffle(unique)
    held = set(unique[: max(1, int(len(unique) * frac))].tolist())
    mask = np.array([g in held for g in groups])
    return ~mask, mask


def haversine_targets(cells, tau_km: float = 75.0) -> torch.Tensor:
    """A soft label per cell, spread over its neighbours by distance.

    Plain cross-entropy scores the neighbouring cell exactly as wrong as the
    opposite hemisphere. For a geographic task that discards most of the
    signal: the model is told nothing about the difference between a near miss
    and a catastrophe, so it never learns that cells near each other look
    alike.

    Each row here is the true cell's own smoothed target, exp(-d/tau) over
    every cell's distance from it, normalised. At tau of 75 km a cell 75 km
    away keeps about a third of the weight and one on another continent keeps
    nothing, so being close is worth something and being far is still wrong.

    This is the idea PIGEON calls a haversine-smoothed loss. Measured on this
    data it is a modest gain that has to be paid for, and the sweep is worth
    keeping because the trade runs against what this project cares about:

        tau     accuracy   median    calibration error
        off       21.1%   1032 km        1.4%
        150       22.0%   1003 km        1.6%
        300       21.7%    924 km        2.9%
        600       21.4%    850 km        6.6%
        1200      18.6%    835 km        9.0%

    Wider smoothing pulls the median in and pushes calibration out, because a
    label spread over half a continent teaches the model that many cells are
    partly right and its probabilities stop meaning anything sharp. 150 km is
    the default here: most of the accuracy, nearly all of the calibration.

    Anyone wanting the distance number instead should raise it and say what it
    cost. One matrix, computed once, so the sweep is cheap to redo.
    """
    n = len(cells)
    dist = torch.zeros(n, n)
    for i, a in enumerate(cells):
        for j, b in enumerate(cells):
            if j > i:
                d = haversine(a.lat, a.lon, b.lat, b.lon)
                dist[i, j] = dist[j, i] = d
    targets = torch.exp(-dist / tau_km)
    return targets / targets.sum(dim=1, keepdim=True)


def fit_head(X, y, n_classes, epochs=60, lr=1e-3, wd=1e-4, dev="cpu",
             soft_targets: torch.Tensor | None = None):
    """One linear layer, Adam, weight decay. Seconds on a laptop.

    With `soft_targets` the loss is cross-entropy against a distance-smoothed
    distribution rather than against a one-hot label, which is the whole
    difference between learning geography and learning 236 arbitrary bins.
    """
    model = nn.Linear(X.shape[1], n_classes).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    hard_loss = nn.CrossEntropyLoss()
    Xt = torch.tensor(X, dtype=torch.float32, device=dev)
    yt = torch.tensor(y, dtype=torch.long, device=dev)
    soft = soft_targets.to(dev) if soft_targets is not None else None

    for _ in range(epochs):
        perm = torch.randperm(len(Xt), device=dev)
        for i in range(0, len(Xt), 512):
            idx = perm[i:i + 512]
            opt.zero_grad()
            logits = model(Xt[idx])
            if soft is None:
                loss = hard_loss(logits, yt[idx])
            else:
                loss = -(soft[yt[idx]] * torch.log_softmax(logits, dim=1)).sum(dim=1).mean()
            loss.backward()
            opt.step()
    return model


def fit_temperature(logits: torch.Tensor, y: torch.Tensor) -> float:
    """The one number that makes a confidence mean something.

    Optimised against held-out data only. Fitting it on the training set would
    calibrate the model to answers it has already seen, which is the same
    mistake as reporting training accuracy.
    """
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=60)
    loss_fn = nn.CrossEntropyLoss()

    def closure():
        opt.zero_grad()
        loss = loss_fn(logits / log_t.exp(), y)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.exp().item())


def calibration_table(probs: np.ndarray, correct: np.ndarray, bins=10):
    """Stated confidence against observed accuracy, and the gap between them."""
    conf = probs.max(axis=1)
    rows, ece = [], 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = (conf > lo) & (conf <= hi)
        if not sel.any():
            continue
        stated, observed, n = conf[sel].mean(), correct[sel].mean(), int(sel.sum())
        rows.append((lo, hi, n, stated, observed))
        ece += n / len(conf) * abs(stated - observed)
    return rows, ece


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("cluster", "admin"), default="cluster",
                    help="how cells are drawn: from data density, or from "
                         "national borders split by density inside each country")
    ap.add_argument("--per-cell", type=int, default=300,
                    help="admin mode only: points before a country is split")
    ap.add_argument("--cells", type=int, default=300)
    ap.add_argument("--min-count", type=int, default=25)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--tau-km", type=float, default=150.0,
                    help="how far the smoothed label reaches. 0 turns smoothing "
                         "off and falls back to a one-hot target")
    ap.add_argument("--seed", type=int, default=20260822)
    args = ap.parse_args()

    X, y, groups, points, cells, origins = load_data(
        args.cells, args.min_count, args.mode, args.per_cell)
    train, val = split_by_location(groups, args.val_frac, args.seed)
    print(f"{len(X)} images, {len(cells)} {args.mode} cells, "
          f"{len(np.unique(groups))} seed locations")
    print(f"  train {train.sum()}  val {val.sum()}  "
          f"(split by location, so no box appears in both)")

    soft = haversine_targets(cells, args.tau_km) if args.tau_km > 0 else None
    if soft is not None:
        print(f"  labels smoothed over {args.tau_km:.0f} km, so a near miss "
              "scores better than a far one")
    model = fit_head(X[train], y[train], len(cells), epochs=args.epochs,
                     soft_targets=soft)
    with torch.no_grad():
        logits = model(torch.tensor(X[val], dtype=torch.float32))
    yv = torch.tensor(y[val], dtype=torch.long)

    pred = logits.argmax(dim=1).numpy()
    correct = pred == y[val]
    print(f"\ncell accuracy      {correct.mean():.1%}   "
          f"(chance is {1 / len(cells):.2%})")

    # What the answer actually is: the predicted cell's centroid.
    centroids = {c.id: (c.lat, c.lon) for c in cells}
    errors = np.array([haversine(*centroids[int(p)], *points[val][i])
                       for i, p in enumerate(pred)])
    med = float(np.median(errors))
    print(f"median distance    {med:>6.0f} km   "
          f"within 750 km {np.mean(errors <= 750):.0%}, "
          f"within 200 km {np.mean(errors <= 200):.0%}")

    temperature = fit_temperature(logits, yv)
    raw = torch.softmax(logits, dim=1).numpy()
    cal = torch.softmax(logits / temperature, dim=1).numpy()
    _, ece_raw = calibration_table(raw, correct)
    rows, ece_cal = calibration_table(cal, correct)

    direction = ("overconfident, the usual case" if temperature > 1
                 else "underconfident, which is not the usual case")
    print(f"\ntemperature        {temperature:.2f}   ({direction})")
    print(f"calibration error  {ece_raw:.1%} -> {ece_cal:.1%}")
    print(f"\n  {'confidence':<14}{'n':>6}{'stated':>9}{'observed':>10}{'gap':>8}")
    for lo, hi, n, stated, observed in rows:
        print(f"  {lo:.1f} to {hi:.1f}   {n:>6}{stated:>9.0%}{observed:>10.0%}"
              f"{stated - observed:>+8.0%}")

    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "temperature": temperature,
                "n_cells": len(cells), "dim": X.shape[1]}, OUT / "geocell_head.pt")
    save_cells(cells, OUT / "cells.json")
    (OUT / "metrics.json").write_text(json.dumps({
        "images": int(len(X)), "cells": len(cells), "mode": args.mode,
        "train": int(train.sum()), "val": int(val.sum()),
        "cell_accuracy": float(correct.mean()),
        "median_km": med,
        "within_750_km": float(np.mean(errors <= 750)),
        "within_200_km": float(np.mean(errors <= 200)),
        "temperature": temperature, "tau_km": args.tau_km,
        "ece_raw": ece_raw, "ece_calibrated": ece_cal,
    }, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(ROOT)}/geocell_head.pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
