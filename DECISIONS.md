# Decisions

Choices made, with the reasoning, so I do not relitigate them later. Also the
bugs worth remembering. Newest at the bottom within each date.

---

## 2026-08-11

### Name: Reckon

From dead reckoning, working out where you are from context you already hold: a
known starting point, a heading, elapsed time. That is the thing that separates
this from a pure image classifier, since the context (a date, an itinerary, a
half-remembered story) is an input rather than a nuisance.

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

`CLAUDE.md`, `PLAN.md`, and `PROGRESS.md` are gitignored. This file is not,
because a decision log is a normal thing for a repo to carry and it is the
record of reasoning I want to be able to point at later.

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
