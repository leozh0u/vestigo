# Arm B: image plus real capture metadata

Same eight rural images as arm A, same model, same prompt, plus the metadata
that genuinely came with each photograph: capture timestamp in UTC and camera
compass heading. No invented context.

## Result

| | arm A | arm B |
|---|---|---|
| median error | 94 km | 111 km |
| mean error | 158 km | 121 km |
| country correct | 8/8 | 8/8 |

| | arm A | arm B | delta |
|---|---|---|---|
| Brazil | 668 km | 192 km | -476 |
| United Kingdom | 167 km | 108 km | -59 |
| Chile | 80 km | 25 km | -55 |
| Spain | 11 km | 12 km | +1 |
| Poland | 109 km | 113 km | +5 |
| Mexico | 25 km | 45 km | +20 |
| Germany | 160 km | 197 km | +37 |
| Thailand | 46 km | 277 km | +231 |

## This experiment cannot answer the question it was built for

Median moved one way and mean moved the other. Both are driven by a single
image. At n=8 that is what noise looks like, not an effect.

The deeper problem is the design. Arm B changed two things at once: it added
metadata **and** it re-sampled the model. A 476 km improvement on an image where
the model explicitly stated it could not use the metadata (fully overcast, no
shadows) is not evidence about metadata. It is evidence that two runs of the
same model on the same image disagree by hundreds of kilometres.

**What was needed first is an arm A2**: identical prompt, no metadata, run a
second time, to measure the model's own run-to-run variance. Without that
baseline the arm B deltas are uninterpretable, and no amount of extra images
fixes it. Adding that control before rerunning.

## What can be said

**Country accuracy was unchanged at 8/8.** Metadata neither helped nor harmed
the one thing the model was already reliable at.

**No measurable gain in point accuracy.** Which is at least consistent with the
physics: solar position gives a latitude band and a longitude from solar time.
It is a coarse constraint and should not sharpen a local estimate.

**Both times the model reasoned from a timestamp to a coordinate, it got
worse.** Thailand and Mexico are the only two cases where it said the metadata
changed its answer, and both degraded. Thailand is the clearest: the model
derived local solar time near 18:15-18:45, correctly bounded longitude to +100
to +110, and that band contains the truth at 100.25. It then chose 102.8 inside
the band, six times worse than its image-only guess of 100.6.

n=2 is not a finding. But the mechanism is worth designing against: a correct
coarse constraint pulling a point estimate away from a better visual one.

## Consequence for the build

Solar geometry belongs in code as a filter over candidates, not in a prompt as
something a model reasons from. Compute the band, discard hypotheses outside it,
keep the visual estimate for precision within it.

That needs a claim type the design does not currently have. The evidence board
models point claims with a confidence. It has no way to express "latitude
between 15 and 20 north, from solar geometry" as a constraint that eliminates
rather than competes.
