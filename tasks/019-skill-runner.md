# 019 — Skill Runner + Binding Resolver

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 018

## Objective
Execute multi-step skills where each step's output can be bound as input to subsequent steps.

## Files to Create

### `packages/core/src/tools/skill-runner.ts`

**`executeSkill(skill: SkillDefinition, inputs: Record<string, unknown>, registry: ToolRegistry, engine: SQLiteEngine): Promise<SkillResult>`**

Step execution:
1. For each step in `skill.steps` (sequential):
   a. Resolve all parameter bindings using `resolveBindings(params, inputs, stepResults)`
   b. Find the tool by `step.toolName` in registry
   c. Execute via `executeTool()`
   d. Store result under `step.alias` in `stepResults` map
2. Return final step result (or designated output step)
3. If any step fails → throw `ElliotError` with partial step results attached

**`resolveBindings(template: Record<string, unknown>, inputs: Record<string, unknown>, stepResults: Map<string, ToolResult>): Record<string, unknown>`**
- `{{skill.input.X}}` → look up `X` in `inputs`
- `{{steps.ALIAS.FIELD}}` → look up `ALIAS` in `stepResults`, then extract `FIELD` from first row using `jsonpath-plus`
- Non-template values pass through unchanged

## Done When
- [ ] Sequential steps execute in order
- [ ] `{{skill.input.X}}` binding resolves correctly
- [ ] `{{steps.ALIAS.FIELD}}` binding resolves from previous step result
- [ ] Step failure throws with partial results
