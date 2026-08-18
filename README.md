# Vestigo

Works out where a photograph was taken, at the most specific level the evidence
actually supports.

Most geolocation systems return a point no matter how little they have to go on.
This one returns the most specific claim it can defend and stops there. Country
at high confidence is a better answer than a confidently wrong street address,
so the metric that matters is calibration rather than distance error.

Every claim carries the tool result or the rule that produced it. A claim with
nothing behind it does not count toward the answer.

## Status

Early. There is no agent yet. What exists is the measurement that defines the
problem, which is deliberate: the point of starting here was to find out whether
a plain model call is already good enough before building anything on top of it.

## The baseline

Twenty photographs with known coordinates, all metadata stripped and verified
stripped, one model call each, no tools and no context. Ground truth is held in
a manifest the model never sees.

| set | n | median error | within 1 km | within 25 km |
|---|---|---|---|---|
| IM2GPS, 2004-2007 Flickr | 10 | 2.6 km | 40% | 60% |
| Mapillary, city centres | 10 | 0.6 km | 70% | 80% |
| Mapillary, rural roads | 8 | 92.5 km | 0% | 12% |

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
python3 -m venv .venv && ./.venv/bin/pip install pillow
./.venv/bin/python scripts/ingest_im2gps.py
./.venv/bin/python scripts/ingest_mapillary.py    # needs a Mapillary token in .env
./.venv/bin/python eval/score.py eval/arm_a.json
```

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

## Decisions

[DECISIONS.md](DECISIONS.md) records why things are the way they are, including
the choices that turned out to be wrong.
