from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class ParameterDefinition(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "date"]
    required: bool = True
    description: str = ""
    default: Optional[Any] = None


class FilterCondition(BaseModel):
    field: str
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "in_list", "contains", "is_null", "is_not_null"]
    value: Optional[Any] = None           # fixed value baked into the tool
    parameter_name: Optional[str] = None  # runtime parameter passed by the agent


class FilterGroup(BaseModel):
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[FilterCondition] = []


class ReturnField(BaseModel):
    field: str
    alias: Optional[str] = None
    aggregation: Literal["none", "count", "sum", "avg", "min", "max"] = "none"


class ApiRequestMapping(BaseModel):
    """
    For REST sources: how tool parameters map into the HTTP request.
    Only used when source.type == 'rest' and category == 'WRITE' or 'ACTION'.
    """
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path_template: Optional[str] = None  # e.g. "/users/{user_id}"
    query_params: list[str] = []
    body_params: list[str] = []
    body_format: Literal["json", "form"] = "json"


class ResponseShape(BaseModel):
    max_rows: int = 1000
    rename: dict[str, str] = {}  # old_name -> new_name in output


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: Literal["READ", "WRITE", "ACTION"]

    # Which sources to pull data from.
    source_ids: list[str]

    # READ tools: Elliot converts these into a safe parameterized SELECT.
    filter_groups: list[FilterGroup] = []
    return_fields: list[ReturnField] = []
    limit: int = 100

    # WRITE / ACTION tools: Elliot maps parameters into the HTTP request.
    api_mapping: Optional[ApiRequestMapping] = None

    parameters: list[ParameterDefinition] = []
    response_shape: ResponseShape = ResponseShape()


class SkillStep(BaseModel):
    alias: str
    tool_id: str
    params: dict[str, Any]  # may contain {{skill.input.X}} or {{steps.Y.Z}}


class SkillDefinition(BaseModel):
    id: str
    name: str
    description: str
    steps: list[SkillStep]
    input_parameters: list[ParameterDefinition] = []


class ToolResult(BaseModel):
    rows: list[dict[str, Any]]
    meta: dict[str, Any]  # row_count, latency_ms, truncated, sources_fetched
