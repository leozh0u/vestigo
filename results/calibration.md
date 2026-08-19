# Calibration: the metric the project is actually about

The design claim is that Vestigo answers at the granularity the evidence
supports and stops there, which makes calibration the headline number and
distance error a supporting one. Every result before this was distance error,
because nothing scored granularity. This does.

Reproduce with `./.venv/bin/python eval/calibrate.py`. No model calls and no
network. It runs on the arm A answers, which already recorded a granularity and
a confidence for all 28 images.

## How a claim is judged

A claim counts as correct if the truth falls inside the radius its level
implies. The radii are the standard IM2GPS bands rather than new numbers, so a
result here can still be read next to published ones.

| level | radius |
|---|---|
| continent | 2500 km |
| country | 750 km |
| region | 200 km |
| city | 25 km |
| district or street | 5 km |
| point | 1 km |

A radius is a stand-in for the real test, which is whether the point falls
inside the named administrative boundary. That needs a boundary lookup, and
until there is one this over-credits a claim near the edge of a large country
and under-credits one in the middle of a small one.

## The headline

| source | n | correct at the level claimed | overclaimed | underclaimed | median error |
|---|---|---|---|---|---|
| IM2GPS | 10 | 90% | 10% | 70% | 2.6 km |
| Mapillary, city centres | 10 | 90% | 10% | 80% | 0.6 km |
| Mapillary, rural roads | 8 | 88% | 12% | 62% | 94.2 km |
| all | 28 | 89% | 11% | 71% | 7.5 km |

**The rural row is the one that changes.** Distance error put it at a 94 km
median, which reads as the half where the system fails. Scored on what it
claimed, 88% of those answers were correct, and the gap to the other two rows
is four points rather than a factor of 130. Both numbers are true. They are
answers to different questions, and the second is the question this project
asked.

Ten answers are correct under one metric and failures under the other, and they
are the whole argument:

| image | claimed | error | |
|---|---|---|---|
| mapillary_3afe051f4f | country | 502 km | correct, and a failure by distance |
| im2gps_d6223a52f3 | country | 293 km | correct, and a failure by distance |
| im2gps_04881af57a | country | 286 km | correct, and a failure by distance |
| rural_97a65d8135 | country | 167 km | correct, and a failure by distance |
| rural_42816b32de | country | 160 km | correct, and a failure by distance |
| rural_3e5efad504 | country | 109 km | correct, and a failure by distance |
| im2gps_2d187a1317 | country | 95 km | correct, and a failure by distance |
| rural_58bb638a1b | region | 80 km | correct, and a failure by distance |
| rural_cb06bab2f5 | country | 46 km | correct, and a failure by distance |
| rural_7ee09e498b | region | 25 km | correct, and a failure by distance |

Not one image goes the other way. There is no answer here that distance calls a
success and granularity calls a failure, which says the model was not sneaking
precision past a loose metric.

## It underclaims far more than it overclaims

71% against 11%. On seven answers in ten the model stopped at a coarser level
than its own accuracy would have supported: claiming a country and landing
2.6 km away.

That is the design working in one direction and leaving a great deal on the
table in the other. Overclaiming is the failure to drive to zero and it is
already at 11%. Underclaiming is not a failure, and a metric that punished it
would push the system straight back to confident precision. But 71% is a lot of
specificity given up, and closing it is a different piece of work from getting
more accurate: the answers are already there and the system will not commit to
them.

## Calibration

| stated | n | promised | observed | gap | median | worst |
|---|---|---|---|---|---|---|
| high | 10 | 90% | 90% | 0 | 0.4 km | 30 km |
| medium | 13 | 60% | 85% | -25% | 95.1 km | 1545 km |
| low | 5 | 30% | 100% | -70% | 46.0 km | 293 km |

Expected calibration error 24%.

**High confidence is exactly calibrated.** Promised 90%, delivered 90%, over
ten calls.

**Everything else is underconfident, not overconfident.** Low confidence answers
were correct at the level they claimed every single time, because the model
correctly downgrades its granularity when it is unsure. It says low confidence
and country, and it gets the country right. Under distance scoring that looked
like the honestly bad band. It is not bad, it is a coarse claim being kept.

The promised column is a reading of the words rather than a measurement. Phase 5
replaces it with values fitted to this curve, and every calibration error above
inherits the assumption until then.

## What happened to the bimodal medium band

Phase 0's sharpest finding was that medium confidence is not a wide band but a
split one: four answers under a kilometre, then 95, 502 and 1545 km. Measured
against what each answer actually claimed:

| band | worst broken promise |
|---|---|
| high | 6.0x |
| medium | 61.8x |
| low | 0.4x, none broken |

The finding survives and gets sharper. Medium is still the band that fails, and
now by how much: its worst answer landed 62 times further out than the level it
claimed allows. Low never breaks its claim at all. High breaks its claim once,
by 6x, which is the 30 km worst case against a street-level promise.

The first version of this metric was worst error over median error, which ranked
high confidence as the most erratic band purely because its median was 400 m.
That is the same mistake as scoring a country claim by distance, one level up,
and it is why the metric is a ratio to the claim rather than to the median.

## Variance, and why every run needs repeat sampling

Three runs exist per rural image: arm A, arm A2 and arm B.

| image | median | best | worst | spread | correct | stable |
|---|---|---|---|---|---|---|
| rural_2dafd2f200 | 668 km | 192 | 669 | 537 km | 33% | yes |
| rural_3e5efad504 | 113 km | 109 | 118 | 14 km | 100% | yes |
| rural_1e85f5921d | 12 km | 11 | 12 | 22 km | 100% | yes |
| rural_cb06bab2f5 | 199 km | 46 | 277 | 246 km | 100% | no |
| rural_58bb638a1b | 43 km | 25 | 80 | 57 km | 100% | yes |
| rural_42816b32de | 160 km | 119 | 197 | 83 km | 100% | yes |
| rural_97a65d8135 | 114 km | 108 | 167 | 65 km | 100% | yes |
| rural_7ee09e498b | 45 km | 25 | 14970 | 14964 km | 67% | no |

Median spread 74 km, worst 14,964 km. Six of eight sets agree closely enough to
be read as one answer, where the threshold is the radius of the level the median
error earned, so country-level answers are allowed to disagree by more than
street-level ones.

A single-sample eval reports one column of that table. It would have reported
rural_7ee09e498b as a 25 km success or a 14,970 km disaster depending on which
run it happened to draw, and nothing in the output would say which.

## What to fix, in order

1. **The underclaim rate.** 71% of answers are coarser than the evidence
   already supports. That is the largest single number on this page and it is
   not an accuracy problem.
2. **Medium confidence.** It breaks its claim by 62x at worst while sitting at
   85% overall, so the band is carrying two populations that nothing in the
   output separates.
3. **Fitted confidence values.** Every gap here is measured against numbers
   read off the words rather than fitted, so the 24% calibration error is an
   estimate of an estimate.
4. **Real boundary checks** instead of radii, which is what makes "the country
   was correct" a fact rather than a proxy.
