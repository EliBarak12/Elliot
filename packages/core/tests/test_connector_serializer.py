import pytest

from elliot_core.connector.schema_gen import to_mcp_tool_schema, to_openai_function
from elliot_core.connector.serializer import deserialize_connector, serialize_connector
from elliot_core.errors import ElliotError
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ParameterDefinition, ToolDefinition


def _make_config() -> ConnectorConfig:
    return ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[SourceConfig(id="src", name="Source", type="rest", url="https://api.example.com")],
        tools=[
            ToolDefinition(
                id="list_items",
                name="List items",
                description="Return all items",
                category="READ",
                source_ids=["src"],
                parameters=[
                    ParameterDefinition(
                        name="category",
                        type="string",
                        required=False,
                        description="Filter by category",
                    )
                ],
            )
        ],
    )


def test_serialize_roundtrip():
    config = _make_config()
    json_str = serialize_connector(config)
    restored = deserialize_connector(json_str)
    assert restored.name == config.name
    assert len(restored.tools) == 1
    assert restored.tools[0].id == "list_items"


def test_deserialize_invalid_json_raises():
    with pytest.raises(ElliotError) as exc_info:
        deserialize_connector("not valid json")
    assert exc_info.value.code == "INVALID_CONNECTOR"


def test_to_mcp_tool_schema():
    tool = _make_config().tools[0]
    schema = to_mcp_tool_schema(tool)
    assert schema["name"] == "list_items"
    assert "category" in schema["inputSchema"]["properties"]
    assert "category" not in schema["inputSchema"]["required"]


def test_object_param_schema_is_open_object():
    """An object (dynamic-key map) param emits a JSON-Schema object with
    additionalProperties so arbitrary keys (cart items {id: qty}) are valid."""
    tool = ToolDefinition(
        id="write_cart",
        name="Write cart",
        description="Add a map of items to the cart.",
        category="WRITE",
        source_ids=["src"],
        api_mapping={"method": "POST", "path_template": "/cart", "body_params": ["items"]},
        parameters=[
            ParameterDefinition(name="items", type="object", required=True, description="map")
        ],
    )
    schema = to_mcp_tool_schema(tool)
    items = schema["inputSchema"]["properties"]["items"]
    assert items["type"] == "object"
    assert items["additionalProperties"] is True


def test_source_with_headers_and_body_roundtrips():
    """Custom headers, static body and forward_params_in survive serialize →
    deserialize so a body-driven, multi-credential source stays intact."""
    config = ConnectorConfig(
        name="Catalog",
        slug="catalog",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="src",
                name="Source",
                type="rest",
                url="https://api.example.com/catalog",
                method="POST",
                forward_params_in="body",
                headers={"ecomtoken": "{{ env:ECOMTOKEN }}"},
                body={"store": "331"},
            )
        ],
        tools=[],
    )
    restored = deserialize_connector(serialize_connector(config))
    src = restored.sources[0]
    assert src.method == "POST"
    assert src.forward_params_in == "body"
    assert src.headers == {"ecomtoken": "{{ env:ECOMTOKEN }}"}
    assert src.body == {"store": "331"}


def test_to_openai_function_structure():
    tool = _make_config().tools[0]
    fn = to_openai_function(tool)
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "list_items"
    assert "properties" in fn["function"]["parameters"]


def test_to_openai_function_required_params():
    tool = ToolDefinition(
        id="create_item",
        name="Create item",
        description="Create a new item in the catalog",
        category="WRITE",
        source_ids=["src"],
        api_mapping={"method": "POST", "path_template": "/items", "body_params": ["name"]},
        parameters=[
            ParameterDefinition(name="name", type="string", required=True, description="Item name")
        ],
    )
    fn = to_openai_function(tool)
    assert "name" in fn["function"]["parameters"]["required"]


def test_to_openai_function_strict_mode_lists_all_params_required():
    """OpenAI strict mode rejects a schema unless every property is required;
    optional params are expressed as nullable instead."""
    tool = ToolDefinition(
        id="search",
        name="Search",
        description="Search the catalog for items",
        category="READ",
        source_ids=["src"],
        sql="SELECT 1",
        parameters=[
            ParameterDefinition(name="q", type="string", required=True, description="Query"),
            ParameterDefinition(name="limit", type="integer", required=False, description="Limit"),
        ],
    )
    params = to_openai_function(tool)["function"]["parameters"]
    assert set(params["required"]) == {"q", "limit"}
    # The optional param is nullable; the required one is not.
    assert params["properties"]["limit"]["type"] == ["integer", "null"]
    assert params["properties"]["q"]["type"] == "string"
    # strict mode forbids `default`.
    assert "default" not in params["properties"]["limit"]
