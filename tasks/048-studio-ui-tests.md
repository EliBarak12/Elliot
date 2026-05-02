# 048 — Studio Unit Tests

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 047

## Objective
Unit tests for the most critical Studio components using Vitest + React Testing Library.

## Files to Create
- `packages/studio/src/tests/unit/ToolCard.test.tsx`
- `packages/studio/src/tests/unit/ToolEditor.test.tsx`
- `packages/studio/src/tests/unit/ParameterForm.test.tsx`
- `packages/studio/src/tests/unit/ResultViewer.test.tsx`

## Setup
Add to `packages/studio/package.json` devDeps:
- `@testing-library/react ^15`
- `@testing-library/user-event ^14`
- `@testing-library/jest-dom ^6`
- `jsdom` (vitest environment)

Update `packages/studio/vitest.config.ts`: `environment: 'jsdom'`

## Required Tests

**ToolCard.test.tsx:**
- Renders tool name and description
- Shows correct badge colour for each `ToolCategory`
- `onClick` fires when card is clicked

**ToolEditor.test.tsx:**
- "Save" button disabled when name is empty
- Submitting valid form calls `elliot_create_tool` with correct args
- Validation error shown for name with spaces

**ParameterForm.test.tsx:**
- INTEGER param renders `<input type="number">`
- BOOLEAN param renders checkbox
- Required param marked with `*`
- "Run" disabled until all required fields filled

**ResultViewer.test.tsx:**
- Renders JSON correctly
- Copy button copies text to clipboard
- Shows latency badge

## Done When
- [ ] All tests pass in jsdom environment
- [ ] `pnpm --filter @elliot/studio test` exits 0
