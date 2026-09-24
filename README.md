# Vestigo

[![ci](https://github.com/leozh0u/vestigo/actions/workflows/ci.yml/badge.svg)](https://github.com/leozh0u/vestigo/actions/workflows/ci.yml)

Works out where a photograph was taken, at the most specific level the evidence
supports.

Most geolocation systems return a point no matter how little they have to go on.
This one returns the most specific claim it can defend and stops there. Country
at high confidence is a better answer than a confidently wrong street address,
so the metric that matters is calibration rather than distance error.

Every claim carries the tool result or the rule that produced it. A claim with
nothing behind it does not count toward the answer.

There is a site for it at **https://vestigo.earth**. It shows what the agent does; you cannot run it there yet.

## Status

The agent runs end to end, with a trained geocell classifier alongside it and
eight measured evaluation runs behind it.

It started as a measurement rather than a system. The point was to find out
whether a plain model call is already good enough before building anything on
top of it, and the types the board holds came out of what that baseline
measured.

```
vestigo/board.py         claims, evidence, and constraints that filter candidates
vestigo/observe.py       structured readings, and which of them are the same reading
vestigo/solar.py         solar position, and the constraints built on it
vestigo/metas.py         facts about countries a photograph can show, as constraints
vestigo/verify.py        checks every claim against what could disprove it
vestigo/consensus.py     one answer out of repeated samples
vestigo/scoring.py       granularity-aware correctness and calibration
vestigo/agent.py         the loop
vestigo/llm.py           one interface over every provider, with a budget
vestigo/tools/           solar, gazetteer, geocell classifier, metas, one contract for all
ml/                      the classifier: embedding, geocells, training
eval/                    the experiments, none of which need network access
```

## The baseline

Twenty photographs with known coordinates, all metadata stripped and verified
stripped, one model call each, no tools and no context. Ground truth is held in
a manifest the model never sees.

| set | n | median error | within 1 km | within 25 km |
|---|---|---|---|---|
| IM2GPS, 2004-2007 Flickr | 10 | 2.6 km | 40% | 60% |
| Mapillary, city centres | 10 | 0.6 km | 70% | 80% |
| Mapillary, rural roads | 8 | 94.2 km | 0% | 12% |

The last two rows are the same source, the same pipeline and the same model.
Only the sampling differs, and the median moves by a factor of 130.

Sampling city centres was my mistake on the first pass. A 440 m box centred on a
famous square puts ground truth next to a landmark the model can name on sight,
so answering "central Madrid" scores under a kilometre by construction. Those
images came out as tourist districts full of legible shopfronts, which is the
opposite of what the set was for. It is kept rather than deleted because the
comparison against the rural set measures exactly how much the model leans on
text and landmarks.

On the rural half the model named the correct country eight times out of eight,
and landed within 25 km once. Country knowledge holds up; precision collapses.
That gap is the problem worth working on.

The calibration breakdown is the part worth reading:

| stated confidence | n | median | worst case |
|---|---|---|---|
| high | 10 | 0.4 km | 30 km |
| medium | 7 | 0.7 km | 1545 km |
| low | 3 | 285.6 km | 293 km |

High confidence is reliable across ten calls. Low confidence is honestly bad.
Medium is not a wide band, it is bimodal: four answers under a kilometre, then
95 km, 502 km and 1545 km, with nothing in the output separating the two cases.
Making "medium" mean something is a concrete target.

One result argues for the whole design. Given a night street in India with no
legible signage, the model answered at country granularity, said so, and
explained it was hedging rather than making a city claim. India was correct.
Distance scoring calls that a 502 km failure.

Full writeup in [results/baseline.md](results/baseline.md).

## The agent

Five steps: read the photograph, make an unaided guess, call tools, propose
claims, resolve. The second step is the one that looks wrong and is not. A bare
model call is already good, so the unaided guess is kept as a candidate and the
tools filter it rather than replacing it.

Nothing reaches the answer except through the board. A claim must cite evidence
that is already on it, a claim citing an id that does not exist has that
citation stripped and the rejection reported, and tools have no route to write a
claim at all.

Seven measured runs over 28 photographs, three samples each:

| run | what was added | correct at level | overclaimed |
|---|---|---|---|
| v1 | first working agent | 71% | 29% |
| **v2** | **evidence carries its own reach** | **84%** | **16%** |
| v5 | constraints able to act at all | 83% | 17% |
| v6 | geocell classifier | 84% | 16% |
| v7 | solar accepts a local clock | 83% | 17% |

A bare model call scores 89% and 11% on the same images, which is the reference
every row above is measured against.

**The change that mattered was about who grades evidence.** In v1 whoever wrote
a citation also wrote the number on it, so the model could put 0.9 on "dry
scrub" and push a point claim through a threshold. Evidence now carries the
finest level it could justify and the most any citation of it may be worth.
Overclaiming fell from 29% to 16% with the median error unmoved: the same
answers, stated at levels they can carry.

The rounds after that isolated something worth knowing. The agent's first pass
is itself a frontier model call, so a tool only moves the result if it supplies
something the model does not already hold. Solar geometry is physics it knows,
the classifier is a second opinion, and the observation extractor is the same
model looking again.

Full writeup, including the three bugs found on the way, in
[results/agent.md](results/agent.md).

The eighth run tested that with the first tool that does query the outside
world, a place-name lookup against OpenStreetMap. Of the nineteen images both
runs answered, eighteen came back at a distance identical to three decimal
places. That is not noise. It means no tool could have moved the answer: the
ranking seeds the model's own guess at a prior no evidence can overcome, so
outside evidence can cap how precisely an answer is stated but never change
where it is. The cap did work, and ten answers claimed a city, a district or a
point, where no earlier run had ever claimed anything finer than a region.
Writeup in [results/gazetteer.md](results/gazetteer.md).

## The first tool

Solar geometry. Given the instant a photograph was taken and the fact that it
was taken in daylight, it rules out everywhere the sun was below the horizon,
which at any moment is 49% of the earth. No shadow measurement, no sun in the
frame, no model in the loop. The plan had this working backwards, inverting the
equations to get a latitude band; running them forwards against one candidate
at a time is exact and needs no algebra.

It is a filter and not an estimator. It proposes no location and there is no
route in the tool contract for it to try.

The baseline left twenty-four guesses across the eight rural images, so those
became the candidates and the manifest timestamps became the constraint:

| | before | after |
|---|---|---|
| candidates ruled out | | 1 of 24 |
| best candidate cut by mistake | | 0 of 8 images |
| median error over the set | 114 km | 114 km |
| worst-case disagreement between runs | 14,964 km | 537 km |

The median does not move and the worst case falls by a factor of 28. One image
was answered as Mexico on one run and Kenya on an identical rerun, 14,970 km
apart. At the capture instant the sun was 47 degrees up over Querétaro and 79
degrees below the horizon over Nairobi, so the Kenya answer cannot be right and
the tool removes it without touching the other one.

That is the tool doing the only thing this class of evidence can do. It does
not find the town. It stops the answer being on the wrong continent.

Full writeup in [results/solar.md](results/solar.md), including where it is
weak: two of the eight images sit within four degrees of the horizon, where the
daylight reading everything rests on is close to a coin flip.

## Scoring it on what it claimed

Distance error cannot see the thing this project is for. Given a night street in
India with no legible signage, the model answered at country granularity, said
so, and India was correct. Distance calls that a 502 km failure.

So a claim now counts as correct if the truth falls inside the radius its level
implies, using the standard IM2GPS bands rather than new numbers. On the same 28
images that produced the table above:

| source | n | correct at the level claimed | overclaimed | underclaimed |
|---|---|---|---|---|
| IM2GPS | 10 | 90% | 10% | 70% |
| Mapillary, city centres | 10 | 90% | 10% | 80% |
| Mapillary, rural roads | 8 | 88% | 12% | 62% |

The rural row is the one that moves. By distance it is a 94 km median and reads
as the half where the system fails. By what it claimed, 88% of those answers
were right, and the gap to the other two rows is four points rather than a
factor of 130. Both numbers are true; they answer different questions.

Ten answers are correct under one metric and failures under the other. None go
the other way, so the model was not sneaking precision past a loose metric.

Two things fall out that distance had hidden.

**It underclaims seven times as often as it overclaims**, 71% against 11%. On
most images it stops at a coarser level than its own accuracy would support,
claiming a country and landing 2.6 km away. Overclaiming is the failure worth
driving to zero and it is already low. Underclaiming is not a failure, but that
much specificity given up is its own problem, and a different one from being
inaccurate.

**Stated confidence is underconfident rather than overconfident.** High
confidence is exactly calibrated: promised 90%, delivered 90%. Low confidence
answers were correct at the level they claimed every time, because the model
correctly coarsens its claim when it is unsure. Under distance scoring that
looked like the honestly bad band. It is a coarse claim being kept.

Phase 0's finding that medium confidence is bimodal survives and sharpens. Its
worst answer landed 62 times further out than the level it claimed allows, where
low confidence never broke its claim at all.

Full writeup in [results/calibration.md](results/calibration.md).

## What comes next

The gazetteer run changed the order. Another tool that proposes a place would
measure flat for the same reason the last ones did, so the work now is on what
is allowed to overrule the first guess.

1. **Constraints that eliminate places.** Which side of the road people drive
   on, what script the signs use, what colour the centre line is. These are
   facts about countries rather than about Street View, and they rule places
   out instead of proposing new ones. Built in `vestigo/metas.py`, not yet
   written up.
2. **Aggregating repeated samples.** Run-to-run noise is a 40 km median with a
   14,951 km tail. `vestigo/consensus.py` makes one answer out of the samples
   the eval already pays for. Built, not yet written up.
3. **Verification.** Every claim checked against what could disprove it, in
   `vestigo/verify.py`. Built, not yet written up.
4. **The ranking itself.** The 1.0 seed was a fix for a real failure: ranking
   on tool candidates once refused three answers that were right to within a
   kilometre. Replacing it is a trade the project has now measured both sides
   of, so it gets decided carefully rather than patched.

On the classifier side, the next gains are more data and unfreezing the
encoder, which needs a real GPU.

## What this is aimed at

On photographs with readable text or a recognisable landmark, a frontier model
with no tools is already excellent and tools will add very little. Only five of
the twenty images produced errors above 30 km: a hostel dormitory, a bare beach,
an English field, a night street with no signage, and a plaza whose Latin-script
Turkish text was read as Lithuanian.

No text, no landmark, no distinctive infrastructure. That is a narrower target
than I expected going in, and it is where the work belongs.

## Reproducing

```
python3 -m venv .venv && ./.venv/bin/pip install pillow pytest
./.venv/bin/python scripts/ingest_im2gps.py
./.venv/bin/python scripts/ingest_mapillary.py    # needs a Mapillary token in .env
./.venv/bin/python eval/score.py eval/arm_a.json
./.venv/bin/python eval/solar_check.py    # needs no images and no network
./.venv/bin/python eval/calibrate.py      # same
./.venv/bin/python eval/harness.py --dry  # the whole agent, no key, no spend
./.venv/bin/pytest
```

The ML half needs torch and about 8 GB of imagery for the full set:

```
./.venv/bin/python scripts/fetch_training.py --target 200000 --per-place 150 --spread-km 180
./.venv/bin/python ml/embed.py --model ViT-SO400M-14-SigLIP --pretrained webli
./.venv/bin/python ml/train.py --embeddings vit-so400m-14-siglip__webli
```

Without the flags, `ml/embed.py` uses ViT-B/32, which runs on a laptop in
minutes and is the first row of the encoder table below.

The package itself has no dependencies. Pillow is for the ingest scripts and
pytest is for the tests.

Images are not committed. The manifest holds the coordinates, so the fetch is
reproducible without redistributing anyone's pixels.

## Data

IM2GPS test set, from the Carnegie Mellon project page. Ground truth for those
images lives in the JPEG comment markers rather than EXIF.

Street-level imagery from Mapillary, licensed CC-BY-SA.

## Intended use

For placing photographs you have a reason to place: undated family pictures,
archive material, your own travel photos.

There is no face recognition anywhere in the pipeline and there will not be. The
hosted version is rate limited. Please do not use this to locate people.

## The classifier

The only model here that I trained. About 65,000 Mapillary images, a frozen
image encoder, and one linear head over 250 geocells clustered from the training
points rather than laid out on a grid, because what a photograph shows changes
at borders and not at round numbers.

The first version used 20,000 images and landed at a 1,024 km median. Tripling
the data took that to 527 km. Swapping the frozen encoder did more than the
data had:

| encoder | cell accuracy | median | within 200 km | calibration error |
|---|---|---|---|---|
| CLIP ViT-B/32 | 31.9% | 527 km | 37% | 2.6% |
| CLIP ViT-L/14 | 44.8% | 198 km | 50% | 3.5% |
| **SigLIP SO400M** | **51.6%** | **142 km** | **58%** | **3.7%** |

Chance is 0.4%. For scale, a frontier model call managed 94 km on the rural
half of the eval, so a linear layer trained on a laptop in ninety seconds is
now within about 1.5 times of it rather than 5.6.

The calibration is the part worth having. After temperature scaling the error
stays under 4% at every encoder, so a more accurate model did not come at the
cost of an honest one. On the encoder with the full breakdown written up, every
band above the lowest is slightly underconfident, which is the safe direction to
be wrong in. That makes it the only evidence source in
the project whose strength is measured rather than written by the model citing
it.

The split holds out whole seed locations rather than random images, because
several photographs were drawn from each 10 km box and a random split would
report recall dressed as accuracy.

Full writeup in [results/classifier.md](results/classifier.md).

## Cost

The eval is the expensive part, because its whole point is running the same
images repeatedly. Three things keep that affordable, and all three are in the
code rather than in a plan.

Responses cache on disk keyed partly on a sample index, so three samples of an
image cost three calls the first time and nothing on any rerun while still
carrying three distinct answers. Repeat sampling is not optional here: run-to-run
noise on this data is a 40 km median with a 14,951 km tail, so one sample cannot
tell an improvement from a reroll.

Each job goes to its own model. Reading a photograph is high volume and barely
reasons; deciding which clue to chase next runs a handful of times per image.
Sending both to the same model is the most expensive mistake available.

The budget refuses rather than warns, checking before the call and recording the
real figure after. A model with no price on file reports its cost as unknown and
is refused unless explicitly allowed, because a budget that reads unpriced as
free looks fine until the invoice arrives.

No part of the codebase names a vendor above `llm.py`, so running the same eval
against a second provider is a config line. That matters beyond cost: calibration
is a property of the model rather than of this code, so comparing two of them is
a result rather than an expense.

## Decisions

[DECISIONS.md](DECISIONS.md) records why things are the way they are, including
the choices that turned out to be wrong.
