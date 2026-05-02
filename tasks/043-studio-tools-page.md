# 043 — Tools Page + SQL Editor

**Sprint**: 4 | **Estimate**: 4h | **Depends on**: 042

## Objective
Tool management UI: list, create, edit, and test tools with an inline SQL editor.

## Files to Create

### `src/pages/ToolsPage.tsx`
- Left panel: tool cards (name, category badge, description, call count)
- Right panel: `ToolEditor` for selected tool
- "New Tool" button → opens blank editor

### `src/components/tools/ToolCard.tsx`
- Name, category badge (color-coded: READ=blue, ACTION=orange, AGGREGATE=purple)
- Short description preview
- Click → select tool and open editor

### `src/components/tools/ToolEditor.tsx`
- Fields: name (snake_case enforced), description, category dropdown
- `SqlEditor` component (CodeMirror with SQL syntax highlight)
- Parameters list: add/edit/remove rows (name, type, required toggle, description)
- Response shape config: fields filter, maxRows
- "Validate SQL" button → calls `elliot_validate_sql`
- "Save" button → calls `elliot_create_tool` or `elliot_update_tool`
- "Test" section: parameter input form → "Run" → calls `elliot_preview_tool` → shows result table

### `src/components/tools/SqlEditor.tsx`
- CodeMirror 6 with SQL language support
- Highlights `:paramName` tokens
- Calls `elliot_validate_sql` on blur, shows inline error/success

## Done When
- [ ] Tool can be created from scratch via UI
- [ ] SQL validation feedback shown inline
- [ ] Test runner returns results in a table
