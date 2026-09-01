# The geocell classifier

Phase 3.5. The only model in this project that I trained, and the only evidence
source whose confidence is measured rather than asserted.

No API spend. Twenty thousand images fetched from a free API, embeddings
computed once on the laptop GPU, a linear head that trains in seconds.

    ./.venv/bin/python scripts/fetch_training.py --target 20000 --per-place 150 --spread-km 180
    ./.venv/bin/python ml/embed.py
    ./.venv/bin/python ml/train.py

## What it is

A photograph goes through a frozen CLIP encoder, which turns it into 512
numbers. One linear layer maps those numbers onto 236 geocells. The predicted
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

236 cells, median radius 127 km, at least 25 images each after undersized cells
are folded into their nearest neighbour. Cells below that are not classes, they
are places the head would memorise.

## The training data

20,000 Mapillary images, seeded near 161 populated places and thrown a random 5
to 180 km in a random direction, so they land on ring roads, farmland and the
routes between towns rather than on the tourist streets that made the urban
half of the eval set too easy.

| region | images | share |
|---|---|---|
| Europe | 7,755 | 39% |
| Asia | 4,199 | 21% |
| North America | 3,101 | 16% |
| Africa and Middle East | 2,069 | 10% |
| South America | 1,620 | 8% |
| Oceania | 1,193 | 6% |

55% sits north of 25 degrees. The fetcher prints that figure itself rather than
leaving it to be discovered, because a single accuracy number over a set this
skewed says less than it appears to.

Training and eval are kept apart by construction. Seeds come from a global place
list rather than from the eval locations, and any seed within 25 km of an eval
image is dropped. Metadata is stripped on save, or the head could read the
answer off the file instead of the picture.

## The split is the most important line in train.py

Whole seed locations go to train or to validation, never both.

The fetcher drew several photographs from each 10 km box, so a random split
would put pictures taken metres apart on either side of it and report recall
dressed as accuracy. 3,838 locations, split by location: 15,933 images to train
and 4,067 to validate.

This makes every number below lower and worth reading.

## Results

| | |
|---|---|
| cell accuracy | **21.5%** |
| chance | 0.42% |
| median distance | 1,024 km |
| within 750 km | 44% |
| within 200 km | 29% |

Fifty times chance, and far worse than a frontier model call, which managed 94
km median on rural imagery of the same kind. DECISIONS.md predicted exactly this
before any of it was built: country-level accuracy respectable, anything finer
well short, and the gap is the writeup rather than a failure.

Cell count trades the two against each other, and neither end is good:

| cells | accuracy | median distance |
|---|---|---|
| 91 | 37.3% | 956 km |
| 236 | 21.5% | 1,024 km |
| 314 | 18.4% | 1,126 km |

## Calibration, which is the result worth having

| | before | after |
|---|---|---|
| expected calibration error | **10.7%** | **1.4%** |

One number, fitted on held-out data, and stated confidence then tracks observed
accuracy to within two points across the whole range below 0.6:

| stated confidence | n | stated | observed | gap |
|---|---|---|---|---|
| 0.1 to 0.2 | 1,667 | 14% | 15% | -1% |
| 0.2 to 0.3 | 689 | 24% | 25% | -1% |
| 0.3 to 0.4 | 366 | 35% | 36% | -2% |
| 0.4 to 0.5 | 175 | 44% | 44% | 0% |
| 0.5 to 0.6 | 87 | 54% | 56% | -2% |

The bands above 0.6 hold few enough examples that their gaps swing ten points
either way on a handful of images, and they are reported rather than smoothed.

## An assumption I had written down and got wrong

A comment in `ml/train.py` said a temperature above 1 means the model was
overconfident, the usual case. Every cell count came back near **0.70**, below
1, meaning the head was *under*confident and the scaling sharpens its
probabilities rather than softening them.

The code now reports which direction it found rather than asserting one. An
assumption in a comment is still an assumption.

## Why this matters to the rest of the project

Not as a locator. At 1,024 km it will not improve the agent's accuracy and the
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

1. **More data.** 20,000 images over 236 cells is 76 per class. PIGEON trained
   on millions. This is the binding constraint and everything else is second.
2. **Unfreezing the encoder**, which needs a real GPU and is the difference
   between this and the published work.
3. **Coverage.** Whole countries have no cell because Mapillary has no imagery
   there, and no amount of training fixes an absence of data.
