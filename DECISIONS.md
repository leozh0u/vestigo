# Decisions

Choices made, with the reasoning, so I do not relitigate them later. Also the
bugs worth remembering. Newest at the bottom within each date.

---

## 2026-08-11

### Name: Vestigo

Latin, first person: *I track, I trace, I search out*. From *vestigium*, a
footprint or a trace. It names the actual operation, following the traces in an
image back to the place they came from.

Started as Reckon, after dead reckoning, which had the right idea: working out
where you are from context you already hold. Changed for two reasons. Reckon
Limited is a listed Australian accounting software company with marks in the
same class, which is fine for a personal repo and not fine for anything
promoted. And every sensible domain was taken or parked for resale, whereas
vestigo.com was unregistered.

A coined or arbitrary term is also a stronger mark than a descriptive one. Any
name built from "loc" or "place" describes the category and is close to
impossible to defend; a Latin verb does not.

### Answer at the granularity the evidence supports

Most geolocation systems emit a point. This one emits the most specific claim it
can defend and stops there. Country at high confidence beats a confidently wrong
street address.

Consequence: the headline metric is calibration, not distance error. When the
system says "city level, high confidence," how often is it right? No existing
benchmark rewards that, which is exactly why it is worth measuring.

### Every claim carries its evidence

A `Claim` holds a level, a value, a confidence, and references to `Evidence`
records. Each `Evidence` points at a specific tool call or a cited rule: which
one, what input, what came back.

**A claim with no evidence does not count toward the answer.** Not "is
penalized." Does not count. Without that rule the failure mode is a vision model
asserting "London plane tree, therefore New York" with total confidence and no
basis, and the whole thing collapses into a chatbot that guesses.

### Baseline before any agent code

Session one produces a number, not a feature. Twenty photos with known
coordinates, GPS stripped, run past a frontier vision model with no tools.

If a plain API call is already good enough on most photos, I need to know that
before building, so the project can aim at the hard cases instead.

### Dataset: 10 IM2GPS + 10 Mapillary, reported separately

The obvious choice was IM2GPS alone, since it is the standard academic test set
and published numbers exist for it. Rejected as the sole source because of
contamination: those are public Flickr photos from around 2008, almost certainly
in the training data of every frontier model. A strong score there might be
recall rather than reasoning, and that is the one direction of error that would
mislead this project, since it would make the baseline look stronger than it is.
IM2GPS is also landmark-heavy, so it is mostly the easy half.

Mapillary is crowd-sourced street-level imagery, generic roadsides, almost
certainly not memorised. It matches the hard case the project is aimed at.

Ten of each, **always reported separately, never as a pooled median.** If the
model aces the Flickr half and flounders on the Mapillary half, that gap is
itself the finding.

Cost of the split: no directly comparable published number, and Mapillary needs
a free API token. Accepted.

Sample size: ten per half gives a rough median with wide error bars. This is a
go/no-go measurement, not a final grade — the real eval is ~100 images later.
Twenty is also the number where I can personally check every image and verify
every ground-truth coordinate by hand, which matters more here than n, because a
silent bug in EXIF stripping would invalidate every number downstream.

### Two arms: image only, and image plus real metadata

Arm A is the floor. Arm B adds only context that genuinely came with the photo:
capture date, local time, camera heading where present.

Rejected: writing realistic context myself ("a road trip through the Pacific
Northwest, summer 2019"). It is closer to the real use case, but I would be
choosing how helpful the context is, and that is the same knob that determines
the result. The measured delta would be partly a measurement of my own writing.

Arm B is not a detour. Date plus local time plus a shadow is the input the solar
geometry tool needs.

### PIGEON's weights are not public

Checked the repo directly. It states that geocell shapes and coordinates,
training and validation datasets, and model weights are all withheld, pointing
at the paper's ethical considerations section.

So: no benchmarking against PIGEON, no building on top of it. Compare against
their published numbers (44.4 km median on Street View, >40% within 25 km) and
use GeoCLIP as the specialised tier that can actually be run locally.

Worth noting for the guardrails section: the closest prior work looked at the
misuse question and chose not to ship the model. That makes the question
concrete rather than hypothetical.

### Train a geocell classifier rather than only calling APIs

Without this the project contains no machine learning at all — it is inference
on models other people trained. It is also the only route to the no-context
capability: generic street, name the country.

Following PIGEON's core idea in simplified form: geocells built from
administrative boundaries rather than a grid (visual features change at borders,
not at grid lines), classification over cells rather than regression to a point,
then a cluster-retrieval step to choose a point inside the predicted cell.

Simplification: PIGEON fine-tuned CLIP itself with synthetic geographic
captions, which needs real GPUs. I freeze the CLIP encoder and train only a
classifier head on cached embeddings, which runs on a laptop.

Expected consequence, stated up front: country-level accuracy should be
respectable and anything finer will be well short of 44 km. The gap is the
writeup, not a failure.

The classifier's softmax will be overconfident out of the box. Temperature
scaling fixes it, and the calibrated probability becomes the confidence on a
country-level claim. The ML work and the calibration thesis are the same idea
from two directions, which is why this phase is not a bolt-on.

### Text extraction is the highest-value tool, not solar geometry

Solar geometry is the appealing one: shadow angle plus a date gives a latitude
band from trigonometry, no model involved. It is still worth building first
because it is the one tool that either checks out or does not.

But it is a cross-check, not the workhorse. It returns a wide band, and the
band is usually something already known. Watching how these problems are
actually solved, most street-level answers come from reading text in the image
(a shop name, an area code, a route number) and searching it. That is OCR plus
search, and it is promoted to a first-class tool rather than being buried inside
"web search."

### Ship it free, do not charge per lookup

Shipping publicly is a goal in itself: proving it can be done, learning
deployment, giving something concrete to point at.

Charging per lookup does not work, for unglamorous reasons. API cost is roughly
10–30 cents a query, which leaves no margin at any price a casual user would
pay. A paid service also implies a guarantee and brings a payment processor's
acceptable-use policy into scope.

On misuse: the concern was overweighted at first. Someone determined to locate a
person uses social engineering or a data broker, not a public web demo that is
mediocre on generic streets. Guardrails kept because they are cheap and because
"did you think about misuse" deserves a real answer: no face recognition
anywhere in the pipeline, rate limits (which also cap the API bill), and a
README paragraph on intended use.

### Working documents stay out of the repo

Planning and progress notes stay local, excluded through `.git/info/exclude`
rather than `.gitignore` so the exclusion list itself is not part of the
repository. This file is the exception, because a decision log is a normal thing
for a repo to carry and it is the record of reasoning I want to be able to point
at later.

### Cost control moves ahead of the eval harness

Originally sequenced after it. Rebuilding the cost estimate bottom-up showed
why that is backwards: a full eval run over 100 images is 5 to 15 model calls
per image, and it gets rerun a dozen or more times while iterating, which makes
it the single largest expense in the project by a wide margin.

So prompt caching and model routing land *before* the first full eval run
rather than after. Caching the system prompt and tool definitions drops the
cached portion to roughly a tenth of list price, and routing the observation
extractor to a small model cuts the largest token consumer several times over,
since image tokens dominate.

Two more things follow from the same reasoning. Evals go through the batch
endpoint, which is half price and costs nothing in convenience because no user
is waiting on an eval. And the public demo serves precomputed evidence boards
for a gallery of example photos by default, with live upload behind a hard rate
limit, since most visitors want to see it work rather than submit their own
photo. That turns an open-ended bill into a fixed one.

### Deep multi-hop research, not just tool lookup

The interesting cases are not "call a tool, get a fact." They are chains: a
photo taken out of an aircraft window where the winglet shape narrows the
airframe, the seat fabric narrows the carrier, the terrain below narrows the
region, the sun angle gives heading and rough time, and the cloud deck gives an
altitude band. None of those is conclusive alone. Together they can reach a
specific flight.

Three consequences for the design.

**The agent needs a research sub-loop.** A tool call takes fixed inputs and
returns a fact. Multi-hop deduction generates each query from the previous
answer, so it needs its own loop with its own stopping condition, nested inside
the main one.

**Evidence needs strength and independence, not just presence.** The rule that a
claim either has evidence or does not is too crude here. Five weak signals that
independently narrow the space should compound; five that all derive from the
same observation should not. Without that distinction, correlated evidence
produces false confidence, which is the hallucination failure mode wearing a
disguise.

**Search quality is the bottleneck, not reasoning.** People who do this well
succeed by knowing which niche registry or regional forum holds the answer.
Generic web search returns noise and the agent flails. So the work is source
routing: airframes to spotter databases, species to GBIF, architecture to
specific archives. Curating that table is most of the value.

Error compounding is the risk that scales with depth. At 70% reliability per
hop, three hops is 34%. Every hop has to be verified before the next builds on
it, which is why the evidence discipline matters more the deeper the chain.

Cost: deep research is 30-60 model calls per image, roughly a dollar or two
rather than twenty cents. It cannot be the default path. It is what the system
escalates to when the cheap path returns low confidence, which is the model
routing doing real work rather than being a cost micro-optimisation.

### Prior art found: LocationAgent and GeoRC (both Jan 2026)

**LocationAgent** (arXiv 2601.19155) is a hierarchical agent for image
geolocation: coarse region first, then fine-grained. Architecturally close to
this project, with two differences that matter. It does not address calibration
or confidence at all. And its evidence comes from *parametric* knowledge, the
model's own internalised geography, which is close to the opposite of the rule
here that evidence must come from a tool result the model cannot fabricate.

**GeoRC** (arXiv 2601.21278) is a benchmark of 800 expert-written reasoning
chains over 500 GeoGuessr scenes, annotated across hundreds of discriminative
attributes: soil properties, architecture, licence plate shapes. Read it before
writing the Phase 3 rule base from scratch; much of that corpus may already
exist in usable form.

Their control condition is the important part, and it is being adopted here.
They compared real VLM reasoning against an LLM given the correct location, no
image at all, and asked to invent a justification. Small open models scored only
marginally better than that pure hallucination.

That is the empirical basis for this whole project: geolocation reasoning that
reads as expert is largely confabulation, so grounding claims in tool results is
addressing a measured failure rather than a hypothetical one.

**Consequence: the eval gains a third arm.** Alongside image-only and
image-plus-metadata, add a no-image hallucination control -- give the model the
right answer and ask it to justify. If the evidence-grounded chains do not beat
that, the tools are contributing nothing and I need to know.

Net position: not scooped. The direction is validated by other people
publishing on it, the open gap (calibration, evidence grounding) is the one this
project already targets, and a benchmark plus an annotated attribute corpus now
exist to compare against.

### Cheap models: local before multi-provider

Considered adding a second API provider for cost. Deferred, because the
compounding wins on one provider need no new integration: a small model for the
observation extractor is ~5x, prompt caching is ~10x on the cached prefix, and
the batch endpoint is another 2x on evals.

The stronger version is to run a small vision model locally for observation
extraction, which takes marginal cost to zero rather than merely lowering it.
That call is the highest-volume, most image-heavy and least reasoning-intensive
step in the pipeline, which is exactly the right job for a small local model.

Sequencing: one provider until the pipeline runs end to end, then swap the
cheap-path model and measure the quality delta. That delta is itself a result
worth reporting.

---

## 2026-08-19

### Phase 2 before Phase 1

The plan had solar geometry first, on the argument that one verified tool beats
six stubs. Phase 0 changed the order. The rural result and the Mexico case both
say the useful work is going from country to city on textless images, every
tool needs somewhere to attach its output, and the board as designed could not
express the one kind of evidence Phase 0 proved matters. Solar geometry now
becomes the first tool built against a contract that already exists, and it is
testable against eight rural images whose coordinates are known.

### Evidence is a fact, Support is a reading of it

The first sketch put `strength` on the evidence record. That is wrong, because
the same fact bears differently on different claims. A shadow measurement
supports Mexico and refutes Kenya at the same time, and one number on the
evidence cannot say both.

So evidence records what happened and carries no opinion: which tool, what
inputs, what came back. `Support` is the link from a claim to a piece of
evidence and holds the direction and the weight. The cost is one more type. The
gain is that the same evidence can be cited by several claims without the
readings interfering, which is what an evidence board has to do.

### One tool call is exactly one evidence record

Considered letting a tool emit several evidence records per call. Rejected as
untraceable: if a call produces four facts and one turns out to be wrong, there
is no way back to the inputs that produced it.

So a call becomes one record, and everything that call produced, constraints
and candidate locations, cites that record. Tracing anything back gives the
call, its inputs and its raw return. A tool wanting finer structure puts it
inside the `value` payload, which stays verbatim.

### Confidence is computed, never asserted

`Claim` has no confidence field. Ask the board and it works the number out from
the supporting evidence each time. What a model said about its own certainty is
kept in `stated_confidence` and does nothing.

That is Phase 0 read back. Stated medium confidence was bimodal from 0.1 km to
1545 km with nothing in the output separating the two cases, so a stated
confidence is data to calibrate against, not a number to act on.

The combination rule: within a group of correlated evidence take the strongest
and ignore the rest, across independent groups use noisy-OR. Correlation is
computed by walking `derived_from` back to root observations, so two readings
off the same signboard land in one group and count once. Without that, a model
restating one observation four ways looks like four confirmations.

### Constraints filter candidates, they do not vote

The type Phase 0 asked for. A constraint is a region the answer has to be in or
out of, with an `admits` score per point, and it never proposes a point of its
own.

Two properties fall out of that, and both are the Phase 0 failures inverted. A
constraint that admits a candidate leaves it exactly where it was, which is
what should have happened on the Thailand image where a correct band was turned
into a point six times worse than the model's own guess. And a constraint can
delete a candidate without improving any other one, which is what the capture
timestamp did on the Mexico image when it stopped the answer flipping to Kenya.

`weight` is separate from the admission score, and it is the certainty in the
constraint itself. At 1.0 an outside point is dead. At 0.8 it keeps 0.2. Solar
geometry read off a soft shadow edge should not be able to rule out the correct
country outright, so a tool measuring something uncertain does not get to claim
1.0.

Bands also take a soft margin so the score falls off linearly past the edge
rather than cutting. A band measured to within a few degrees should have edges
that are a few degrees wide.

### An unevaluated constraint abstains, never vetoes

`RegionSet` needs a coordinate-to-country resolver, which is code, so it cannot
survive the JSON cache. A constraint that cannot evaluate a point returns None
and the point passes untouched.

This is the one failure in the design that would be invisible. A vetoing
default would look like a working system that had quietly started ruling out
the truth, and it would show up as a slightly worse median that nobody could
explain. It has its own test.

### Tools cannot write claims

The contract has no route for it. Tools return evidence, constraints and
candidates. Only the board mints claims, and only citing evidence already on
it.

The dependency runs one way: the board knows nothing about tools, tools know
about the board. That is why `attach` is a function in `tools/base.py` rather
than a method on `Board`.

### Cache keyed on tool version, and failures are results

Tool results cache on disk under a key of name, version and inputs, so bumping
a tool's version invalidates its cache without anyone remembering to clear
anything. Only deterministic tools cache, and only successful calls.

A tool that raises returns a result with `ok=False` and still lands on the
board as evidence of a failed lookup. A failed Overpass query is a normal
outcome and the record should say so, rather than the run ending.

The reason to build this now rather than in Phase 4.5: the eval harness is the
largest cost in the project and it reruns over the same images a dozen times.
Retrofitting a cache around six tools that each grew their own signature is the
expensive version of this.

### Solar geometry runs forwards, not backwards

The plan said: measure a shadow, invert the equations, get a latitude band.
That is the harder half of the problem and it discards the azimuth, which is
the half that carries longitude.

A constraint is asked `admits(point)` one point at a time, so there is no need
to invert anything. Compute where the sun was at the candidate at that instant
and compare it to what the photograph shows. Forward is exact where inversion
is approximate, and there is no algebra to get wrong.

This only became available because the board was built first. With a band as
the output type, inversion is the only option. With a scoring function as the
output type, the forward equations are enough. Phase 2 before Phase 1 paid for
itself here.

### Daylight is the constraint worth having

Falls out of the same change. The strongest single solar constraint needs no
shadow measurement and no sun in frame. It needs only that the photograph was
taken in daylight, and fixing the instant then rules out the 49% of the earth
that is in the dark.

Measured on the eight rural images: the worst-case disagreement between two
runs on the same photograph falls from 14,964 km to 537 km, and the median
error does not move at all. That is the Phase 0 argument restated with a tool
in place. It also means the cheapest reading in the whole pipeline carries most
of the tool's value, so it gets weight 0.97 while the readings that need a
judgement get 0.75 and 0.70.

### The sun's bearing separates continents, not towns

Measured, not assumed. On the twenty-four real baseline guesses, a perfect
reading of the sun's direction changes nothing: same eliminations, same spread.
On a decoy set built from the other images' true coordinates it takes
elimination from 22% to 64%.

Both are the same fact. The sun's bearing barely moves over a few hundred
kilometres, which is where the real guesses already were, so it can only speak
at continent scale. Worth knowing before building the observation half, since
it means that half earns its cost on gross errors and not on precision.

### Constraint types live with their subject matter

`SolarElevation` and `SolarAzimuth` are in `vestigo/solar.py` next to the
algorithm they call, not in `board.py`. Keeping every constraint in the board
would have made it the place where all future domain knowledge accumulates.

The cost is that a type in a module nobody imports cannot be deserialized, so
`vestigo/__init__.py` has to import each one and `Constraint.from_dict` raises
with that explanation rather than a bare KeyError. `register_constraint` and
`soft_score` are public for the same reason.

### The azimuth constraint abstains at night

It could reasonably reject a point where the sun is below the horizon, since
there is no bearing to match. It does not, because the elevation constraint has
already ruled on exactly that. Scoring it twice would count one observation as
two, which is the same error the independence rule exists to prevent, just
appearing in the constraints rather than the evidence.
