"""Compare arm A, arm A2 (repeat, no metadata) and arm B (metadata).

Arm B on its own is uninterpretable: it added metadata and re-sampled the model
in the same step, so any change could be either. Arm A2 is the control that
separates them. It is the same prompt as arm A, run again, with no metadata.

For each image:
  noise    = distance between the arm A and arm A2 guesses
  effect   = distance between the arm A and arm B guesses

A metadata effect only counts as real if it is clearly larger than that image's
own noise. Where effect is within noise, nothing was measured.
"""
import json
import math
import pathlib
import statistics


def hav(a, b, c, d):
    r = 6371.0088
    p1, p2 = math.radians(a), math.radians(c)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))


def load(name):
    return {r["file"]: r for r in json.loads(pathlib.Path(f"eval/{name}.json").read_text())}


def main():
    truth = {e["file"]: e["truth"]
             for e in json.loads(pathlib.Path("data/manifest.json").read_text())}
    A, A2, B = load("arm_a"), load("arm_a2"), load("arm_b")

    rows = []
    for f in sorted(A2):
        t = truth[f]
        ea = hav(t["lat"], t["lon"], A[f]["lat"], A[f]["lon"])
        e2 = hav(t["lat"], t["lon"], A2[f]["lat"], A2[f]["lon"])
        eb = hav(t["lat"], t["lon"], B[f]["lat"], B[f]["lon"])
        noise = hav(A[f]["lat"], A[f]["lon"], A2[f]["lat"], A2[f]["lon"])
        effect = hav(A[f]["lat"], A[f]["lon"], B[f]["lat"], B[f]["lon"])
        rows.append({"country": A[f]["country"], "err_a": ea, "err_a2": e2,
                     "err_b": eb, "noise": noise, "effect": effect,
                     "said": B[f].get("metadata_effect", "")})

    print(f"{'country':<16}{'errA':>7}{'errA2':>7}{'errB':>7}"
          f"{'noise':>8}{'effect':>8}  verdict")
    print("-" * 74)
    real = 0
    for r in rows:
        # An effect is only distinguishable from noise if it clearly exceeds it.
        if r["effect"] > max(r["noise"] * 2, 25):
            verdict = "metadata moved it"
            real += 1
        elif r["effect"] < r["noise"]:
            verdict = "within noise"
        else:
            verdict = "ambiguous"
        print(f"{r['country']:<16}{r['err_a']:>6.0f}k{r['err_a2']:>6.0f}k"
              f"{r['err_b']:>6.0f}k{r['noise']:>7.0f}k{r['effect']:>7.0f}k  {verdict}")
    print("-" * 74)
    for k, label in (("err_a", "arm A"), ("err_a2", "arm A2"), ("err_b", "arm B")):
        v = [r[k] for r in rows]
        print(f"  {label:<7} median {statistics.median(v):>6.0f} km   mean {statistics.mean(v):>6.0f} km")
    n = [r["noise"] for r in rows]
    print(f"\n  run-to-run noise, no metadata: median {statistics.median(n):.0f} km, "
          f"max {max(n):.0f} km")
    print(f"  images where metadata clearly moved the answer: {real}/{len(rows)}")


if __name__ == "__main__":
    main()
