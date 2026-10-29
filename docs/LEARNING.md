# Learning Vestigo

Read this alongside the code. For each checkpoint, predict the behaviour before
running it, then explain the result without reading the implementation aloud.

## Start with one investigation

```sh
python3 -m vestigo.demo
python3 -m vestigo.demo --scripted
```

A recorded investigation shows what a previous model-assisted run produced.
The deterministic board exercise shows what the current code accepts and
rejects. Neither performs new image inference. The website animates stored
trace files, so its playback time is not model latency.

## Read the system in this order

| File | Responsibility | Explain-back checkpoint |
| --- | --- | --- |
| `vestigo/agent.py` | Observe, first guess, tools, claims, resolve. | Trace one input through the five steps and explain why the first guess survives. |
| `vestigo/board.py` | Evidence, candidates, claims, constraints and resolution. | Explain why a country-level clue cannot establish a street address. |
| `vestigo/tools/base.py` | Tool inputs, results, attachment and caching. | Show how one tool call becomes evidence with a stable source. |
| `vestigo/observe.py` | Structured observations and dependencies. | Explain why a sign and the language read from that sign are not independent evidence. |
| `vestigo/verify.py` | Checks that can contradict a proposed location. | Give a case where verification rules out a candidate, and one where it must abstain. |
| `vestigo/llm.py` | Requests, usage, caches, routing and budgets. | Distinguish provider prompt caching from a local response cache. |
| `vestigo/ledger.py` | Persistent project spending guard. | Explain the difference between one-run and monthly limits. |
| `eval/harness.py` | Repeated runs, scoring, traces and reporting. | Explain why changing a prompt can invalidate cached responses. |
| `ml/embed.py`, `ml/train.py` | Frozen image features and the learned classifier head. | Identify exactly which weights were trained. |
| `site/src/main.js` | Connects the gallery, globe, trace player and opening. | Explain how recorded evidence becomes visible UI without a backend request. |

## Evidence is a contract

An evidence ID identifies an existing record. A support links a claim to that
record and contributes bounded strength. A tool can limit both its strength
and the geographic precision it supports. The board combines admissible
support and resolves through progressively finer levels.

Being cited is necessary, but a citation can still refer to weak or mistaken
evidence. Distinguish structural validation from factual verification. Read
the tests around missing citations, dependencies, precision limits and
contradictions before explaining the confidence calculation.

Exercise: describe the smallest test that would fail if an unknown evidence
ID could support an answer. Then find the actual test and compare it with
your prediction.

## The AI harness

The harness is application code surrounding pretrained models: typed requests,
tool schemas, the action loop, evidence state, routing, stopping conditions,
budgets, caches and traces. Vestigo implements this in Python. It does not
currently use LangGraph, CrewAI, ADK or a vector database.

An image embedding is a fixed-size vector produced by a pretrained encoder.
The classifier maps it to geographic cells. Saving embeddings as NumPy arrays
does not make them a vector database, and using a pretrained language model
does not mean its weights were trained in this project.

Read routing literally: the `local` preset localises extraction, while its
reasoning requests still go to an external provider. A routing label alone
does not establish that an entire investigation is local or free.

Exercise: explain what would need to change to add a new tool while leaving
the board unchanged. Use the solar and geocell tools as contrasting examples.

## Evaluation and calibration

Read `results/three_arms.md`, then `results/classifier.md`. Keep the experiment
boundaries separate. A model can correctly name a country while its guessed
point is hundreds of kilometres away. A low median distance can also conceal
a severe tail error.

The classifier's validation split groups photographs by seed location.
Otherwise nearby photographs could appear in both training and validation.
Temperature scaling changes the distribution of predicted probabilities; it
does not improve the image features or create new geographic knowledge.

Exercise: explain how two systems can have the same classification accuracy
and different calibration. Then explain why a calibrated coarse classifier
cannot justify a fine-grained claim.

## Website and animation

Read `site/src/sequence/machine.js` and `player.js` before the rendering code.
The state machine represents the page's interaction state; the player advances
through a stored investigation. Obsolete asynchronous loads must not replace
the user's latest selection.

The intro is a rendered film. Its exported laptop-screen corners position the
actual page in the filmed display. At the end, the page returns to its normal
DOM position. Skip, load failures, stalled playback and reduced motion must
all leave the page usable.

Exercise: explain how a rapid second photo selection invalidates the first
request, and why a cancelled player must never publish its final answer.

## Finish with a defensible account

Explain one successful investigation, one refusal, one limitation and one
bug covered by a regression test. Name the evidence for every result you cite.
If a number is historical, say so. If a fresh model run was not performed,
do not describe recorded playback as new inference.
