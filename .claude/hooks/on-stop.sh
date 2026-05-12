#!/usr/bin/env bash
# Stop hook — gates session on the full Elliot check suite.
# Returns exit 2 to prevent Claude from stopping if any check fails.
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR}"

ERRORS=()

uv run ruff check . --quiet 2>&1 || ERRORS+=("ruff: lint failed")
uv run ruff format --check . --quiet 2>&1 || ERRORS+=("ruff: formatting needed")
uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src --no-error-summary 2>&1 || ERRORS+=("mypy: type errors found")
uv run pytest --tb=line -q 2>&1 || ERRORS+=("pytest: tests failing")

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo "Check suite failed — fix before finishing:" >&2
  for e in "${ERRORS[@]}"; do
    echo "  • $e" >&2
  done
  exit 2
fi

exit 0
