# 016 — Tool + Skill Validator

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005, 010

## Objective
Zod-based validation for tool definitions, skill definitions, and full connector configs.

## Files to Create

### `packages/core/src/tools/validator.ts`

**Zod schemas:**
- `ParameterDefinitionSchema` — name, type (`string|integer|number|boolean|date`), required, description, defaultValue
- `ToolDefinitionSchema` — id, name (snake_case only), description (min 10 chars), category (`READ|ACTION|AGGREGATE`), sql, parameters, responseShape
- `SkillDefinitionSchema` — id, name, description, steps (min 1), inputParameters
- `ConnectorConfigSchema` — full connector including sources, tools, skills, name, version, slug

**Additional validation beyond Zod:**
- `validateToolSqlParams(tool: ToolDefinition): ValidationResult` — every `:param` in SQL must have a matching entry in `tool.parameters`; every parameter must appear as `:param` in SQL
- `validateToolDefinition(tool: unknown): ValidationResult` — run Zod + SQL param check

## Done When
- [ ] Valid tool passes all checks
- [ ] Tool with `:missing_param` in SQL but not in parameters → error
- [ ] Tool with parameter defined but no `:param` in SQL → warning
- [ ] Tool name with spaces → Zod error
- [ ] Tool description < 10 chars → Zod error
