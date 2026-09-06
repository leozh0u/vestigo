# Vestigo

[![ci](https://github.com/leozh0u/vestigo/actions/workflows/ci.yml/badge.svg)](https://github.com/leozh0u/vestigo/actions/workflows/ci.yml)

Works out where a photograph was taken, at the most specific level the evidence
actually supports.

Most geolocation systems return a point no matter how little they have to go on.
This one returns the most specific claim it can defend and stops there. Country
at high confidence is a better answer than a confidently wrong street address,
so the metric that matters is calibration rather than distance error.

Every claim carries the tool result or the rule that produced it. A claim with
nothing behind it does not count toward the answer.

There is a site for it at **https://vestigo.earth**. It shows what the agent does; you cannot run it there yet.

## Status

The agent runs end to end, with a trained geocell classifier alongside it and
seven measured evaluation runs behind it.

What exists is the measurement that defines the problem, which is deliberate:
the point of starting there was to find out whether a plain model call is
already good enough before building anything on top of it. On top of that sits
`vestigo/`, the evidence board and the contract every tool is written against,
the first tool, and the scoring that judges a claim on what it claimed. The
types the board holds came out of what the baseline measured, so the order is
the argument.

```
vestigo/board.py         claims, evidence, and constraints that filter candidates
vestigo/observe.py       structured readings, and which of them are the same reading
vestigo/solar.py         solar position, and the constraints built on it
vestigo/scoring.py       granularity-aware correctness and calibration
vestigo/agent.py         the loop
vestigo/llm.py           one interface over every provider, with a budget
vestigo/tools/base.py    one contract for every tool
eval/                    the experiments, none of which need network access
```

The loop is observe, guess, use tools, claim, resolve. The second step is the
one that looks wrong and is not: a bare model call is already good, so the
unaided guess is kept as a candidate and the tools filter it rather than
replace it. Nothing can reach the answer except through the board, and a claim
citing evidence that does not exist is rejected and the rejection is reported.

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
model looking again. Tools that query the outside world are the open direction,
and the plan for them is below.

Full writeup, including the three bugs found on the way, in
[results/agent.md](results/agent.md).

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

The measured result points at one thing: a tool only moves the answer if it
returns something the model does not already contain. Three directions, in
order:

1. **Tools that query the outside world.** Search on text read from the image,
   Overpass queries against OpenStreetMap for spatial co-occurrence, reverse
   image search. These return facts the model does not contain. My own decision
   log says text extraction was the highest-value tool and I built the solar
   solver first anyway.
2. **Aggregating repeated samples.** Run-to-run noise is a 40 km median with a
   14,951 km tail, and the system currently takes one answer per run.
3. **Verification.** Hand a guess to a second call that tries to refute it.

On the classifier side, the cheapest gain is a haversine-smoothed loss. Plain
cross-entropy scores a neighbouring cell exactly as wrong as the opposite
hemisphere, which for a geographic task throws away most of the signal.

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

The ML half needs torch and about 3 GB of imagery:

```
./.venv/bin/python scripts/fetch_training.py --target 20000 --per-place 150 --spread-km 180
./.venv/bin/python ml/embed.py
./.venv/bin/python ml/train.py
```

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

The only model here that I trained. 20,000 Mapillary images, a frozen CLIP
encoder, one linear head over 236 geocells clustered from the training points
rather than laid out on a grid, because what a photograph shows changes at
borders and not at round numbers.

| | |
|---|---|
| cell accuracy | 21.5% against 0.42% chance |
| median distance | 1,024 km |
| **calibration error** | **10.7% to 1.4%** |

Fifty times chance, and coarse by design at this data size, which is what I
wrote down it would be before building it. The calibration is the part worth
having: after temperature scaling, stated confidence tracks observed accuracy to
within two points across the whole range below 0.6.

That makes it the only evidence source in the project whose strength is
measured rather than written by the model citing it. On one image it is wrong,
placing a Mexican road in Central Asia, and reports 7%. Wrong answer, honestly
signalled, and nothing can lean on it further than that.

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
