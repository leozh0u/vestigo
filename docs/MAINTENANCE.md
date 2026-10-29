# Verification and maintenance

Vestigo has two execution contexts. The public website is static and replays
recorded investigations. The Python agent can call external models and tools
when explicitly enabled. Presentation and verification should use the offline
paths below.

## Offline checks

Python 3.12 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m vestigo.demo
.venv/bin/python -m vestigo.demo --scripted
.venv/bin/python eval/harness.py --dry --max-images 1 --samples 1
```

Use Node 22 or newer for the website:

```sh
cd site
npm ci --ignore-scripts
npm run assets:fetch
npm run assets:check
npm run check
npm run build
```

Dependency installation and the one-time asset fetch require network access.
The asset fetch retrieves static files from a pinned historical deployment and
verifies their hashes. It does not call inference or rendering services.
Subsequent checks and builds need no credentials or paid calls.

Optional classifier integration tests need locally retained checkpoints,
matching pretrained encoder weights and the ML dependencies. Their absence
does not prevent the core tests or recorded presentation from running.
Do not download new weights or rerun training merely to present the project.

## Paid execution is a separate decision

Use `eval/harness.py --help` before a fresh run. Offline cache-only execution
must refuse missing responses rather than silently call a provider. A saved
run is not evidence that a new prompt will hit the same cache.

Keep real credentials in ignored environment files. A local budget is an
application guard, not a guarantee about a provider's invoice. External
account limits remain a separate control. Do not represent ordinary
synchronous requests as discounted batch requests.

The existing `local` routing preset sends observation extraction to a local
model server but still uses an external reasoning provider. It is not an
all-local or inherently free pipeline. The fresh local classifier smoke test
is a different path, using the retained image encoders and trained head.

## Presentation assets

`site/presentation-assets.json` records the required movie and globe textures,
their hashes and the immutable deployment used to recover them. The current
gallery's photographs and trace JSON are tracked source assets. Preserve their
source and licence notices when changing the gallery.

Native Blender scenes and full render outputs are ignored, retained in the
media worktree. They are needed to reproduce the cinematic film from source.
They are not needed for a fresh checkout to recover and present the exact
published film. Archive that worktree only after preserving its ignored media.

## Deployment

After the checks and visual review:

```sh
cd site
./scripts/deploy.sh
```

The script verifies the GitHub account, builds, validates assets and publishes
a fast-forward commit on `gh-pages`. Confirm that GitHub Pages finishes its
build and that the live manifest selects the expected video. Keep source and
deployment commits in the release record.

## Known boundaries

- The gallery is curated recorded output, including refusals. It does not
  accept arbitrary public image uploads or spend an API budget per visitor.
- A fresh paid vision/reasoning run is not part of offline verification.
- Historic evaluation scores are not new results from the current hardening
  pass. Re-evaluation would require a separate approved inference budget.
- The exterior and room are rendered scenes. Their geometry and materials
  retain visible CGI characteristics; successful playback is not proof of
  complete photorealism.
- External APIs, browsers and dependencies can change. The automated checks
  and retained artifacts support future maintenance; they do not eliminate it.
