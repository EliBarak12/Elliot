from elliot_core.types.connector import ConnectorConfig
from elliot_mcp_plugin.server import build_tool_list, create_server

_CONFIG = ConnectorConfig(
    name="Demo",
    slug="demo",
    version="0.1.0",
    description="Demo connector",
    sources=[{"id": "s1", "name": "Source 1", "type": "file", "path": "data.csv"}],
    tools=[
        {
            "id": "list_users",
            "name": "List Users",
            "description": "List all users from the system",
            "category": "READ",
            "source_ids": ["s1"],
            "parameters": [
                {
                    "name": "limit",
                    "type": "integer",
                    "description": "Max rows to return",
                    "required": False,
                    "default": 10,
                }
            ],
        }
    ],
)


def test_build_tool_list_length():
    tools = build_tool_list(_CONFIG)
    assert len(tools) == 1


def test_build_tool_list_name_and_description():
    tools = build_tool_list(_CONFIG)
    assert tools[0].name == "list_users"
    assert "List all users" in tools[0].description


def test_build_tool_list_param_in_schema():
    tools = build_tool_list(_CONFIG)
    assert "limit" in tools[0].inputSchema["properties"]


def test_build_tool_list_optional_param_not_in_required():
    tools = build_tool_list(_CONFIG)
    assert "limit" not in tools[0].inputSchema.get("required", [])


def test_create_server_returns_server():
    server = create_server(_CONFIG, {})
    assert server is not None
    assert server.name == "elliot"
