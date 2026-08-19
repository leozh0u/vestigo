# Three arms: does real capture metadata help?

Eight rural images. Three conditions:

- **arm A** image only
- **arm A2** image only, run a second time (the control for run-to-run variance)
- **arm B** image plus real capture timestamp and camera compass heading

Arm A2 exists because arm B on its own changed two things at once, the metadata
and a fresh sample of the model, so any difference could be either.

## Numbers

| | median | mean |
|---|---|---|
| arm A | 80 km | 165 km |
| arm A2 | 119 km | 2304 km |
| arm B | 108 km | 122 km |

Per image, `noise` is the distance between the two no-metadata runs and `effect`
is the distance between arm A and arm B:

| country | err A | err A2 | err B | noise | effect |
|---|---|---|---|---|---|
| Spain | 11 km | 12 km | 12 km | 16 km | 10 km |
| Brazil | 668 km | 669 km | 192 km | 1 km | 536 km |
| Germany | 160 km | 119 km | 197 km | 42 km | 41 km |
| Chile | 80 km | 43 km | 25 km | 38 km | 57 km |
| Mexico | 25 km | 14970 km | 45 km | 14951 km | 30 km |
| United Kingdom | 167 km | 114 km | 108 km | 62 km | 65 km |
| Thailand | 46 km | 199 km | 277 km | 165 km | 246 km |

## Run-to-run noise is large and heavy tailed

Median 42 km, and on one image 14,951 km. Two runs of the same model on the same
photograph with an identical prompt can disagree by a continent.

That settles the earlier question. The arm A to arm B median difference, 80 km
against 108 km, sits well inside that noise. **Metadata produced no measurable
improvement in point accuracy**, which is what the physics predicts: solar
position yields a latitude band and a longitude from solar time, so it is a
coarse constraint and should not sharpen a local estimate.

One image shows a clear effect. Brazil moved 536 km with only 1 km of noise, and
improved from 668 km to 192 km.

## The Mexico case, and why the metric above is wrong

Mexico is the most informative image in the set and the table mishandles it.

- arm A: Mexico, 25 km error. The reasoning flagged "East African (Kenyan)
  acacia scrub is a plausible alternative".
- arm A2, same prompt, no metadata: **Kenya**, 14,970 km error. The model took
  the alternative it had already named.
- arm B, with metadata: Mexico, 45 km, and the reasoning stated that 21:35 UTC
  with a front-lit scene on an easterly heading forces mid-afternoon local solar
  time and a longitude near -100, ruling out East Africa.

By displacement the effect is 30 km and the script calls it "within noise",
because the noise on that image is 14,951 km. That verdict is arithmetically
right and analytically useless.

The metadata did not move the answer. It **held the answer still**. Without it
the model flips continents between runs on this image; with it, it does not, for
a stated and correct physical reason.

**A constraint is not measured by how far it moves an estimate. It is measured
by which candidates it eliminates and how much it reduces variance.** Distance
displacement cannot see that, so it is the wrong metric for this class of
evidence, the same way raw distance error was the wrong metric for a claim made
honestly at country granularity.

## What to build from this

Two things the design does not currently support.

**A constraint claim.** The board models point claims with confidences. It needs
a way to express "latitude between 15 and 20 north, from solar geometry" as
something that discards candidates rather than competing with them as another
point estimate. On the Thailand image the model derived a correct longitude band
containing the truth, then picked a point inside it six times worse than its own
image-only guess. The band was right; treating it as a point was wrong.

**Variance as a first-class metric.** Every eval run should sample each image
more than once. A single-sample eval on this data would report a median that
moves 40 km on rerun and cannot distinguish a real improvement from a reroll.
That applies to the agent as much as to the baseline.
