# The connector runtime (:3001) is NOT started here — it is connector-bound
# and is launched on demand by the `elliot_start_runtime` MCP tool once a
# connector has been built and exported. Starting it here with no connector
# would squat on port 3001 in a degraded no-connector state.
plugin:  uv run uvicorn elliot_mcp_plugin.main:app --port 3000 --reload --app-dir packages/mcp-plugin/src
studio:  pnpm --filter @elliot/studio run dev
