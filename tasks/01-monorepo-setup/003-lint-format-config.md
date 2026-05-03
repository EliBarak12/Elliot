# 003 — ESLint + Prettier Config

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 002

## Objective
Shared linting and formatting rules for all packages.

## Files to Create
- `.eslintrc.cjs` — `@typescript-eslint/recommended`, parser `@typescript-eslint/parser`, rules: `no-explicit-any: error`, `no-unused-vars: error`, `verbatim-module-syntax` compatible settings.
- `.prettierrc` — `{ "semi": true, "singleQuote": true, "trailingComma": "all", "printWidth": 100 }`
- `.eslintignore` — `dist/`, `node_modules/`, `*.config.ts`

## Done When
- [ ] `pnpm lint` exits 0 on empty packages
- [ ] `prettier --check .` exits 0
