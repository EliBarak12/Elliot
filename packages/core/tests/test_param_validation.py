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


def test_unknown_param_suggests_closest_name():
    # A typo'd key is pointed at its real name so the agent fixes it in one shot.
    tool = _tool(a={"name": "status", "type": "string", "required": False})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"staus": "open"})
    assert "did you mean" in exc.value.message.lower()
    assert "'status'" in exc.value.message
    assert exc.value.detail["suggestions"] == {"staus": "status"}


def test_unknown_param_no_suggestion_when_nothing_close():
    # A wholly unrelated key gets the expected list, no misleading suggestion.
    tool = _tool(a={"name": "status", "type": "string", "required": False})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"xyzzy": "1"})
    assert exc.value.code == "UNKNOWN_PARAM"
    assert exc.value.detail["suggestions"] == {}
    assert "did you mean" not in exc.value.message.lower()


def test_invalid_enum_suggests_case_corrected_value():
    tool = _tool(
        a={"name": "status", "type": "string", "required": False, "enum": ["open", "closed"]}
    )
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"status": "Open"})
    assert exc.value.code == "INVALID_PARAM_VALUE"
    assert "did you mean 'open'" in exc.value.message.lower()
    assert exc.value.detail["suggestion"] == "open"


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


def test_missing_param_names_type_enum_and_description():
    # An agent that omits a required param must learn what to supply — type,
    # allowed values, and meaning — not just the name.
    tool = _tool(
        a={
            "name": "status",
            "type": "string",
            "required": True,
            "enum": ["open", "closed"],
            "description": "Filter tickets by their state.",
        }
    )
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {})
    assert exc.value.code == "MISSING_PARAM"
    msg = exc.value.message
    assert "status" in msg
    assert "string" in msg
    assert "open" in msg and "closed" in msg
    assert "Filter tickets by their state." in msg
    assert exc.value.detail["enum"] == ["open", "closed"]


def test_missing_required_integer_names_its_bounds():
    tool = _tool(
        a={"name": "limit", "type": "integer", "required": True, "minimum": 1, "maximum": 50}
    )
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {})
    assert exc.value.code == "MISSING_PARAM"
    assert "between 1 and 50" in exc.value.message


def test_type_error_names_the_offending_parameter():
    # Two integer params: a bad value must say WHICH one, not a bare
    # "expected integer, got 'abc'".
    tool = _tool(
        a={"name": "page", "type": "integer", "required": False},
        b={"name": "limit", "type": "integer", "required": False},
    )
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"limit": "abc"})
    assert exc.value.code == "INVALID_PARAM_TYPE"
    assert "limit" in exc.value.message
    assert exc.value.detail["param"] == "limit"


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


def test_array_param_accepts_list():
    # A bulk-create's item list is a valid param (routed into a JSON body).
    tool = _tool(a={"name": "items", "type": "array", "required": True})
    out = validate_call_params(tool, {"items": [{"username": "a"}, {"username": "b"}]})
    assert out["items"] == [{"username": "a"}, {"username": "b"}]


def test_array_param_parses_json_string():
    # Clients limited to string args (e.g. OpenAI strict mode) still work.
    tool = _tool(a={"name": "items", "type": "array", "required": True})
    out = validate_call_params(tool, {"items": "[1, 2, 3]"})
    assert out["items"] == [1, 2, 3]


def test_array_param_rejects_non_array():
    tool = _tool(a={"name": "items", "type": "array", "required": True})
    with pytest.raises(ElliotError) as exc:
        validate_call_params(tool, {"items": '{"not": "a list"}'})
    assert exc.value.code == "INVALID_PARAM_TYPE"
    with pytest.raises(ElliotError) as exc2:
        validate_call_params(tool, {"items": 5})
    assert exc2.value.code == "INVALID_PARAM_TYPE"
