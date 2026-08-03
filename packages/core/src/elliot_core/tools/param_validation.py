"""Shared call-time parameter validation and coercion.

One implementation, used by every place a tool's inputs are bound:

  * the design-time preview executor (:mod:`elliot_core.tools.executor`),
  * the MCP-plugin ``elliot_preview_tool`` path,
  * the published connector runtime
    (:mod:`elliot_connector_runtime.executor`).

Centralising it removes the preview/production divergence the audit flagged
(H5): an invalid ``enum`` value or an out-of-range ``limit`` was rejected at
design time but silently accepted by the published runtime. Now both paths
reject unknown params, enforce ``required``, ``enum`` membership, declared
numeric bounds (H6), and type coercion identically.
"""

from __future__ import annotations

import difflib
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.types.tool import ParameterDefinition, ToolDefinition

_TRUE_STRINGS = {"true", "1", "yes", "on"}
_FALSE_STRINGS = {"false", "0", "no", "off"}


def _param_spec(p: ParameterDefinition) -> str:
    """A compact, agent-readable spec for one parameter — everything an agent
    needs to supply the value correctly WITHOUT re-reading ``tools/list``: the
    type, its allowed ``enum`` values, any numeric bounds, and the description.

    This is what turns a bare "parameter missing: 'status'" into an actionable
    error the agent can act on in one shot (principle 3), instead of guessing
    the type or the allowed values and calling again."""
    bits: list[str] = [p.type]
    if p.enum:
        bits.append(f"one of {p.enum}")
    if p.type in ("integer", "number"):
        if p.minimum is not None and p.maximum is not None:
            bits.append(f"between {p.minimum} and {p.maximum}")
        elif p.minimum is not None:
            bits.append(f">= {p.minimum}")
        elif p.maximum is not None:
            bits.append(f"<= {p.maximum}")
    spec = f"(expected {', '.join(bits)})"
    desc = (p.description or "").strip()
    if desc:
        spec += f" — {desc}"
    return spec


def _closest(value: str, candidates: list[str]) -> str | None:
    """The single closest candidate to ``value``, or ``None`` if none is close.

    Turns "unknown parameter 'staus'" into "did you mean 'status'?" and
    "must be one of [...]" into a specific fix — so an agent that typo'd,
    pluralised, or mis-cased a name or enum value corrects it in one shot
    instead of re-scanning the list. A case-insensitive exact hit wins (the
    most common near-miss: 'Open' for 'open'); otherwise fall back to fuzzy
    ratio matching."""
    lower_map = {c.lower(): c for c in candidates}
    ci = lower_map.get(value.lower())
    if ci is not None and ci != value:
        return ci
    match = difflib.get_close_matches(value, candidates, n=1, cutoff=0.6)
    return match[0] if match else None


def allowed_param_names(tool: ToolDefinition) -> set[str]:
    """Every key a tool legitimately accepts at call time.

    Spans declared ``parameters``, passthrough ``rest_query_params`` and the
    WRITE/ACTION ``api_mapping`` query/body params — the three places a value
    can be consumed.
    """
    allowed = {p.name for p in tool.parameters}
    allowed.update(tool.rest_query_params)
    if tool.api_mapping is not None:
        allowed.update(tool.api_mapping.query_params)
        allowed.update(tool.api_mapping.body_params)
    return allowed


def coerce_value(val: Any, typ: str) -> Any:
    """Coerce ``val`` to the declared parameter ``type`` or raise ElliotError."""
    if typ == "integer":
        try:
            return int(val)
        except (ValueError, TypeError) as exc:
            raise ElliotError("INVALID_PARAM_TYPE", f"Expected integer, got: {val!r}") from exc
    if typ == "number":
        try:
            return float(val)
        except (ValueError, TypeError) as exc:
            raise ElliotError("INVALID_PARAM_TYPE", f"Expected number, got: {val!r}") from exc
    if typ == "boolean":
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            low = val.strip().lower()
            if low in _TRUE_STRINGS:
                return True
            if low in _FALSE_STRINGS:
                return False
            raise ElliotError("INVALID_PARAM_TYPE", f"Expected boolean, got: {val!r}")
        if isinstance(val, (int, float)):
            return bool(val)
        raise ElliotError("INVALID_PARAM_TYPE", f"Expected boolean, got: {val!r}")
    if typ == "object":
        # A dynamic-key map (e.g. cart items {product_id: qty}). Accept a dict
        # as-is, or a JSON object string and parse it. Anything else is an error
        # so a wrong type doesn't silently serialize into the request body.
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            import json

            try:
                parsed = json.loads(val)
            except (ValueError, TypeError) as exc:
                raise ElliotError(
                    "INVALID_PARAM_TYPE", f"Expected a JSON object, got: {val!r}"
                ) from exc
            if isinstance(parsed, dict):
                return parsed
        raise ElliotError("INVALID_PARAM_TYPE", f"Expected object (map), got: {val!r}")
    if typ == "array":
        # A JSON list (e.g. a bulk-create's items). Accept a list as-is, or a
        # JSON array string and parse it — clients that can only send strings
        # (e.g. OpenAI strict function calling) still work. Anything else is an
        # error so a wrong type doesn't silently serialize into the body.
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            import json

            try:
                parsed = json.loads(val)
            except (ValueError, TypeError) as exc:
                raise ElliotError(
                    "INVALID_PARAM_TYPE", f"Expected a JSON array, got: {val!r}"
                ) from exc
            if isinstance(parsed, list):
                return parsed
        raise ElliotError("INVALID_PARAM_TYPE", f"Expected array (list), got: {val!r}")
    if typ in ("string", "date"):
        # Reject silent int→str coercion: previously `country_summary({"iso": 99})`
        # turned 99 into "99", bound it to a string SQL param, matched nothing,
        # and returned 200 + empty rows. An agent passing the wrong type should
        # get an actionable error, not a misleading empty result. (bool is an
        # int subclass, so it's caught here too.)
        if not isinstance(val, str):
            raise ElliotError(
                "INVALID_PARAM_TYPE",
                f"Expected string, got {type(val).__name__}: {val!r}",
            )
        return val
    return str(val)


def _check_bounds(param_name: str, value: Any, minimum: int | None, maximum: int | None) -> None:
    """Enforce a numeric parameter's declared ``minimum`` / ``maximum``.

    This is what makes a documented per-tool cap real (audit H6): a tool can
    declare ``limit`` with ``maximum: 50`` and the platform rejects ``999`` or
    ``-1`` at the validation boundary, instead of relying on the author
    hand-writing ``LIMIT MAX(MIN(:limit, 50), 1)`` in every query.
    """
    if minimum is not None and value < minimum:
        raise ElliotError(
            "INVALID_PARAM_VALUE",
            f"Parameter '{param_name}' must be >= {minimum}, got: {value!r}",
        )
    if maximum is not None and value > maximum:
        raise ElliotError(
            "INVALID_PARAM_VALUE",
            f"Parameter '{param_name}' must be <= {maximum}, got: {value!r}",
        )


def validate_call_params(
    tool: ToolDefinition,
    params: dict[str, Any],
    *,
    declared_only: bool = False,
) -> dict[str, Any]:
    """Validate and coerce ``params`` against ``tool``'s declared inputs.

    Rejects unknown keys, missing required params, invalid ``enum`` values,
    out-of-range numeric bounds, and uncoercible types — raising
    :class:`ElliotError` with an actionable code in every case.

    Returns a dict with declared parameters coerced and defaults applied.
    ``declared_only=True`` returns ONLY the declared ``parameters`` (the shape
    the design-time executor binds to SQL); otherwise the returned dict is a
    superset that also carries through allowed passthrough / api_mapping keys
    so the runtime can forward them.
    """
    allowed = allowed_param_names(tool)
    unknown = sorted(k for k in params if k not in allowed)
    if unknown:
        allowed_sorted = sorted(allowed)
        # Point each typo'd / pluralised / mis-cased key at its closest real name
        # so the agent fixes it in one shot instead of re-scanning the whole
        # expected list.
        near = {k: m for k in unknown if (m := _closest(k, allowed_sorted))}
        hint = ""
        if near:
            pairs = ", ".join(f"'{k}' → '{v}'" for k, v in near.items())
            hint = f" Did you mean: {pairs}?"
        raise ElliotError(
            "UNKNOWN_PARAM",
            f"Unknown parameter(s) for tool '{tool.id}': {', '.join(unknown)}. "
            f"Expected: {', '.join(allowed_sorted) or '(none)'}.{hint}",
            detail={
                "tool_id": tool.id,
                "unknown": unknown,
                "allowed": allowed_sorted,
                "suggestions": near,
            },
        )

    declared: dict[str, Any] = {}
    for p in tool.parameters:
        val = params.get(p.name, p.default)
        if val is None and p.required:
            # Name the type, allowed values, bounds, and meaning — so the agent
            # supplies the right value on the retry instead of guessing.
            raise ElliotError(
                "MISSING_PARAM",
                f"Required parameter missing: '{p.name}' {_param_spec(p)}",
                detail={
                    "tool_id": tool.id,
                    "param": p.name,
                    "type": p.type,
                    "enum": p.enum,
                    "minimum": p.minimum,
                    "maximum": p.maximum,
                },
            )
        if val is not None:
            try:
                coerced = coerce_value(val, p.type)
            except ElliotError as exc:
                # Attribute the type error to THIS parameter: "Expected integer,
                # got 'abc'" alone doesn't say which one when a tool has several
                # params of the same type.
                raise ElliotError(
                    exc.code,
                    f"Parameter '{p.name}': {exc.message}",
                    detail={"tool_id": tool.id, "param": p.name, "type": p.type},
                ) from exc
            if p.enum is not None and str(coerced) not in p.enum:
                # A case/spelling near-miss ('Open' for 'open', 'cancelled' for
                # 'canceled') is the common enum failure — name the exact value.
                suggestion = _closest(str(coerced), [str(e) for e in p.enum])
                hint = f" Did you mean '{suggestion}'?" if suggestion else ""
                raise ElliotError(
                    "INVALID_PARAM_VALUE",
                    f"Parameter '{p.name}' must be one of {p.enum}, got: {coerced!r}.{hint}",
                    detail={
                        "tool_id": tool.id,
                        "param": p.name,
                        "enum": p.enum,
                        "suggestion": suggestion,
                    },
                )
            if p.type in ("integer", "number"):
                _check_bounds(p.name, coerced, p.minimum, p.maximum)
            declared[p.name] = coerced

    if declared_only:
        return declared
    out = dict(params)
    out.update(declared)
    return out
