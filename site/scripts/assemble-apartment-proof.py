"""Validate and encode one complete local render. Does not publish the intro."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("directory", type=Path)
args = parser.parse_args()
root = args.directory.resolve()
camera = json.loads((root / "camera.json").read_text())
timings = json.loads((root / "timings.json").read_text())
count = len(camera)
expected = list(range(1, count + 1))
if count != 144 or [v["frame"] for v in camera] != expected:
    raise ValueError("Expected the complete 144-frame camera path")
if [v["frame"] for v in timings] != expected:
    raise ValueError("The complete frame sequence has not finished rendering")
frames = [root / f"frame-{i:04d}.png" for i in expected]
dimensions, digests = set(), []
for frame in frames:
    data = frame.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG: {frame}")
    dimensions.add(struct.unpack(">II", data[16:24]))
    digests.append(hashlib.sha256(data).hexdigest())
if len(dimensions) != 1:
    raise ValueError("Mixed frame dimensions")
width, height = next(iter(dimensions))
if width % 2 or height % 2:
    raise ValueError("H.264 proof dimensions must be even")
if len(set(digests)) < count * 0.95:
    raise ValueError("Repeated frames: the camera or renderer may have stalled")
for previous, current in zip(camera, camera[1:]):
    if not all(math.isfinite(n) for n in current["camera"]):
        raise ValueError("Invalid camera coordinates")
    if current["camera"][1] <= previous["camera"][1]:
        raise ValueError("Camera does not move continuously forward")
corners = [(0, 1), (1, 1), (1, 0), (0, 0)]
error = max(abs(a-b) for p, q in zip(camera[-1]["screen"], corners) for a, b in zip(p, q))
if error > 0.002:
    raise ValueError("Final screen alignment exceeds 0.2% of the frame")
output = root / "window-to-screen.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(root / "frame-%04d.png"),
                "-frames:v", str(count), "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames,r_frame_rate,width,height", "-of", "json",
                        str(output)], capture_output=True, text=True, check=True)
stream = json.loads(probe.stdout)["streams"][0]
if int(stream["nb_read_frames"]) != count or stream["r_frame_rate"] != "24/1":
    raise ValueError("Encoded frame count or cadence mismatch")
review = json.loads((root / "review.json").read_text()) if (root / "review.json").exists() else {}
report = {
    "artifact": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "frames": count, "fps": 24, "duration_seconds": count / 24, "resolution": [width, height],
    "unique_frame_hashes": len(set(digests)), "final_screen_error": error,
    "render_seconds": sum(v["seconds"] for v in timings),
    "mechanical_checks": "pass", "visual_quality": review.get("overall", "requires independent review"),
    "visual_review_evidence": review.get("evidence"),
    "full_intro": False, "unverified": ["city connection", "live browser takeover", "responsive framing"],
}
(root / "proof-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
