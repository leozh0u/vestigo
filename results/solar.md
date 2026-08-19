# Solar geometry: what a timestamp rules out

Phase 1. The first tool, measured on the eight rural images. No model calls and
no network, because everything it needs is already in `data/manifest.json`: a
true capture time in UTC and a camera compass heading for every image.

Reproduce with `./.venv/bin/python eval/solar_check.py`.

## The tool runs the equations forwards

The plan had this backwards, and said so: measure a shadow, invert the
equations, get a latitude band. That is the harder half of the problem and it
throws away the azimuth, which is the half that carries longitude.

A constraint is asked `admits(point)` one point at a time, so the equations can
run forwards instead. Compute where the sun was at the candidate at that
instant, compare it to what the photograph shows, score. Forward is exact where
inversion is approximate, and there is no algebra to get wrong.

What falls out is cheaper than the plan assumed. **The strongest single
constraint needs no shadow measurement and no sun in the frame.** It needs only
that the photograph was taken in daylight, which is the one reading a vision
model does not get wrong. Fix the instant and 49% of the earth is in the dark.

## The algorithm checks out

NOAA's solar position algorithm, following Meeus. Checked against quantities
that are true by definition rather than a table:

| check | expected | got |
|---|---|---|
| Julian day at the J2000 epoch | 2451545.0 | 2451545.0 |
| declination, March equinox 2024 | 0 | +0.0005 |
| declination, September equinox 2024 | 0 | -0.0018 |
| declination, June solstice 2024 | +23.44 | +23.4386 |
| declination, December solstice 2024 | -23.44 | -23.4386 |
| azimuth at local solar noon, 51.5N | 180 | 180.0 |
| elevation at local solar noon | 90 - abs(lat - decl) | within 0.1 |

Then swept, rather than only checked at named instants, because a sign error or
a hemisphere assumption can sit quietly inside a formula that happens to be
right on the one date anyone tested:

| swept check | result |
|---|---|
| noon elevation against its closed form plus refraction, 132 place-dates | within 0.01 |
| noon bearing due south or due north by the declination, 100+ place-dates | within 0.5 |
| solar noon lands on a zero hour angle, 7 longitudes | within 0.02 |
| antipodal elevations cancel once refraction is removed, 61 pairs | within 0.005 |
| share of the earth lit, 12 dates through the year | 49% to 53% |
| elevation peaks at solar noon and falls either side | holds |

The bearing sweep is there for a specific trap. "Sun in the south means northern
hemisphere" holds outside the tropics and fails inside them, because what the
bearing at noon reports is which side of the subsolar latitude you stand on,
and that latitude swings 23.4 degrees either way across the year. Running the
geometry forwards sidesteps the trap rather than solving it, since a candidate
is only ever asked whether it fits.

Two of these failed first time and neither was a fault in the geometry. Both
were refraction: the closed forms give the true elevation and `sun_position`
returns the apparent one, so the residual was exactly the refraction every
time. The tests now include refraction and are checked ten times tighter than
they were when they failed.

## The sun at ground truth

| image | country | capture, UTC | elevation | sun bearing |
|---|---|---|---|---|
| rural_2dafd2f200 | Brazil | 2026-05-24 15:29:08 | 46.5 | 354 |
| rural_3e5efad504 | Poland | 2017-08-19 11:50:23 | 47.5 | 205 |
| rural_1e85f5921d | Spain | 2024-05-03 12:55:00 | 63.0 | 202 |
| rural_cb06bab2f5 | Thailand | 2024-03-10 11:14:52 | 2.7 | 265 |
| rural_58bb638a1b | Chile | 2022-09-05 11:20:37 | 3.6 | 79 |
| rural_42816b32de | Germany | 2020-06-06 12:19:33 | 59.0 | 208 |
| rural_97a65d8135 | UK | 2017-08-21 16:13:09 | 27.6 | 253 |
| rural_7ee09e498b | Mexico | 2024-04-20 21:35:52 | 47.2 | 266 |

All eight are above the horizon, so "daylight" is the correct reading for every
one of them. Two are marginal: Thailand at 2.7 degrees is near sunset and Chile
at 3.6 is just after sunrise, and on those a model could reasonably say twilight
instead. That is the tool's real error mode and it is not hypothetical.

## The Mexico case, closed

At 2024-04-20 21:35:52 UTC the sun is 47.2 degrees above the horizon over
Querétaro and 79.3 degrees below it over Nairobi. It is the middle of the night
in Kenya. A photograph taken in daylight cannot have been taken there, and
nothing had to be measured off the image to say so.

That is the whole of the Phase 0 metadata finding, derived from physics, with
no model in the loop. Arm A2 put this image in Kenya, 14,970 km out. The
constraint removes that answer and leaves the Mexico answer at admissibility
1.0, untouched.

## On the real baseline guesses

Twenty-four guesses across the eight images, from arm A, arm A2 and arm B.
Daylight is the only reading used.

| | before | after |
|---|---|---|
| candidates ruled out | | 1 of 24 |
| best candidate survived | | 8 of 8 images |
| median error of what was ruled out | | 14,970 km |
| median error of what was kept | | 113 km |
| median spread | 74 km | 61 km |
| **worst spread** | **14,964 km** | **537 km** |
| median error over the set | 114 km | 114 km |

Spread is the distance between the two furthest surviving candidates, which is
how far two runs of the same model on the same photograph are allowed to end up
from each other. Phase 0 measured that at a 40 km median and a 14,951 km
maximum and said a constraint should be judged on what it eliminates and how
much variance it removes rather than on displacement.

Here is that sentence as numbers. **The median error does not move at all. The
worst-case disagreement falls by a factor of 28.** One metric sees the tool
working and the other cannot, which is the argument Phase 0 made, now with the
tool in place rather than in prospect.

The other twenty-three candidates were already in the right country and solar
geometry has nothing to say about any of them. It corrected one answer out of
twenty-four, and that one was wrong by most of the planet.

## How much does it discriminate

Twenty-four guesses that are nearly all correct is a weak test of discriminating
power. So a second set: every image gets the other seven images' true
coordinates as candidates alongside its own. Real places, real instants,
nothing chosen to be easy to reject.

| reading | ruled out | median spread after | best survived |
|---|---|---|---|
| daylight only | 14 of 64 | 13,154 km | 8 of 8 |
| daylight plus a perfect sun bearing | 41 of 64 | 2,439 km | 8 of 8 |

**Daylight alone rejects 22% of wrong continents. Adding the sun's bearing takes
that to 64%.** So the second half of the tool, the half that needs the image
read, is worth building. It roughly triples the discrimination and it collapses
the surviving spread from 13,000 km to 2,400.

The second row is a ceiling and not a result. The sun bearing was taken from
the ground truth rather than from the image, so the truth candidate survives by
construction, not by measurement. What the row establishes is the size of the
prize, which is the number needed before paying for the observation.

The same oracle adds nothing at all on the baseline guesses: identical
elimination, identical spread. That is not a contradiction, it is the shape of
the tool. **The sun's bearing separates continents and says nothing within a
country**, because it barely changes over a few hundred kilometres, and a few
hundred kilometres is where all but one of the real guesses already were.

## Where it is worth the most

It needs nothing from the scene. Text extraction needs signage, a map query
needs mapped features, and a classifier needs training images from somewhere
near the answer. The polar regions, the Sahara and the interior of the Amazon
have none of those. The sun behaves the same everywhere, so this is the one
tool whose accuracy does not fall off where every other tool stops working.

## What this fixes and what it does not

It never cut the best candidate. Thirty-two image-condition pairs, zero false
eliminations. That matters more than the elimination rate, because a constraint
that removes the truth is worse than no constraint at all, and it is the reason
weight sits below 1.0 on everything except the daylight reading.

It does nothing for the actual Phase 0 gap. The rural median is 94 km because
the model knows the country and cannot find the town, and no timestamp fixes
that. Solar geometry stops the catastrophic answer. Going from country to city
needs the tools that read the image.

## Where it is weak

- Two of the eight images are within four degrees of the horizon, so the
  daylight reading that everything rests on is a coin flip on a quarter of the
  set. Twilight needs its own handling rather than a band that happens to
  overlap.
- The three weights (0.97, 0.75, 0.70) are picked, not measured. Measuring them
  needs images annotated with what a model actually reported against what was
  true, which is the next piece of work on this tool.
- The elevation reading is untested. No image here has an annotated shadow
  length, so the low, mid and high bands are asserted and not checked.
- Near the poles in summer the daylight constraint eliminates nothing, and near
  an equinox the declination is near zero, so latitude does not separate. The
  tool is weakest exactly when the sun is least informative, which is worth
  saying out loud rather than reporting one average number.
