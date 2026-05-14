#!/usr/bin/env bash
# Stop hook — gates session on the full Elliot check suite.
# Returns exit 2 to prevent Claude from stopping if any check fails.
#
# Each step is wrapped in `timeout` so a hung test or runaway type-checker
# can't pin the Stop hook indefinitely (audit Low item).
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR}"

ERRORS=()
RUFF_TIMEOUT=30
MYPY_TIMEOUT=120
PYTEST_TIMEOUT=300

timeout "${RUFF_TIMEOUT}" uv run ruff check . --quiet 2>&1 || ERRORS+=("ruff: lint failed (or timed out)")
timeout "${RUFF_TIMEOUT}" uv run ruff format --check . --quiet 2>&1 || ERRORS+=("ruff: formatting needed (or timed out)")
timeout "${MYPY_TIMEOUT}" uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src --no-error-summary 2>&1 || ERRORS+=("mypy: type errors found (or timed out)")
timeout "${PYTEST_TIMEOUT}" uv run pytest --tb=line -q 2>&1 || ERRORS+=("pytest: tests failing (or timed out)")

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo "Check suite failed — fix before finishing:" >&2
  for e in "${ERRORS[@]}"; do
    echo "  • $e" >&2
  done
  exit 2
fi

exit 0
