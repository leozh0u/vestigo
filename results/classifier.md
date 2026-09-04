# The geocell classifier

Phase 3.5. The only model in this project that I trained, and the only evidence
source whose confidence is measured rather than asserted.

No API spend. Sixty-five thousand images fetched from a free API, embeddings
computed once on the laptop GPU, a linear head that trains in ninety seconds.

    ./.venv/bin/python scripts/fetch_training.py --target 200000 --per-place 150 --spread-km 180
    ./.venv/bin/python ml/embed.py
    ./.venv/bin/python ml/train.py

## What it is

A photograph goes through a frozen CLIP encoder, which turns it into 512
numbers. One linear layer maps those numbers onto 250 geocells. The predicted
cell's centroid is the answer.

Frozen is the simplification that makes this runnable on a laptop. PIGEON
fine-tuned CLIP itself against synthetic geographic captions, which needs real
GPUs and weeks. Caching the embeddings means the encoder runs once, twenty
thousand images in two and a half minutes, and the head can then be retrained
fifty times an afternoon while the cells change.

The cost of freezing, stated because it bounds everything below: the head can
only separate places that already look different to CLIP. Anything needing
geographic knowledge CLIP does not hold is out of reach.

## The cells

Not a latitude and longitude grid. What a photograph shows changes at borders
and not at round numbers: road paint, plate shapes, signage script, which side
of the road people drive on. A grid cuts through all of that.

PIGEON builds cells from administrative boundaries and publishes neither the
boundaries nor the weights, so these are built by clustering the training points
themselves. Dense regions get small cells, empty regions get none. That is
honest rather than convenient: a classifier cannot predict a cell it has never
seen an image from, and pretending otherwise turns missing data into a confident
wrong answer.

Two details that took a rewrite each.

**Clustering happens on the unit sphere.** A degree of longitude is 111 km at
the equator and 20 km at 70 north, and the dateline puts neighbours 358 apart.

**Seeding is furthest-point, not random.** The training set is 39% European.
Random seeds on data that lopsided produce cells just as lopsided and leave a
continent inside one enormous cell.

250 cells, at least 25 images each after undersized cells are folded into
their nearest neighbour. Cells below that are not classes, they are places the
head would memorise.

## The training data

64,865 Mapillary images, seeded near 161 populated places and thrown a random 5
to 180 km in a random direction, so they land on ring roads, farmland and the
routes between towns rather than on the tourist streets that made the urban
half of the eval set too easy.

| region | images | share |
|---|---|---|
| Europe | 26,904 | 41% |
| Asia | 13,208 | 20% |
| North America | 10,157 | 16% |
| Africa and Middle East | 5,746 | 9% |
| South America | 5,085 | 8% |
| Oceania | 3,765 | 6% |

64% sits north of 25 degrees, and the skew got worse rather than better as the
set grew: more data from a source that is already lopsided is more lopsided
data. The fetcher prints that figure itself rather than leaving it to be
discovered, because a single accuracy number over a set this skewed says less
than it appears to.

Training and eval are kept apart by construction. Seeds come from a global place
list rather than from the eval locations, and any seed within 25 km of an eval
image is dropped. Metadata is stripped on save, or the head could read the
answer off the file instead of the picture.

## The split is the most important line in train.py

Whole seed locations go to train or to validation, never both.

The fetcher drew several photographs from each 10 km box, so a random split
would put pictures taken metres apart on either side of it and report recall
dressed as accuracy. 12,337 locations, split by location: 51,856 images to
train and 13,009 to validate.

This makes every number below lower and worth reading.

## Results

| | 20,000 images | 65,000 images |
|---|---|---|
| cell accuracy | 21.5% | **31.9%** |
| chance | 0.42% | 0.40% |
| median distance | 1,024 km | **527 km** |
| within 750 km | 44% | 56% |
| within 200 km | 29% | 37% |

Eighty times chance, and still far worse than a frontier model call, which
managed 94 km median on rural imagery of the same kind. DECISIONS.md predicted
exactly this before any of it was built: country-level accuracy respectable,
anything finer well short.

### Data volume was the binding constraint, and that was worth proving

Two attempts to improve the model without more data both failed. Haversine
label smoothing cost calibration and bought nothing; administrative-boundary
cells lost to clustering, 32.0% against 36.0%. Both are written up below,
because a prediction that measured wrong is the part of this file worth
reading.

The third attempt was 3.2x the data and it nearly halved the median. That is
the answer to which of the three guesses was right, and it took a fetch rather
than an argument.

### Cell count stopped mattering once the data grew

At 20,000 images the number of cells traded accuracy against distance and
neither end was good:

| cells | accuracy | median distance |
|---|---|---|
| 91 | 37.3% | 956 km |
| 236 | 21.5% | 1,024 km |
| 314 | 18.4% | 1,126 km |

At 65,000 the same sweep is flat over a five-fold range:

| cells | accuracy | median distance | calibration error |
|---|---|---|---|
| 103 | 46.6% | 550 km | 0.7% |
| 250 | 31.9% | **527 km** | 2.6% |
| 493 | 24.3% | 531 km | 5.8% |

Accuracy still falls as cells get smaller, because a smaller cell is a harder
class, but the distance the answer is wrong by barely moves. Cell count was
never the lever; it only looked like one while the data was thin. 250 is kept
because it holds the best within-200 km rate at effectively the best median.

### What data would still buy

The fetch that produced these 65,000 images made 191,450 queries and **166,258
of them failed** with transient network errors, an 87% failure rate against a
free API being asked for more than it wants to give. So this is what got
through rather than what exists, and a rerun with better backoff would likely
pass 150,000.

Whether that is worth doing is a different question. The trend across 20k and
65k is roughly a halving of the median per 3.2x of data, which puts 200,000
near 350 km and a million near 250 km, and 250 km still loses to one API call
by a factor of three. The classifier earns its place through calibration, not
through distance, and it already has that.

## Calibration, which is the result worth having

| | before | after |
|---|---|---|
| expected calibration error | **12.9%** | **2.6%** |

One number, fitted on held-out data, and stated confidence then tracks observed
accuracy to within a few points across the whole range:

| stated confidence | n | stated | observed | gap |
|---|---|---|---|---|
| 0.0 to 0.1 | 907 | 8% | 7% | +1% |
| 0.1 to 0.2 | 4,106 | 15% | 17% | -2% |
| 0.2 to 0.3 | 3,166 | 25% | 28% | -3% |
| 0.3 to 0.4 | 1,880 | 34% | 36% | -2% |
| 0.4 to 0.5 | 1,196 | 45% | 49% | -4% |
| 0.5 to 0.6 | 691 | 54% | 58% | -3% |
| 0.6 to 0.7 | 442 | 65% | 71% | -6% |
| 0.7 to 0.8 | 303 | 75% | 80% | -6% |
| 0.8 to 0.9 | 212 | 85% | 92% | -8% |
| 0.9 to 1.0 | 106 | 94% | 99% | -5% |

Every gap is negative above the first band, which says the head stays a little
underconfident even after scaling, and that is the safe direction to be wrong
in: a claim leaning on this number leans slightly less far than it could.

The coarser the cells, the better this gets. At 103 cells the error after
scaling is 0.7%, near the floor of what the validation set can measure. Fewer
classes means more examples per class means a probability with more behind it,
and that is a real trade against the finer answer 250 cells gives.

## Haversine-smoothed labels, and what they cost

Plain cross-entropy scores the neighbouring cell exactly as wrong as the
opposite hemisphere, which for a geographic task throws away most of the
signal. The fix is PIGEON's: spread each label over nearby cells by distance,
so being close is worth something.

I expected this to be the cheapest large gain available. Measured, it is a
modest gain that has to be paid for:

| smoothing | accuracy | median | calibration error |
|---|---|---|---|
| off | 21.1% | 1,032 km | **1.4%** |
| 150 km | **22.0%** | 1,003 km | 1.6% |
| 300 km | 21.7% | 924 km | 2.9% |
| 600 km | 21.4% | 850 km | 6.6% |
| 1,200 km | 18.6% | 835 km | 9.0% |

Wider smoothing pulls the median in and pushes calibration out. A label spread
over half a continent teaches the model that many cells are partly right, and
its probabilities stop meaning anything sharp. That trade runs directly against
what this project is for, so the default is 150 km: most of the accuracy gain,
nearly all of the calibration kept.

The honest reading is that the loss shape is not the binding constraint here.
76 images per class and a frozen encoder are, and no amount of reshaping the
target fixes either.

## Cells drawn from borders, which did not work

The cells above are clustered from the training points, so their boundaries sit
wherever the data thins out. That is not what the pictures look like: road
paint, plate shapes, signage script and which side of the road people drive on
change at a national border and nowhere else. PIGEON builds cells from ranked
administrative divisions for exactly this reason.

Built the simplified version, one level: assign every point to its country from
Natural Earth boundaries, split countries holding too many points by density,
absorb ones holding too few. At a matched cell count:

| cells | accuracy | median | calibration error |
|---|---|---|---|
| **clustered** | **36.0%** | **903 km** | 1.0% |
| admin borders | 32.0% | 1,157 km | 1.9% |

Worse on every measure. The likely reason is mechanical rather than
conceptual. Clustering minimises spread within a cell by construction, so a
centroid sits close to its members, and a prediction resolves to a centroid. A
cell shaped like Argentina has a centroid far from most of Argentina.

Borders match what the pictures show. Centroids match where the answer goes,
and the metric rewards the second. Kept in the repo with the result recorded,
since it tests one level of hierarchy rather than the ranked and tessellated
scheme in the paper, so it is evidence against this simplification and not
against the idea.

Two smaller things it did surface. 0.3% of Mapillary geotags sit in open ocean
and are dropped as broken rather than pooled, and at 1:50m the coastline is
coarse enough that 4% of points fall outside every polygon, so a point within
120 km of a coast is assigned to it.

## An assumption I had written down and got wrong

A comment in `ml/train.py` said a temperature above 1 means the model was
overconfident, the usual case. Every cell count came back near **0.70**, below
1, meaning the head was *under*confident and the scaling sharpens its
probabilities rather than softening them.

The code now reports which direction it found rather than asserting one. An
assumption in a comment is still an assumption.

## Why this matters to the rest of the project

Not as a locator. At 527 km it will not improve the agent's accuracy and the
tool description says so.

It matters because it is the first evidence source in this project whose
strength is measured. Every other one has a number the model wrote on its own
citation, which is the fault behind the agent overclaiming on 28% of answers: it
could put 0.9 on "dry scrub", and the party grading the evidence had an interest
in the answer.

A calibrated probability is a number a claim may lean on exactly as far as it
says. That is what `max_strength` on an evidence record was for, and until now
nothing could fill it honestly.

On the Mexico image the classifier is wrong, placing it in Central Asia, and
reports 7%. Wrong answer, honestly signalled, ceiling set at 0.07 so no claim
can lean on it. That is the design working, not a disappointment.

## What would make it better

1. **More data.** This was the binding constraint, and 3.2x of it nearly
   halved the median. 65,000 images over 250 cells is 260 per class; PIGEON
   trained on millions, so the ceiling here is a long way up. What it buys is
   also fading: see the arithmetic above.
2. **Unfreezing the encoder**, which needs a real GPU and is the difference
   between this and the published work.
3. **Coverage.** Whole countries have no cell because Mapillary has no imagery
   there, and no amount of training fixes an absence of data.
