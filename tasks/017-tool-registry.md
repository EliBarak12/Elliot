# 017 — Tool Registry

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 016

## Objective
In-memory store for tool and skill definitions with CRUD and uniqueness enforcement.

## Files to Create

### `packages/core/src/tools/registry.ts`

**Class `ToolRegistry`:**
- `add(tool: ToolDefinition): void` — validate + store; throw if name already exists
- `update(toolId: string, patch: Partial<ToolDefinition>): ToolDefinition` — merge + re-validate
- `delete(toolId: string): void`
- `get(toolId: string): ToolDefinition | undefined`
- `getByName(name: string): ToolDefinition | undefined`
- `getAll(): ToolDefinition[]`
- `addSkill(skill: SkillDefinition): void`
- `updateSkill(skillId: string, patch: Partial<SkillDefinition>): SkillDefinition`
- `deleteSkill(skillId: string): void`
- `getSkill(skillId: string): SkillDefinition | undefined`
- `getAllSkills(): SkillDefinition[]`
- `clear(): void` — remove all tools and skills

## Done When
- [ ] Adding tool with duplicate name throws
- [ ] Update merges partial fields, re-validates
- [ ] `getAll()` returns tools in insertion order
