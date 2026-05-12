import pytest

from elliot_core.errors import ElliotError
from elliot_core.tools.validator import validate_tool_definition

VALID_READ = {
    "id": "list_products",
    "name": "List products",
    "description": "Return all products from the catalog",
    "category": "READ",
    "source_ids": ["products_api"],
}

VALID_WRITE = {
    "id": "create_order",
    "name": "Create order",
    "description": "Submit a new order to the orders API",
    "category": "WRITE",
    "source_ids": ["orders_api"],
    "api_mapping": {
        "method": "POST",
        "path_template": "/orders",
        "body_params": ["product_id", "quantity"],
    },
    "parameters": [
        {"name": "product_id", "type": "string", "required": True, "description": "Product id"},
        {"name": "quantity", "type": "integer", "required": True, "description": "Quantity"},
    ],
}


def test_valid_read_tool():
    tool = validate_tool_definition(VALID_READ)
    assert tool.id == "list_products"


def test_valid_write_tool():
    tool = validate_tool_definition(VALID_WRITE)
    assert tool.category == "WRITE"


def test_read_without_source_ids_raises():
    data = {**VALID_READ, "source_ids": []}
    with pytest.raises(ElliotError) as exc_info:
        validate_tool_definition(data)
    assert "INVALID_TOOL" in exc_info.value.code


def test_write_without_api_mapping_raises():
    data = {**VALID_WRITE}
    del data["api_mapping"]
    with pytest.raises(ElliotError) as exc_info:
        validate_tool_definition(data)
    assert "INVALID_TOOL" in exc_info.value.code


def test_bad_id_raises():
    with pytest.raises(ElliotError):
        validate_tool_definition({**VALID_READ, "id": "Bad-Id"})


def test_short_description_raises():
    with pytest.raises(ElliotError):
        validate_tool_definition({**VALID_READ, "description": "short"})


def test_undefined_filter_param_raises():
    data = {
        **VALID_READ,
        "filter_groups": [
            {
                "logic": "AND",
                "conditions": [{"field": "category", "operator": "=", "parameter_name": "cat"}],
            }
        ],
    }
    with pytest.raises(ElliotError):
        validate_tool_definition(data)


def test_invalid_pydantic_schema_raises_invalid_tool():
    with pytest.raises(ElliotError) as exc_info:
        validate_tool_definition({"id": "x", "name": "X"})  # missing required fields
    assert exc_info.value.code == "INVALID_TOOL"


def test_generic_id_raises():
    with pytest.raises(ElliotError) as exc_info:
        validate_tool_definition({**VALID_READ, "id": "query"})
    assert exc_info.value.code == "INVALID_TOOL"


def test_invalid_skill_definition_raises():
    from elliot_core.tools.validator import validate_skill_definition

    with pytest.raises(ElliotError) as exc_info:
        validate_skill_definition({"id": "x", "name": "X"})  # missing steps/description
    assert exc_info.value.code == "INVALID_SKILL"
