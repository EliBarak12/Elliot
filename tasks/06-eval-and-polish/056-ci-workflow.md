# 056 — CI Workflow + Final Polish

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 055

## Objective
GitHub Actions CI that runs on every push and PR. Green CI = project is shippable.

## Files to Create

### `.github/workflows/ci.yml`
```yaml
name: CI
on: [push, pull_request]
jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with: { version: "latest" }
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src
      - run: uv run pytest --cov --cov-fail-under=85
  studio:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm --filter @elliot/studio run typecheck
      - run: pnpm --filter @elliot/studio run test
      - run: pnpm --filter @elliot/studio run build
```

### Final Polish Checklist
- [ ] Add docstrings to all public functions in `elliot_core`
- [ ] Verify `make setup` runs without error on a fresh clone
- [ ] Verify `make dev` starts both plugin and Studio
- [ ] Confirm all 8 Studio pages have non-empty empty states (task 054)
- [ ] `uv run pytest --cov` hits 85% line coverage across all packages
- [ ] Add `CHANGELOG.md` to repo root with Phase 1 highlights

## Done When
- [ ] `.github/workflows/ci.yml` exists and is valid YAML
- [ ] Python CI job exits 0 locally
- [ ] Studio CI job exits 0 locally
- [ ] Zero type errors across all packages
- [ ] All 56 tasks completed
