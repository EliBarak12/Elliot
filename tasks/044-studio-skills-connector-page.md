# 044 — Skills + Connector Page

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 043

## Objective
Skill builder UI and connector assembly + export page.

## Files to Create

### `src/pages/SkillsPage.tsx`
- Skill list with step count badge
- "New Skill" button → opens `SkillEditor`

### `src/components/skills/SkillEditor.tsx`
- Name, description fields
- Steps list:
  - Each step: alias, tool selector dropdown, binding editor for each tool param
  - Binding editor: free text or `{{skill.input.X}}` / `{{steps.ALIAS.FIELD}}` template
  - Add/remove steps
- "Save" → `elliot_create_skill` or `elliot_update_skill`
- "Test" → input form for skill inputs → `elliot_preview_skill` → show result

### `src/pages/ConnectorPage.tsx`
- Two columns: Tools selector (checkboxes) + Skills selector
- "Build Connector" button → calls `elliot_build_connector` with selected IDs
- Connector info panel (name, version, tool count, skill count)
- "Export" button → `elliot_export_connector`
- "Start Runtime" button → `elliot_start_runtime` → shows running URL
- Connection config card with copy-to-clipboard button

## Done When
- [ ] Skill with 2 steps can be created and tested via UI
- [ ] Connector built from selected tools shows correct count
- [ ] Connection config copy button works
