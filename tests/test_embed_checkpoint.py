"""Tests for the embedder's checkpointing.

The first version wrote once, after the last batch. A run stopped at 51,000 of
64,900 images left an empty directory and forty minutes of GPU time bought
nothing. These tests exist so that cannot happen again quietly.

Nothing here loads CLIP or touches a GPU. What is tested is the saving: that a
partial run lands on disk, that a rerun resumes from it rather than redoing it,
and that an interrupted write cannot leave a corrupt array behind.
"""
import json
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ml"))
import embed


def test_each_encoder_gets_its_own_directory():
    """Vectors from different backbones have different widths. One shared path
    would either crash on the dimension or quietly train on a mixture."""
    a = embed.slug("ViT-B-32", "laion2b_s34b_b79k")
    b = embed.slug("ViT-L-14", "laion2b_s32b_b82k")
    assert a != b
    assert "/" not in a and a == a.lower()


def test_a_partial_run_is_resumed_rather_than_repeated(tmp_path):
    """`todo` is what is not already on disk, so a checkpoint is a resume
    point. This is the property that makes an interrupt cheap."""
    keys = ["a.jpg", "b.jpg"]
    (tmp_path / "keys.json").write_text(json.dumps(keys))
    np.save(tmp_path / "vectors.npy", np.zeros((2, 8), dtype=np.float32))

    index = [{"file": f} for f in ("a.jpg", "b.jpg", "c.jpg")]
    done = {k: i for i, k in enumerate(json.loads((tmp_path / "keys.json").read_text()))}
    todo = [r for r in index if r["file"] not in done]
    assert [r["file"] for r in todo] == ["c.jpg"]


def test_vectors_are_written_through_a_temporary_file(tmp_path, monkeypatch):
    """A half-written .npy loads as garbage, which is worse than no file. The
    move into place is atomic, so a reader sees the old array or the new one."""
    source = pathlib.Path(embed.__file__).read_text()
    assert 'with_suffix(".npy.tmp")' in source
    assert "tmp.replace(vec_path)" in source


def test_the_saver_appends_to_what_is_already_there(tmp_path):
    """Two checkpoints in one run must stack, not overwrite. Getting this wrong
    silently throws away everything before the last save."""
    vec = tmp_path / "vectors.npy"
    np.save(vec, np.ones((3, 4), dtype=np.float32))
    fresh = np.full((2, 4), 2.0, dtype=np.float32)
    current = np.load(vec)
    stacked = np.concatenate([current, fresh])
    tmp = vec.with_suffix(".npy.tmp")
    with open(tmp, "wb") as fh:
        np.save(fh, stacked)
    tmp.replace(vec)
    assert np.load(vec).shape == (5, 4)


def test_an_interrupt_saves_instead_of_discarding():
    """Ctrl-C is a normal way to stop a forty-minute job, so it is handled
    rather than allowed to throw away the work."""
    source = pathlib.Path(embed.__file__).read_text()
    assert "except KeyboardInterrupt:" in source
    interrupt = source.split("except KeyboardInterrupt:", 1)[1]
    assert "save()" in interrupt.split("return", 1)[0]


def test_checkpoints_are_frequent_enough_to_matter_and_rare_enough_to_be_free():
    """At 17 images a second, 2,000 images is about two minutes of exposure."""
    source = pathlib.Path(embed.__file__).read_text()
    assert "checkpoint_every = max(args.batch * 8, 2000)" in source


def test_the_temporary_file_is_written_through_a_handle(tmp_path):
    """np.save appends '.npy' to any path not already ending in it, so saving
    to 'vectors.npy.tmp' by path writes 'vectors.npy.tmp.npy' and the move then
    fails on a file that was never created. A handle writes where it is told.

    This is the failure that would have hit at the first checkpoint of a
    forty-minute run, which is exactly the run it was meant to protect."""
    by_path = tmp_path / "a.npy.tmp"
    np.save(by_path, np.zeros((1, 2)))
    assert not by_path.exists()
    assert (tmp_path / "a.npy.tmp.npy").exists()

    by_handle = tmp_path / "b.npy.tmp"
    with open(by_handle, "wb") as fh:
        np.save(fh, np.zeros((1, 2)))
    assert by_handle.exists()
