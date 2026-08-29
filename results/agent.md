# The agent, measured four times

Phase 4. The first version of the whole pipeline running against real
photographs, and three rounds of fixing what the measurements exposed.

Reproduce with `./.venv/bin/python eval/harness.py --preset cheap --samples 3`.
Total spend across every run reported here: **$8.19**.

## The loop

Five steps, and the order comes from what Phase 0 measured rather than from
what an agent usually looks like.

1. **observe.** A cheap model lists what is visible, each with a box in the
   frame so two readings of one signboard can be recognised as one signboard.
2. **first pass.** The reasoning model makes its own unaided guess, plus up to
   three alternatives. The guess is kept as a candidate, not as an answer.
3. **tools.** The model calls tools until it stops asking. Tools add evidence
   and constraints and candidates. None of them can write a claim.
4. **claims.** The model proposes claims, each citing evidence by id. Anything
   citing an id that does not exist has the citation stripped and the rejection
   reported.
5. **resolve.** The board answers at the finest level that clears its
   threshold. No model involved.

Step 2 is the one that looks wrong. A bare model call is already good, 2.6 km
median on landmarks, so an agent that discards its own first pass starts behind
its own baseline. The tools filter that guess rather than replacing it.

## The four runs

Twenty images appear in all four, so this is the like-for-like comparison.

| run | what changed | correct at level | overclaimed | median |
|---|---|---|---|---|
| v1 | first working agent | 71% | 29% | 9.2 km |
| **v2** | **evidence carries its own reach** | **84%** | **16%** | **9.2 km** |
| v3 | constraints able to act | 79% | 21% | 26.4 km |
| v5 | contradiction rule | 79% | 21% | 26.0 km |

Baseline, for comparison: a bare model call with no tools scored 89% correct at
the level it claimed and overclaimed 11%.

**The agent has not beaten the bare model call.** That is the headline and it
should stay the headline until it stops being true.

## v1 to v2 is the one clean result

Identical model outputs, replayed from cache, with only the board's rules
changed. Nothing else in this document is as well controlled.

v1 let whoever wrote a citation also write the number on it, so the model could
put 0.9 on "dry scrub" and push a point claim past a threshold. Citing evidence
was enforced. Grading it was not, and the grader had an interest in the answer.

In v2 each evidence record carries the finest level it could ever justify and
the most any one citation of it may be worth. Text reaches a district, since
Phase 0 measured that nearly every street-level answer came from reading
something. Road and architecture reach a region. Vegetation, terrain and sky
stop at a country. An observation's certainty becomes its strength ceiling.

The level distribution is the mechanism in one line:

| level claimed | v1 | v2 |
|---|---|---|
| point | 9 | 0 |
| district | 11 | 0 |
| city | 10 | 0 |
| region | 10 | 33 |
| country | 9 | 17 |
| continent | 9 | 8 |

Overclaiming fell from 29% to 16% and the median error did not move at all,
which is the point: the same answers, stated at levels they could carry.

## The constraint layer works and has not paid for itself

Three separate bugs had to be fixed before a constraint could affect anything
at all. Each was found from data already on disk, at no cost.

**Constraints were structurally inert.** Candidate scores are normalised across
the set, and the agent only ever produced one candidate, so a single candidate
took all the weight however badly it fit. A Mexican photograph came back as
Namibia, 13,599 km out, on an image where the sun was 47 degrees above the
horizon over the truth and 69 below it over the answer. The solar constraint
had scored that answer at 0.03 and it changed nothing. Fixed by having the
first pass offer alternatives, so there is something to eliminate in favour of.

**Constraints abstained on the claims that mattered.** They need a coordinate,
and a model asked to name a country names a country. A claim is now tested at
the guess it was reasoned from.

**A constraint that rejects everything is not evidence about location.** A
Buenos Aires street timestamped 22:53 local, which is night, with the extractor
reporting daylight. Both cannot hold. The solar constraint was right that they
conflict and wrong to conclude anything about where, so it scored the correct
answer and three alternatives at 0.03 alike and the board refused an answer it
had otherwise reached to within a kilometre. Such a constraint is now set aside
and recorded as contradicted. It takes two candidates to call it: with one,
"rejects everything" and "rejects the only guess" are the same sentence, and
the second is the job.

After all three, the Mexico image declines instead of answering Namibia, which
is exactly what it should do. The aggregate is unchanged at 79% and 21%, worse
than v2's 84% and 16%.

So the constraint machinery now does what it was designed to do, case by case
and demonstrably, and the configuration without it still scores better. That is
the result, not a stage on the way to a better one.

Worth stating plainly: v3 is not as well controlled as v2. Adding alternatives
to the schema changed the first-pass replies and therefore every downstream
prompt, so the model outputs differ as well as the rules. The v1 to v2
comparison has no such confound and the v2 to v3 one does.

## By source

v5, all 28 images, three samples each.

| source | n | correct at level | median |
|---|---|---|---|
| IM2GPS | 30 | 83% | 26.0 km |
| Mapillary, city centres | 26 | 73% | 1.8 km |
| Mapillary, rural roads | 21 | 86% | 148.9 km |

The rural row is the project. 86% of its claims were correct at the level
claimed, and the median error is 149 km, which together say the system reliably
knows the country and cannot find the town. That is the same gap Phase 0
measured before any of this was built, and nothing here has closed it.

Closing it needs tools that read the image and look things up, or a classifier
trained on imagery. Solar geometry cannot do it, and this run is the evidence:
it stops catastrophic answers and does not improve ordinary ones.

## Cost

| | |
|---|---|
| per run, no cache | $0.048 |
| per run, cached | $0.000 |
| reasoning share of spend | 86% |
| total across four runs | $8.19 |

The cache is what makes iteration affordable, and it has one rule: changing
anything early invalidates everything after it. The v3 run cost $4.07 because
one added schema field changed the first-pass reply and cascaded through every
later prompt. Board-logic changes replay free. Prompt changes do not.

## What this says to do next

1. **Stop tuning the agent.** Three rounds, each a dollar or four, and the last
   two moved nothing.
2. **The rural gap is the project** and it needs new capability rather than
   better rules: reading text and looking it up, or a geocell classifier
   trained on imagery.
3. **Keep v2's rules.** The reach ceilings are the only change that measurably
   helped. The constraint layer stays because the cases it fixes are real and
   because the next tools will feed it, but it is not currently earning its
   place and the writeup should keep saying so until it does.
