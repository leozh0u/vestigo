# Presentation readiness, 29 October 2026

This pass hardens the existing Vestigo demonstration and Python pipeline.
It does not report a new paid-model benchmark or a photorealism result.
No paid inference, map, generation or rendering requests were made.

## System and scope

The public site is a static Vite/Three.js application. Visitors choose among
24 stored investigations; trace JSON drives the evidence panels and globe.
The opening movie projects the working page into the filmed laptop before
restoring its normal DOM position. There is no public upload or inference
endpoint, account system, or customer database in this application.

The Python path uses pretrained model adapters, a custom agent loop, an
evidence board, optional local tools, response caches and a spending ledger.
The evaluation CLI now defaults to cache-only operation and refuses misses.
Fresh external requests require `--live`. The local classifier is a separate
frozen-encoder/learned-head path.

## Coverage and evidence

| Area | Reviewed and tested | Boundary |
| --- | --- | --- |
| Evidence and agent | Citations, missing IDs, precision caps, malformed replies, failed tools, contradictions and current scripted Agent/Board exercise. | Structural validation cannot prove a model's factual interpretation. |
| Provider accounting | Concurrent in-flight budget reservations, per-run usage, atomic caches/ledger updates, corrupt ledgers, cache misses and unsupported batch discounts. | No fresh paid provider response was requested. Local guards do not replace provider billing controls. |
| Python packaging | Fresh isolated dev installation; core suite; built wheel installed and executed in isolated mode with packaged replay fixtures. | Optional tests require locally retained ML dependencies, checkpoints or embeddings. |
| Evaluation CLI | Clean-checkout dry run, relative and external absolute output, failures saved, synthetic metrics explicitly invalid. | Synthetic replies establish plumbing, not prediction quality. |
| Website | Actual desktop and phone gallery, rapid selections, resize, retry after failures, escaped output, no-WebGL fallback, keyboard/focus and reduced motion. | Tested in Chromium; other browser engines were not exercised in this pass. |
| Intro | Uninterrupted desktop and 390x844 phone playback through the live portal, restored DOM/focus, Skip, Escape and blocked/stalled video recovery. | Existing rendered exterior retains visible CGI characteristics. |
| Assets and build | Fresh dependency installation, checksum recovery of 11 pinned assets, all 24 investigations, 576 projection cases, four generation guards and production build. | Native render sources remain ignored local media and must be preserved separately. |
| Source/dependencies | Credential-pattern scan, safe rendering review, dependency advisory review, shell syntax and diff checks. | A clean scan does not prove the absence of every vulnerability or secret. |

## Results

- Retained development environment: `python -m pytest -q` completed with
  **457 passed, 15 skipped**. Optional artifact-dependent tests skip explicitly.
- Fresh isolated environment without ML artifacts: **441 passed, 10 skipped**.
  Module-level optional skips change how many parameterized cases are collected.
- `python3 -m vestigo.demo` and all three recorded cases ran without network
  access or credentials. `--scripted` exercised the current agent, capped a
  point request to country evidence and rejected an invented evidence ID.
- `python3 eval/harness.py --dry --max-images 1 --samples 1` completed from
  the fresh snapshot. Its JSON says `mode=scripted`, `metrics_valid=false`
  and zero spend.
- An actual offline classifier call on the committed Lahore photograph
  succeeded using retained paired encoders and the existing checkpoint. The
  top cell was centred at 31.1562, 74.0923, probability 0.6961. This is one
  smoke test, not an accuracy benchmark.
- `npm ci --ignore-scripts`, `npm run assets:fetch`, `npm run assets:check`,
  `npm run check` and `npm run build` passed from a fresh snapshot without
  ignored render files, caches, checkpoints or preinstalled dependencies.
- Dependency updates within the existing major versions removed the six
  reported development-tool audit findings. `npm audit --json` then reported
  zero findings across production and development dependencies. Relevant
  advisories: [Vite](https://github.com/advisories/GHSA-rq7h-c2jc-7f22),
  [source-map-js](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) and
  [Zod](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5).
- The build retains its existing roughly 542 kB main-chunk advisory. The
  website remains usable; this is a bundle-size advisory, not a failed build.

## Reproducing the checks

Use [MAINTENANCE.md](MAINTENANCE.md) for setup and exact commands.
[PRESENTING.md](PRESENTING.md) gives a short demonstration;
[LEARNING.md](LEARNING.md) maps the explanation back to the code.
CI runs the Python suite and offline demos, then checks assets and builds the
site from a fresh Ubuntu checkout with Python 3.12 and Node 22.

The independent review uses at most three rounds. Round one found an absolute
output-path failure after the harness saved its JSON. The completion message
was fixed and a CLI regression now requires successful return and valid
output for both path forms; the actual CLI also passed in a separate process.
Release confirmation and final review are recorded
in the task ledger and canonical project context.
