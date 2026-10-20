#!/usr/bin/env bash
# Run an eval from a frozen snapshot of the current commit, so development can continue
# in the working tree while a multi-hour eval runs (each run spawns a fresh MCP server,
# which would otherwise pick up half-finished edits).
#   scripts/eval_snapshot.sh v2 --n 21 --tiers easy,medium,hard --seed0 3000 --video
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$1"; shift
SNAP="${DSM_SNAP_ROOT:-/opt/dsm-snap}/$VERSION"
REPO="$(git rev-parse --show-toplevel)"
SUB="$(git rev-parse --show-prefix)"   # drone-search-mcp/
if [ ! -d "$SNAP" ]; then
  mkdir -p "$(dirname "$SNAP")"
  git -C "$REPO" worktree add --detach "$SNAP/repo" HEAD >/dev/null
  ln -s "$PWD/.venv" "$SNAP/repo/$SUB.venv"
  ln -s "$PWD/sim/generated" "$SNAP/repo/${SUB}sim/generated"
fi
cd "$SNAP/repo/$SUB"
echo "[snapshot] $(git rev-parse --short HEAD) at $PWD"
source scripts/env.sh
exec .venv/bin/python eval/run.py --version "$VERSION" "$@"
