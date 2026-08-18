# Baseline: frontier vision model, no tools, no context

Arm A of the Phase 0 baseline. Twenty photographs with known coordinates, all
metadata stripped and verified stripped, one model call per image, no tools and
no web access. Ground truth held back in `data/manifest.json`, which the model
never saw.

This is the number the rest of the project has to beat.

## Results

| set | n | median error | within 1 km | within 25 km | within 200 km |
|---|---|---|---|---|---|
| IM2GPS | 10 | 2.6 km | 40% | 60% | 80% |
| Mapillary | 10 | 0.6 km | 70% | 80% | 80% |
| pooled | 20 | 0.7 km | 55% | 70% | 80% |

For scale, PIGEON reports a 44.4 km median on Street View. A model with no
tools, no training and no context beat that here by more than an order of
magnitude. The caveats below matter more than the number does.

## Calibration, which is the interesting part

| stated confidence | n | median | worst case |
|---|---|---|---|
| high | 10 | 0.4 km | 30 km |
| medium | 7 | 0.7 km | **1545 km** |
| low | 3 | 285.6 km | 293 km |

The medians hide the finding. Broken out fully:

- **High confidence is trustworthy.** Ten calls, worst case 30 km, median 400 m.
  It is not once badly wrong.
- **Low confidence is honest.** Two of three are hundreds of km out, which is
  what "low" should mean.
- **Medium confidence is where it lies.** Four answers under a kilometre, then
  95 km, 502 km, and 1545 km. Not a band with a wide spread, a band that is
  bimodal: usually excellent, occasionally catastrophic, with nothing in the
  output distinguishing the two.

That is the single most useful result here. A downstream system can trust "high"
and discount "low". "Medium" is unusable as stated, and making it mean something
is a concrete thing this project can improve.

## Distance error punishes appropriate humility

The Bengaluru image is the clearest case. The model answered at **country**
granularity and said so, explaining that with no legible text or landmark it was
hedging rather than making a city claim. India was correct. Scored by distance
it is a 502 km failure; scored by whether the claim it actually made was right,
it is a success.

This is the argument for granularity-aware scoring over raw distance, and it
showed up unprompted on the first run.

## Two reasons the Mapillary half overstates performance

**The sampling box is too small.** Images were drawn from a 0.004 degree box,
about 440 m, centred on well-known city centres. Ground truth therefore sits
within roughly 600 m of a landmark the model can name on sight, so answering
"central Madrid" scores under a kilometre by construction. That is the box, not
the model.

**It is not the hard half it was meant to be.** The design called for generic
roadside imagery. City-centre sampling produced tourist districts with legible
shopfronts, and the model read them: a wine retailer's Cape Town dialling code,
a Seoul visitor centre's name, a Rome ticket kiosk. Text extraction dominated,
which was predicted, but on images that were supposed to contain none.

One IM2GPS result is also an artifact: the Buenos Aires photo scored exactly
0.0 km because the Flickr geotag is the city centroid and the model guessed the
city centroid. Two lookups agreeing, not skill.

## What actually failed

Only four images produced errors above 30 km, and they are the ones that look
like the real target: a hostel dormitory interior (286 km), a beach with no
built structures (293 km), an English field (95 km), a night street in India
with no legible signage (502 km), and an exhibition plaza whose Latin-script
text was misread as Lithuanian rather than Turkish (1545 km).

No readable text, no landmark, no distinctive infrastructure. That is the
target, and it is a much narrower target than the plan assumed.

## Consequences

1. The Mapillary half needs rebuilding: rural and suburban road segments, a much
   wider sampling area so naming the nearest city does not automatically score.
2. Scoring needs a granularity-aware metric alongside distance, because distance
   alone penalises the model for correctly declining to over-claim.
3. The project's target case is narrower than assumed. On landmark or
   text-bearing photographs the baseline is already excellent and tools will add
   little. The work is in the textless, landmarkless minority.
4. "Medium" confidence being bimodal is a concrete, measurable thing to improve,
   and it is the calibration thesis restated as an engineering task.
