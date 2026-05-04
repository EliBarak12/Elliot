# 056 — CI Workflow

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 055

## Objective
GitHub Actions CI that runs on every push and PR. Green CI = project is shippable.

## Files to Create

### `.github/workflows/ci.yml`
```yaml
name: CI

on:
  push:
    branches: [main, "epic/**", "claude/**"]
  pull_request:

jobs:
  python:
    name: Python (lint + typecheck + test)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
          python-version: "3.13"

      - run: uv sync

      - name: Lint
        run: uv run ruff check .

      - name: Format check
        run: uv run ruff format --check .

      - name: Type check
        run: uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src

      - name: Test with coverage
        run: uv run pytest --tb=short --cov --cov-fail-under=85

  studio:
    name: Studio (typecheck + test + build)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: pnpm/action-setup@v4
        with:
          version: 9

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "pnpm"

      - run: pnpm install --frozen-lockfile

      - name: Type check
        run: pnpm --filter @elliot/studio run typecheck

      - name: Unit tests
        run: pnpm --filter @elliot/studio run test --run

      - name: Build
        run: pnpm --filter @elliot/studio run build
```

### Final Polish Checklist
- [ ] `make setup` runs without error on a fresh clone
- [ ] `make dev` starts plugin, runtime, and Studio
- [ ] All 8 Studio pages have non-empty empty states (task 054)
- [ ] `uv run pytest --cov` hits 85% line coverage
- [ ] `CHANGELOG.md` at repo root with v0.1.0 highlights

## Done When
- [ ] `.github/workflows/ci.yml` passes `yamllint`
- [ ] Python job exits 0 (ruff + mypy + pytest at 85%)
- [ ] Studio job exits 0 (tsc + vitest + vite build)
- [ ] Zero mypy errors across all packages
