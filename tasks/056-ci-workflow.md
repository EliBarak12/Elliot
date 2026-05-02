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
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm typecheck
      - run: pnpm test:coverage
      - run: pnpm build
```

### Final Polish Checklist (do during this task)
- [ ] Add inline JSDoc to all public exported functions in `@elliot/core`
- [ ] Verify `pnpm setup` runs without error on a fresh clone
- [ ] Verify `pnpm dev` starts both plugin and Studio
- [ ] Confirm all 8 Studio pages have non-empty empty states (task 054)
- [ ] Confirm `pnpm test:coverage` hits 85% line coverage across all packages
- [ ] Add `CHANGELOG.md` to repo root with Phase 1 highlights

## Done When
- [ ] `.github/workflows/ci.yml` exists and is valid YAML
- [ ] `pnpm install && pnpm typecheck && pnpm test:coverage && pnpm build` all exit 0 locally
- [ ] Zero TypeScript errors across all packages
- [ ] All 56 tasks completed
