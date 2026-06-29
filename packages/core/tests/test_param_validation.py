"""Tests for shared call-time parameter validation (audit H5/H6)."""

from __future__ import annotations

import pytest

from elliot_core.errors import ElliotError
from elliot_core.tools.param_validation import validate_call_params
from elliot_core.types.tool import ToolDefinition


def _tool(**params: object) -> ToolDefinition:
    return ToolDefinition.model_validate(
        {
            "id": "t",
            "name": "t",
            "description": "a tool for tests",
            "category": "READ",
            "source_ids": ["s"],
            "parameters": list(params.values()),
        }
    )


def test_rejects_unknown_param():
    tool = _tool(a={"name": "status", "type": "string", "required": False})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"staus": "open"})
    assert exc.value.code == "UNKNOWN_PARAM"


def test_enforces_enum():
    tool = _tool(
        a={"name": "group_by", "type": "string", "required": False, "enum": ["city", "region"]}
    )
    assert validate_call_params(tool, {"group_by": "city"})["group_by"] == "city"
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"group_by": "planet"})
    assert exc.value.code == "INVALID_PARAM_VALUE"


def test_object_param_accepts_dict():
    # F7: a dynamic-key map (e.g. cart items {product_id: qty}) is a valid param.
    tool = _tool(a={"name": "items", "type": "object", "required": True})
    out = validate_call_params(tool, {"items": {"123": "2", "456": "1"}})
    assert out["items"] == {"123": "2", "456": "1"}


def test_object_param_parses_json_string():
    tool = _tool(a={"name": "items", "type": "object", "required": True})
    out = validate_call_params(tool, {"items": '{"123": 2}'})
    assert out["items"] == {"123": 2}


def test_object_param_rejects_non_object():
    tool = _tool(a={"name": "items", "type": "object", "required": True})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"items": "not-json"})
    assert exc.value.code == "INVALID_PARAM_TYPE"
    with pytest.raises(ElliotError) as exc2:
        validate_call_params(tool, {"items": 5})
    assert exc2.value.code == "INVALID_PARAM_TYPE"


def test_enforces_declared_maximum():
    tool = _tool(
        a={"name": "limit", "type": "integer", "required": False, "minimum": 1, "maximum": 50}
    )
    assert validate_call_params(tool, {"limit": 25})["limit"] == 25
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"limit": 999})
    assert exc.value.code == "INVALID_PARAM_VALUE"


def test_enforces_declared_minimum():
    tool = _tool(a={"name": "limit", "type": "integer", "required": False, "minimum": 1})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"limit": -1})
    assert exc.value.code == "INVALID_PARAM_VALUE"


def test_passes_through_allowed_passthrough_keys():
    tool = ToolDefinition.model_validate(
        {
            "id": "t",
            "name": "t",
            "description": "a passthrough tool",
            "category": "READ",
            "source_ids": ["s"],
            "rest_query_params": ["q"],
            "parameters": [{"name": "q", "type": "string", "required": True}],
        }
    )
    out = validate_call_params(tool, {"q": "widget"})
    assert out["q"] == "widget"


def test_declared_only_returns_subset():
    tool = ToolDefinition.model_validate(
        {
            "id": "t",
            "name": "t",
            "description": "a passthrough tool",
            "category": "READ",
            "source_ids": ["s"],
            "rest_query_params": ["q"],
            "parameters": [{"name": "q", "type": "string", "required": True}],
        }
    )
    # declared_only mirrors the design-time executor: only declared params, and
    # a rest_query_param that isn't also a declared parameter is excluded.
    out = validate_call_params(tool, {"q": "widget"}, declared_only=True)
    assert out == {"q": "widget"}
