# Elliot — Full System Architecture

## System Overview

Elliot is a connector platform that turns REST APIs, databases, and files into MCP tools. The system comprises three Python services and one TypeScript app:

- `elliot-mcp-plugin` — FastMCP + FastAPI on :3000 (for building connectors)
- `elliot-connector-runtime` — FastAPI + FastMCP on :3001 (for serving connectors)
- `elliot-core` — shared Python library
- `elliot-studio` — React + Vite dashboard on :5173

## Port Map & Environment Variables

| Service | Port | Entry Point | Key Env Vars |
|---|---|---|---|
| `elliot-studio` | 5173 | `vite dev` | `VITE_PLUGIN_URL`, `VITE_RUNTIME_URL` |
| `elliot-mcp-plugin` | 3000 | `uvicorn elliot_mcp_plugin.server:app` | `ELLIOT_CONNECTORS_DIR`, `LOG_LEVEL` |
| `elliot-connector-runtime` | 3001 | `uvicorn elliot_connector_runtime.server:app` | `ELLIOT_CONNECTOR`, `ELLIOT_AUDIT_LOG`, `LOG_LEVEL` |
