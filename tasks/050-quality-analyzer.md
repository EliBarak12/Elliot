# 050 — Description Quality Analyzer

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 049

## Objective
Static analysis of tool descriptions and parameter definitions to score connector quality.

## Files to Create

### `packages/core/src/evaluation/quality-analyzer.ts`

**`analyzeConnectorQuality(config: ConnectorConfig): ConnectorQualityScore`**

Run these checks against each tool:

| Check | Rule | Severity |
|-------|------|----------|
| `min_length` | description ≥ 20 chars | error |
| `starts_with_verb` | description starts with a verb (Returns, Lists, Gets, Finds, Creates, Updates, Deletes, Calculates) | warning |
| `no_jargon` | description does not contain: `SQL`, `endpoint`, `query`, `table`, `column`, `database`, `API` | warning |
| `has_params_described` | every required parameter has a non-empty description | error |
| `name_snake_case` | tool name matches `/^[a-z][a-z0-9_]*$/` | error |
| `no_generic_names` | tool name is not `query`, `get_data`, `fetch`, `run` | warning |

**Returns:**
```typescript
interface ConnectorQualityScore {
  overallScore: number;       // 0–100
  toolScores: ToolQualityScore[];
  errorCount: number;
  warningCount: number;
}
```

## Done When
- [ ] Tool with short description fails `min_length`
- [ ] Tool description `"SQL query for users"` fails `no_jargon`
- [ ] Well-written tool passes all checks with score 100
- [ ] Overall score reflects proportion of passing checks
