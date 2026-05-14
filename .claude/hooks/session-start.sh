#!/usr/bin/env bash
# SessionStart hook — injects contributor workspace state for Elliot development.
#
# All git-derived values are escaped with python3's json.dumps before being
# spliced into the JSON envelope (audit Low item): a branch name or commit
# subject containing `"`, `\`, or a newline would otherwise corrupt the
# additionalContext payload (broken context injection, not RCE).
set -euo pipefail

BRANCH=$(git -C "${CLAUDE_PROJECT_DIR}" branch --show-current 2>/dev/null || echo "unknown")
LAST_TEST=$(git -C "${CLAUDE_PROJECT_DIR}" log --oneline -1 2>/dev/null || echo "no commits")
DIRTY=$(git -C "${CLAUDE_PROJECT_DIR}" diff --stat HEAD 2>/dev/null | tail -1 || echo "")
DIRTY="${DIRTY:-none}"

# Build the additionalContext string then JSON-encode it as a whole, so
# embedded quotes/newlines/backslashes are escaped correctly.
CONTEXT=$(
  python3 - "${BRANCH}" "${LAST_TEST}" "${DIRTY}" <<'PY'
import json
import sys

branch, last_commit, dirty = sys.argv[1], sys.argv[2], sys.argv[3]
ctx = (
    "## Elliot Dev Session\n"
    f"- Branch: {branch}\n"
    f"- Last commit: {last_commit}\n"
    f"- Uncommitted changes: {dirty}\n\n"
    "## Mandatory checks before push\n"
    "  uv run ruff check .\n"
    "  uv run ruff format --check .\n"
    "  uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src\n"
    "  uv run pytest --tb=short\n"
    "  pnpm --filter @elliot/studio run typecheck\n"
    "  pnpm --filter @elliot/studio test --run"
)
# Emit as a JSON string (with surrounding quotes) so the bash here-doc can
# splice it straight into the outer JSON object below.
print(json.dumps(ctx))
PY
)

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": ${CONTEXT}
  }
}
EOF
