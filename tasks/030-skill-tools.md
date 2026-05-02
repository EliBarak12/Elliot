# 030 — Skill MCP Tools

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 029

## Objective
MCP tools that let the agent define and test multi-step skills.

## Files to Create

### `packages/mcp-plugin/src/tools/skill-tools.ts`

Implement `registerSkillTools(server, session)`:

| Tool | Input | Action |
|------|-------|--------|
| `elliot_create_skill` | Full `SkillDefinition` fields | Validate all `step.toolName` exist in registry → add → save |
| `elliot_update_skill` | `skillId`, partial fields | Merge → re-validate → save |
| `elliot_list_skills` | — | Return all skills |
| `elliot_get_skill` | `skillId` | Return full skill definition |
| `elliot_preview_skill` | `skillId`, `inputs` | Execute all steps → return final result |
| `elliot_delete_skill` | `skillId` | Remove → save |

## Done When
- [ ] `elliot_create_skill` with non-existent `toolName` in a step → validation error
- [ ] `elliot_preview_skill` runs all steps and returns final step result
