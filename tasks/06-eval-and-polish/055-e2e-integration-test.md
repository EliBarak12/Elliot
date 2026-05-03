# 055 — End-to-End Integration Test

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 037, 032

## Objective
Single test that exercises the complete Phase 1 flow from source discovery to live tool call via the runtime.

## Files to Create
- `packages/mcp-plugin/tests/integration/test_e2e_flow.py`

## Test Scenario (all in-process, no running server)
```python
def test_full_e2e_flow(session, tmp_path):
    # 1. Create ElliotSession
    # 2. Discover CSV source
    # 3. Query SQL to verify data loaded
    # 4. Create a tool
    # 5. Preview the tool
    # 6. Build connector
    # 7. Export connector to file
    # 8. Load exported connector into runtime ToolExecutor
    # 9. Execute tool via runtime executor (mocked REST with respx)
    # 10. Assert result matches expected
    # 11. Assert audit.ndjson has 1 entry
```

## Done When
- [ ] All steps pass
- [ ] Test runs in CI without any external services
- [ ] Full flow completes in < 10 seconds
