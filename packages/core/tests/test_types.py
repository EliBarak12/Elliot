"""Smoke tests for core type definitions and ConnectorConfig validator."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from elliot_core.types import (
    ConnectorConfig,
    FilterCondition,
    FilterGroup,
    ParameterDefinition,
    ReturnField,
    SourceConfig,
    ToolDefinition,
)

SIMPLE_SOURCE = {
    "id": "products_api",
    "name": "Products API",
    "type": "rest",
    "url": "https://api.example.com/products",
}

SIMPLE_TOOL = {
    "id": "list_products",
    "name": "List products",
    "description": "Return all products",
    "category": "READ",
    "source_ids": ["products_api"],
}


def test_source_config_minimal():
    s = SourceConfig(**SIMPLE_SOURCE)
    assert s.id == "products_api"
    assert s.pagination.strategy == "none"


def test_tool_definition_defaults():
    t = ToolDefinition(**SIMPLE_TOOL)
    assert t.filter_groups == []
    assert t.return_fields == []
    assert t.limit == 100
    assert t.api_mapping is None


def test_connector_config_valid():
    cfg = ConnectorConfig(
        name="E-commerce",
        slug="ecommerce",
        version="1.0.0",
        sources=[SIMPLE_SOURCE],
        tools=[SIMPLE_TOOL],
    )
    assert len(cfg.tools) == 1


def test_connector_config_rejects_unknown_source():
    with pytest.raises((PydanticValidationError, ValueError)):
        ConnectorConfig(
            name="E-commerce",
            slug="ecommerce",
            version="1.0.0",
            sources=[SIMPLE_SOURCE],
            tools=[
                {
                    **SIMPLE_TOOL,
                    "source_ids": ["does_not_exist"],
                }
            ],
        )


def test_filter_group_roundtrip():
    fg = FilterGroup(
        logic="AND",
        conditions=[FilterCondition(field="category", operator="=", parameter_name="category")],
    )
    data = fg.model_dump()
    restored = FilterGroup.model_validate(data)
    assert restored.conditions[0].field == "category"


def test_parameter_definition_defaults():
    p = ParameterDefinition(name="limit", type="integer")
    assert p.required is True
    assert p.default is None


def test_return_field_aggregation_default():
    rf = ReturnField(field="products_api.price")
    assert rf.aggregation == "none"
    assert rf.alias is None
