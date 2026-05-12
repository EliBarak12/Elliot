#!/usr/bin/env bash
# SessionStart hook — injects contributor workspace state for Elliot development.
set -euo pipefail

BRANCH=$(git -C "${CLAUDE_PROJECT_DIR}" branch --show-current 2>/dev/null || echo "unknown")
LAST_TEST=$(git -C "${CLAUDE_PROJECT_DIR}" log --oneline -1 2>/dev/null || echo "no commits")
DIRTY=$(git -C "${CLAUDE_PROJECT_DIR}" diff --stat HEAD 2>/dev/null | tail -1 || echo "")

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Elliot Dev Session\n- Branch: ${BRANCH}\n- Last commit: ${LAST_TEST}\n- Uncommitted changes: ${DIRTY:-none}\n\n## Mandatory checks before push\n  uv run ruff check .\n  uv run ruff format --check .\n  uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src\n  uv run pytest --tb=short\n  pnpm --filter @elliot/studio run typecheck\n  pnpm --filter @elliot/studio test --run"
  }
}
EOF
