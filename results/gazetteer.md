# The gazetteer run, and the structural fault it exposed

Eighth run. The first tool in this project that supplies information a frontier
model does not hold, measured against the seventh run over the same images with
the same preset.

    ./.venv/bin/python eval/harness.py --preset cheap --samples 3 --limit 4.00

$2.72, 54 scored runs. It bought a diagnosis rather than an improvement, which
was the better outcome available.

## The pooled number is a mirage, so ignore it

Pooled over everything, median error fell from 53.9 km to 27.6 km. That number
is worthless and is written here only so nobody quotes it.

The two runs did not cover the same images. Run seven answered 26 distinct
images; run eight answered 20, sharing 19. Six of the seven it dropped were
rural, which is the hardest source, so the pooled median improved mostly
because the hard images left the pool.

## Paired on the 19 images both runs answered

| source | n | run 7 | run 8 |
|---|---|---|---|
| im2gps | 9 | 25.7 km | 25.7 km |
| mapillary_urban | 6 | 6.0 km | 7.1 km |
| mapillary_rural | 4 | 199.6 km | 198.2 km |

One image improved, none got worse, **eighteen of nineteen returned a distance
identical to three decimal places**. Not similar. Identical.

That is not a null result. A null result looks like scatter around zero.
Identical distances mean the tool could not move the answer even in principle,
and finding out why is worth more than the run cost.

## Why: the ranking is seeded so the model's own guess cannot lose

`Board.rank_candidates` scores every candidate as `prior x admissibility`,
where admissibility is how well a point survives the constraints.

The first-pass candidate, the model's unaided guess, is added with **prior
1.0**. Its alternatives get 0.4. A gazetteer match gets its share of the
matched names' prominence, which for anything ambiguous is 0.1 to 0.5 and is
split across several candidates besides.

So a tool candidate can only win if a constraint pushes the first-pass
candidate down. Constraints are the only mechanism that can do that, and they
are largely inert on this data: solar geometry fires on about half the runs and
abstains on most points, so admissibility comes out at 1.0 for nearly
everything.

A candidate at 1.0 x 1.0 beats a candidate at 0.45 x 1.0 every time. **The
scaffolding is built so that external evidence can cap how precisely an answer
is stated, but never change where the answer is.**

That one sentence explains five runs of "tools fire and nothing moves" better
than anything written about it before, including the explanation in
`results/agent.md`, which blamed tool coverage. Tool coverage was never the
problem. Four of the five earlier runs would have measured flat with perfect
tools.

## What did change, and it is not nothing

Granularity travels a different path from ranking. `resolves_to` caps how fine
a claim may be, so it works even when the point does not move.

| level claimed | run 7 | run 8 |
|---|---|---|
| continent | 9 | 7 |
| country | 25 | 23 |
| region | 33 | 14 |
| city | 0 | 4 |
| district | 0 | 3 |
| point | 0 | 3 |

Before the gazetteer, **no run in this project's history ever claimed anything
finer than a region**, because no evidence source could justify it. Ten runs
now do. That is the granularity ladder working end to end for the first time,
and it is the half of the design the project is named for.

Expected calibration error came in at 16%, against 28% overclaiming in the
run that first measured it.

## The agent also abstains more

Thirteen more runs made no claim at all. That follows from the design: a common
name returns matches spread over a continent, which lowers computed confidence,
and a claim that misses its threshold is not stated.

Whether that is the system being honest or the system being useless is a real
question and this run cannot answer it, because the abstentions were
concentrated on rural images that run seven answered badly anyway. Worth a
targeted look rather than a guess.

## A failure the tool cannot fix by itself

On one image the model looked up "Chicago-Kent College of Law", got a unique
point-level match, and that building is almost certainly not in the photograph.
The tool answered the question it was asked. It cannot know the question was
about something the model invented.

The 0.9 ceiling exists for this and is not enough on its own. What is missing
is a check in the other direction: not "does this name exist" but "does what
this photograph shows agree with what is at that coordinate".

## What this says to do next

Not "add more tools". The next tool would measure flat for the same reason the
last four did.

The fix is in `rank_candidates`: the first pass should not be seeded at a prior
no evidence can overcome. What replaces it is a design decision worth making
carefully, because the 1.0 seed was itself a fix for a real failure, recorded
in `Board.locate` — ranking on tool candidates once scored a claim about Paris
against an alternative in Berlin and refused three answers that were right to
within a kilometre.

So this is not a bug to patch. It is a trade the project has now measured both
sides of.
