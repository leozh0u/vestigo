#!/usr/bin/env bash
# Build locally and publish with a fast-forward commit on gh-pages.
set -euo pipefail
cd "$(dirname "$0")/.."

[ "$(gh api user --jq .login)" = "leozh0u" ] || { echo "Expected GitHub account leozh0u" >&2; exit 1; }
git fetch origin gh-pages
rm -rf dist
npm run build
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/vestigo-deploy.XXXXXX")
git worktree add --detach "$WORKTREE" origin/gh-pages
cleanup() { git -C "$WORKTREE" worktree remove "$WORKTREE" 2>/dev/null || true; }
trap cleanup EXIT

# -c, and this is not paranoia.
#
# rsync decides whether to copy by comparing size and modification time. Vite
# rewrites index.html by swapping one ten-character content hash for another,
# which does not change its length: the old file and the new one are both
# exactly 9231 bytes. Given a checked-out mtime that matches, rsync concludes
# they are the same file and skips it — so the assets update, the HTML that
# names them does not, and the deploy ships an index.html pointing at files
# that were deleted in the same breath.
#
# That is the failure that took the site down: a white page with an underlined
# heading. The one file whose contents matter most is the one whose size can
# never change, because a hash swap is length-preserving. Compare contents.
#
# --delete, so a file dropped from the build is dropped from the branch too.
# Without it the branch accumulates every asset the site has ever carried,
# which is how a 16 MB deploy quietly becomes a 200 MB one.
rsync -ac --delete --exclude .git dist/ "$WORKTREE/"

cd "$WORKTREE"

# ---------------------------------------------------------------------------
# Refuse to publish a set that does not agree with itself.
#
# index.html names its script and stylesheet by content hash. If either is
# missing from what is about to be pushed, the page loads and renders nothing —
# no error in the console anyone will see, no failed request anyone is
# watching, just a white page with an underlined heading on it. That shipped
# once. It cannot be allowed to ship silently again, so this turns it from a
# broken deploy into a failed one.
# ---------------------------------------------------------------------------
missing=""
for ref in $(grep -oE '/assets/[^"]+' index.html | sort -u); do
  [ -f ".${ref}" ] || missing="${missing} ${ref}"
done
if [ -n "$missing" ]; then
  echo "refusing to publish: index.html references files that are not here:" >&2
  for m in $missing; do echo "  $m" >&2; done
  echo "what is here:" >&2
  ls assets/ >&2
  exit 1
fi
echo "  index.html and assets agree"

git add -A
if git diff --cached --quiet; then
  echo "nothing changed"
  exit 0
fi
git -c user.name='Leo Zhou' -c user.email='zhouleo2007@gmail.com' commit -q -m "Build $(date -u '+%Y-%m-%d %H:%M UTC')"
if [ "${DRY:-}" = "1" ]; then
  echo "dry run passed; no push"
  exit 0
fi
git push origin HEAD:gh-pages
echo "pushed -> https://vestigo.earth/"
