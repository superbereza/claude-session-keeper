#!/usr/bin/env bash
# bump.sh <new-version> — set the version in VERSION and every plugin manifest,
# so they never drift. Run from the repo root: ./scripts/bump.sh 0.2.0
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: scripts/bump.sh <new-version>" >&2; exit 2; }
new="$1"
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

printf '%s\n' "$new" > VERSION
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json \
         .cursor-plugin/plugin.json .codex-plugin/plugin.json gemini-extension.json package.json; do
  [ -f "$f" ] && perl -0pi -e 's/("version"\s*:\s*")[^"]+(")/${1}'"$new"'${2}/g' "$f"
done

echo "bumped to $new. Next: git commit && git tag v$new"
