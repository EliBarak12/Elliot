#!/usr/bin/env bash
# Stop hook — gates session completion on lint passing for any modified connector.
# Returns exit 2 to prevent Claude from stopping if lint fails.
set -euo pipefail

CONNECTORS_DIR="${CLAUDE_PROJECT_DIR}/connectors"

# Find any connector files modified in the last session (within 5 minutes)
RECENT=$(find "$CONNECTORS_DIR" -name "*.connector.json" -newer "${CLAUDE_PROJECT_DIR}/.elliot/last-stop.txt" 2>/dev/null || true)

if [[ -z "$RECENT" ]]; then
  # No connectors changed — allow stop
  touch "${CLAUDE_PROJECT_DIR}/.elliot/last-stop.txt" 2>/dev/null || true
  exit 0
fi

# Run lint on each changed connector
FAILED=()
for f in $RECENT; do
  RESULT=$(uv run elliot lint "$f" 2>&1) || FAILED+=("$f: $RESULT")
done

touch "${CLAUDE_PROJECT_DIR}/.elliot/last-stop.txt" 2>/dev/null || true

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "Lint failed for modified connector(s). Fix before finishing:" >&2
  for msg in "${FAILED[@]}"; do
    echo "  $msg" >&2
  done
  exit 2
fi

exit 0
