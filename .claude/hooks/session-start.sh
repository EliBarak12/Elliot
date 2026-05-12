#!/usr/bin/env bash
# SessionStart hook — injects current Elliot workspace state into the session.
set -euo pipefail

CONNECTORS_DIR="${CLAUDE_PROJECT_DIR}/connectors"
CONNECTOR_COUNT=$(find "$CONNECTORS_DIR" -name "*.connector.json" 2>/dev/null | wc -l | tr -d ' ')
LINT_STATUS="not run"
EVAL_STATUS="not run"

# Surface the most recent lint result if one exists
LINT_LOG="${CLAUDE_PROJECT_DIR}/.elliot/last-lint.txt"
if [[ -f "$LINT_LOG" ]]; then
  LINT_STATUS=$(cat "$LINT_LOG")
fi

# Surface the most recent eval result if one exists
EVAL_LOG="${CLAUDE_PROJECT_DIR}/.elliot/last-eval.txt"
if [[ -f "$EVAL_LOG" ]]; then
  EVAL_STATUS=$(cat "$EVAL_LOG")
fi

# Emit structured context back to Claude
cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Elliot Workspace\n- Connectors in ./connectors/: ${CONNECTOR_COUNT}\n- Last lint: ${LINT_STATUS}\n- Last eval: ${EVAL_STATUS}\n\nMCP plugin is at http://localhost:3000/mcp. Use /build-connector to start a new connector, /lint-connector to validate, /run-eval to test quality."
  }
}
EOF
