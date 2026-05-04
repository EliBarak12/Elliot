# 043 — Tools Page + Filter Builder

**Sprint**: 4 | **Estimate**: 5h | **Depends on**: 042

## Objective
Tool management UI: list, create, edit, and test tools using the **filter/return model** — no raw SQL. The agent defines filter conditions and return fields; Elliot generates SQL internally.

## Files to Create

### `src/pages/ToolsPage.tsx`
- Left panel: tool cards (name, category badge, description, call count)
- Right panel: `<ToolEditor>` for selected tool
- "New Tool" button → opens blank READ editor

### `src/components/tools/ToolCard.tsx`
- Name, category badge (READ=blue, WRITE=orange, AGGREGATE=purple, ACTION=red)
- Description preview (truncated 80 chars)
- Click → select tool, open editor

### `src/components/tools/ToolEditor.tsx`
Top-level fields:
- `id` — snake_case input, validates `/^[a-z][a-z0-9_]*$/` client-side
- `description` — textarea, char counter (target ≥ 20)
- `category` — dropdown: READ | WRITE | ACTION | AGGREGATE
- `source_ids` — multi-select of available sources (from `useSources()`)
- `parameters` — expandable list: add/remove rows (name, type, required, description)

Conditionally rendered based on `category`:
- **READ / AGGREGATE** → `<FilterGroupBuilder>` + `<ReturnFieldSelector>`
- **WRITE / ACTION** → `<ApiMappingForm>`

Actions:
- "Validate" → calls `elliot_validate_tool { tool }` MCP tool → inline OK / error banner
- "Save" → calls `elliot_create_tool` or `elliot_update_tool`
- "Test" panel (shown after save) → `<ToolTester>`

### `src/components/tools/FilterGroupBuilder.tsx`
Editable list of `FilterGroup` objects:
```tsx
interface FilterGroupBuilderProps {
  groups: FilterGroup[]
  onChange: (groups: FilterGroup[]) => void
  availableFields: string[]   // from loaded sources
}
```
Each group shows:
- Logic toggle **AND** | **OR**
- Condition rows:
  - `field` — text input (e.g. `products.category`)
  - `operator` — dropdown: `=` `!=` `>` `<` `>=` `<=` `contains` `in_list` `is_null` `is_not_null`
  - Value type toggle: **Parameter** | **Fixed**
    - Parameter: `parameter_name` input — must match a parameter in the tool
    - Fixed: `value` input — hardcoded, no param binding
  - Remove (×) button per condition
- "+ Add condition" button
- "+ Add group" button at bottom

### `src/components/tools/ReturnFieldSelector.tsx`
Editable table of `ReturnField` rows:
```tsx
interface ReturnField {
  field: string         // e.g. "products.name"
  alias?: string        // optional rename in output
  aggregation?: 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX'
}
```
- `field` text input, `alias` text input, `aggregation` dropdown (empty = none)
- Drag-to-reorder (use `@dnd-kit/sortable` or simple up/down arrows)
- "+ Add return field" button

### `src/components/tools/ApiMappingForm.tsx`
For WRITE/ACTION tools:
```tsx
interface ApiMappingFormProps {
  value: ApiRequestMapping
  onChange: (m: ApiRequestMapping) => void
}
```
- `method` — dropdown: GET | POST | PUT | PATCH | DELETE
- `path_template` — text input e.g. `/users/{user_id}` (shows hint: `{param}` tokens map to path params)
- `query_params` — tag input (comma-separated param names sent as `?key=value`)
- `body_params` — tag input (param names sent in request body)
- `body_format` — dropdown: `json` | `form`

### `src/components/tools/ToolTester.tsx`
```tsx
// Renders one input per tool.parameters entry
// Required params marked with *
// "Run" disabled until all required fields filled
// On Run: callTool('elliot_preview_tool', { tool_id, params }) via useCallTool()
// Shows result rows in <Table> with latency badge
// No runtime connection needed — preview runs in-process via plugin
```

## Done When
- [ ] READ tool: FilterGroupBuilder + ReturnFieldSelector shown; ApiMappingForm hidden
- [ ] WRITE tool: ApiMappingForm shown; filter/return hidden
- [ ] Adding a parameter updates the FilterGroupBuilder's `parameter_name` autocomplete
- [ ] Save calls correct MCP tool with full `FilterGroup[]` / `ReturnField[]` payload
- [ ] Validate shows inline success/error banner
- [ ] ToolTester shows result rows in a table after run
