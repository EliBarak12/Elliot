from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ParameterDefinition(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "date"]
    required: bool = True
    description: str = ""
    default: Any | None = None


class FilterCondition(BaseModel):
    field: str
    operator: Literal[
        "=", "!=", ">", ">=", "<", "<=", "in_list", "contains", "is_null", "is_not_null"
    ]
    value: Any | None = None  # fixed value baked into the tool
    parameter_name: str | None = None  # runtime parameter passed by the agent


class FilterGroup(BaseModel):
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[FilterCondition] = []


class ReturnField(BaseModel):
    field: str
    alias: str | None = None
    aggregation: Literal["none", "count", "sum", "avg", "min", "max"] = "none"


class OrderField(BaseModel):
    field: str
    direction: Literal["ASC", "DESC"] = "ASC"


class ApiRequestMapping(BaseModel):
    """
    For REST sources: how tool parameters map into the HTTP request.
    Used when category == 'WRITE' or 'ACTION'.
    """

    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path_template: str | None = None  # e.g. "/users/{user_id}"
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

    # ── READ / full-fetch mode (DB, file, or small REST) ───────────────────────
    # Elliot fetches all rows, loads into SQLite, runs a generated SELECT.
    filter_groups: list[FilterGroup] = []  # WHERE conditions
    return_fields: list[ReturnField] = []  # SELECT columns (with optional aggregation)
    having: list[FilterGroup] = []  # HAVING conditions (post-aggregation)
    order_by: list[OrderField] = []  # ORDER BY columns
    limit: int = 100

    # ── READ / passthrough mode (large REST APIs with server-side filtering) ────
    # Parameter names listed here are forwarded directly as API query params.
    # The agent controls their values; Elliot does NOT paginate automatically.
    # Any filter_groups still apply as a post-fetch SQL filter on the result.
    #
    # Example: rest_query_params=["q","page","per_page"] with matching parameters
    # lets the agent call: search_products(q="widget", page=2, per_page=10)
    # Elliot sends: GET /products?q=widget&page=2&per_page=10
    rest_query_params: list[str] = []

    # ── WRITE / ACTION tools (REST sources) ───────────────────────────────
    api_mapping: ApiRequestMapping | None = None

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
    meta: dict[str, Any]  # row_count, fetch_mode, truncated, sources_fetched
