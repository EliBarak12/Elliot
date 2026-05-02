# 046 — Playground Page

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 045

## Objective
Manual tool invocation UI. Select a tool, fill in parameters, run it, inspect the result. No AI involved.

## Files to Create

### `src/pages/PlaygroundPage.tsx`
Two-panel layout:
- **Left panel — Tool Invoker:**
  - Tool selector dropdown (from `useTools()`)
  - Dynamic parameter form: one input per tool parameter, type-appropriate input (text / number / date / checkbox)
  - "Run" button → calls `callTool(selectedTool.name, params)` via `useCallTool()`
  - Loading state while running
  - Error display if tool call fails

- **Right panel — Result + History:**
  - Result viewer: formatted JSON with syntax highlighting, latency badge
  - Invocation history list (most recent first): tool name, params summary, latency, timestamp
  - Click history item → pre-fills the form with same params
  - "Export as fixture" button → downloads invocation as JSON for use in eval suites

### `src/components/playground/ParameterForm.tsx`
- Renders inputs dynamically from `tool.parameters`
- STRING → `<Input>`, INTEGER/NUMBER → `<Input type="number">`, BOOLEAN → `<Checkbox>`, DATE → `<Input type="date">`
- Required params marked with `*`
- Validates all required fields are filled before enabling "Run"

### `src/components/playground/ResultViewer.tsx`
- Renders JSON with indentation and syntax colouring
- Shows `rowCount` and `latencyMs` in a badge bar
- "Copy" button

## Done When
- [ ] Selecting a tool renders correct parameter form
- [ ] Running tool shows result in right panel
- [ ] History list grows with each invocation
- [ ] Clicking history item pre-fills form
