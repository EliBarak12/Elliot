"""Optional OpenTelemetry bridge for Elliot's structlog events.

Converts structured log records that match known Elliot event names into
OpenTelemetry spans so tool call traces appear in any compatible APM backend
(Datadog, Honeycomb, Grafana Tempo, etc.).

Usage — add to logging_config.py or any service entry point:

    from elliot_core.otel_bridge import build_otel_processor
    structlog.configure(processors=[..., build_otel_processor(), ...])

If opentelemetry-sdk is not installed the processor is a transparent no-op,
so this import is always safe regardless of whether OTel is present.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# MCP tool-call span name — aligns with the emerging OTel semantic convention
_SPAN_NAME = "mcp.tool.call"

# Structlog event names that map to a span boundary
_START_EVENTS = {"tool.call.start", "tool.call"}
_END_EVENTS = {"tool.call.complete", "tool.call.error"}


def _noop_processor(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return event_dict


def build_otel_processor() -> Callable[[Any, str, dict[str, Any]], dict[str, Any]]:
    """Return a structlog processor that emits OTel spans for tool call events.

    Falls back to a transparent no-op when opentelemetry-sdk is not installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace import SpanKind, StatusCode
    except ImportError:
        log.debug("otel_bridge.disabled", reason="opentelemetry-sdk not installed")
        return _noop_processor

    tracer = trace.get_tracer("elliot.connector")
    # In-flight spans keyed by tool call correlation id (tool_id + session context)
    _active: dict[str, Any] = {}

    def processor(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event = event_dict.get("event", "")
        tool_name = event_dict.get("tool") or event_dict.get("tool_id", "unknown")
        call_key = f"{tool_name}:{event_dict.get('session_id', '')}"

        if event in _START_EVENTS:
            span = tracer.start_span(
                _SPAN_NAME,
                kind=SpanKind.CLIENT,
                attributes={
                    "tool.name": tool_name,
                    "tool.server": event_dict.get("connector", "elliot"),
                    "tool.category": event_dict.get("category", ""),
                },
            )
            _active[call_key] = (span, time.monotonic())

        elif event in _END_EVENTS:
            entry = _active.pop(call_key, None)
            if entry is not None:
                span, t0 = entry
                duration_ms = round((time.monotonic() - t0) * 1000, 1)
                is_error = event == "tool.call.error"
                span.set_attribute("tool.duration_ms", duration_ms)
                span.set_attribute("tool.is_error", is_error)
                if error_code := event_dict.get("error_code"):
                    span.set_attribute("tool.error_code", error_code)
                if output_tokens := event_dict.get("output_tokens"):
                    span.set_attribute("tool.output_tokens", int(output_tokens))
                if input_tokens := event_dict.get("input_tokens"):
                    span.set_attribute("tool.input_tokens", int(input_tokens))
                if is_error:
                    span.set_status(StatusCode.ERROR, event_dict.get("error", ""))
                else:
                    span.set_status(StatusCode.OK)
                span.end()

        return event_dict

    log.info("otel_bridge.enabled", tracer=_SPAN_NAME)
    return processor
