from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

# Connector-authored models reject unknown fields so a typo in a saved
# connector JSON (e.g. "max_row" for "max_rows") surfaces as a validation
# error instead of being silently dropped.
_strict = ConfigDict(extra="forbid")


class ParameterDefinition(BaseModel):
    model_config = _strict

    name: str
    type: Literal["string", "integer", "number", "boolean", "date"]
    required: bool = True
    description: str = ""
    default: Any | None = None
    enum: list[str] | None = None


class FilterCondition(BaseModel):
    model_config = _strict

    field: str
    operator: Literal[
        "=", "!=", ">", ">=", "<", "<=", "in_list", "contains", "is_null", "is_not_null"
    ]
    value: Any | None = None  # fixed value baked into the tool
    parameter_name: str | None = None  # runtime parameter passed by the agent


class FilterGroup(BaseModel):
    model_config = _strict

    logic: Literal["AND", "OR"] = "AND"
    conditions: list[FilterCondition] = []


class ReturnField(BaseModel):
    model_config = _strict

    field: str
    alias: str | None = None
    aggregation: Literal["none", "count", "sum", "avg", "min", "max"] = "none"


class OrderField(BaseModel):
    model_config = _strict

    field: str
    direction: Literal["ASC", "DESC"] = "ASC"


class ApiRequestMapping(BaseModel):
    """
    For REST sources: how tool parameters map into the HTTP request.
    Used when category == 'WRITE' or 'ACTION'.
    """

    model_config = _strict

    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path_template: str | None = None  # e.g. "/users/{user_id}"
    query_params: list[str] = []
    body_params: list[str] = []
    body_format: Literal["json", "form"] = "json"


class ResponseShape(BaseModel):
    model_config = _strict

    max_rows: int = 1000
    rename: dict[str, str] = {}  # old_name -> new_name in output


class QueryResult(BaseModel):
    rows: list[dict[str, Any]]
    tool_id: str
    # True when the executor truncated the result at ELLIOT_MAX_RESULT_ROWS;
    # callers surface this to the agent so it knows the set is incomplete.
    truncated: bool = False
    # True row count before truncation (None when not truncated). Lets callers
    # tell the agent "returned X of Y" so the truncation marker is actionable.
    total_rows: int | None = None
    # Why the set is incomplete, so callers can give the right recovery advice:
    #   "result_cap" — this query matched more rows than the cap; narrowing the
    #                  request will return a complete, context-sized set.
    #   "source_cap" — the upstream snapshot itself was capped before the query
    #                  ran, so rows may be missing that no client-side filter can
    #                  recover; the source needs upstream filtering/pagination.
    #   "token_budget" — the rows fit the row cap but their serialized size
    #                  exceeded the per-call token budget (a few fat rows can
    #                  blow a context window), so fewer rows were returned;
    #                  select fewer fields or narrow the request.
    truncation_reason: Literal["result_cap", "source_cap", "token_budget"] | None = None


class ToolDefinition(BaseModel):
    model_config = _strict

    id: str
    name: str
    description: str
    category: Literal["READ", "WRITE", "ACTION"]

    # Which sources to pull data from.
    source_ids: list[str] = []

    # Raw SQL query — when set, executor runs this directly against ingested source data.
    sql: str | None = None

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
    output_schema: dict[str, Any] | None = None
    run_async: bool = False


class SkillStep(BaseModel):
    model_config = _strict

    alias: str
    tool_id: str
    params: dict[str, Any]  # may contain {{skill.input.X}} or {{steps.Y.Z}}


class SkillDefinition(BaseModel):
    """A connector workflow.

    A skill is the connector author's answer to "how should an agent use my
    tools to get a job done?" — the same role Elliot's own ``SKILL.md`` files
    play for Elliot-the-plugin. It comes in two flavours, and a single skill
    may be both:

    - **Deterministic** — a ``steps`` chain the runtime can execute end-to-end
      (look up the customer, then summarise their orders). Exposed as one MCP
      call so the agent doesn't orchestrate the chain itself.
    - **Prose** — free-form ``instructions`` (markdown) plus ``when_to_use``,
      describing a workflow the agent drives itself (including branches the
      runtime can't express as a flat chain). Exported verbatim as a
      ``SKILL.md`` guide alongside the connector's tools.

    A skill must carry at least one of ``steps`` or ``instructions``; an empty
    skill is a no-op and is rejected.
    """

    model_config = _strict

    id: str
    name: str
    description: str
    # Optional now that a skill can be pure prose. A prose-only skill leaves
    # this empty and lives entirely in `instructions`.
    steps: list[SkillStep] = []
    input_parameters: list[ParameterDefinition] = []
    # Free-form, agent-facing guidance. When set, it is the body of the
    # exported SKILL.md — the author describes the workflow in their own words
    # instead of (or in addition to) a deterministic step chain.
    instructions: str = ""
    # The trigger line for the exported SKILL.md frontmatter: when an agent
    # should reach for this skill. Empty falls back to an auto-generated line.
    when_to_use: str = ""

    @model_validator(mode="after")
    def _require_steps_or_instructions(self) -> SkillDefinition:
        if not self.steps and not self.instructions.strip():
            raise ValueError(
                f"Skill '{self.id}' must define at least one step or non-empty "
                "instructions — an empty skill does nothing."
            )
        return self


class ToolResult(BaseModel):
    rows: list[dict[str, Any]]
    meta: dict[str, Any]  # row_count, fetch_mode, truncated, sources_fetched
