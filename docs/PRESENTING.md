# Presenting Vestigo

The public site plays recorded investigations. Selecting a photograph does not
send it to a model. The Python demo also runs without credentials or network
access. Keep those distinctions explicit during a presentation.

## Prepare

From the repository root, with Python 3.12 or newer:

```sh
python3 -m vestigo.demo
python3 -m vestigo.demo --scripted
```

For the website:

```sh
cd site
npm ci --ignore-scripts
npm run assets:fetch
npm run assets:check
npm run check
npm run build
npm run preview -- --host 127.0.0.1
```

The asset fetch restores checksum-locked copies of the existing published
movie and globe textures. It calls no model or map service and generates no
new media. After the assets are present, the checks and build run locally.

Open the preview address printed by Vite, or use https://vestigo.earth.
Close the preview and stop its server with Ctrl+C when finished. For a
screen-share, use a browser window containing only the presentation.

## A five-minute walkthrough

1. Play the introduction once. Explain that the apartment is a fictional set
   and the final laptop screen becomes the interactive page. Skip or Escape
   is available throughout; reduced-motion preferences bypass the film.
2. Select the mosque photograph, the first example in the index. Follow the
   observations, tool evidence and claim hierarchy through to its recorded
   answer. The displayed answer is an output to inspect, not ground truth.
3. Select an example that stops at country level, such as the thirteenth
   photograph. Explain what extra evidence a city claim would require.
4. Select one of the last five examples, which declined to make a claim.
   Show that declining is an ordinary result of the thresholds.
5. Run `python3 -m vestigo.demo`, then `python3 -m vestigo.demo --scripted`.
   The first displays a historical investigation. The second exercises the
   current Agent and Board using deliberately synthetic replies.
6. Open `vestigo/agent.py`, `vestigo/board.py` and `vestigo/llm.py` to connect
   the demonstration to the implementation. Use the learning guide for depth.

## The explanation to own

Vestigo combines an observation model, a reasoning model and tools around an
evidence board. The model proposes locations and claims. Code checks citations,
limits how much evidence can support a claim, and chooses the finest claim
that clears its threshold. This prevents particular unsupported outputs; it
does not establish that every surviving conclusion is correct.

The trained classifier is a separate component. A frozen image encoder creates
features, and a trained linear head predicts a coarse geographic cell.
Temperature scaling was fitted against held-out data. Its measured calibration
does not make every prediction reliable on unfamiliar photographs.

## Numbers and their sources

| Result | Source and interpretation |
| --- | --- |
| 142 km median, 3.7% expected calibration error | Historical single-SigLIP classifier result in `results/classifier.md`. |
| 128 km median, 55.6% cell accuracy, 4.0% expected calibration error | Saved paired-encoder checkpoint metrics in `results/classifier_pair.json`; 13,055 validation images. These are historical metrics, not a new evaluation. |
| 94 km versus 118 km on two image-only samples | Eight-image rural experiment in `results/three_arms.md`; illustrates sampling variance, not a large benchmark. |

The classifier validation, rural baseline and agent evaluations are different
experiments. Do not compare their medians as if they were the same test set.
The board's combined confidence scores are heuristic evidence scores; the
classifier's temperature-scaled probabilities are the separately calibrated
component. Neither the gallery nor a screenshot proves benchmark accuracy.

## Questions to prepare for

- Why keep the model's first guess before calling tools?
- What stops an invented evidence ID or an overly precise claim?
- How can correlated observations inflate confidence?
- Why are image groups held together when splitting classifier data?
- What changes during training, and what stays frozen?
- What is cached, what makes a cache miss, and what prevents spending?
- What would a fresh end-to-end run require that this presentation does not?

Current constraints and verification commands are in [MAINTENANCE.md](MAINTENANCE.md).
The code-reading order is in [LEARNING.md](LEARNING.md).
