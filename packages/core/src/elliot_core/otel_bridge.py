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

import threading
import time
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Span name + attributes follow the OpenTelemetry GenAI semantic conventions
# for tool execution (gen_ai.operation.name = "execute_tool").
_OPERATION = "execute_tool"

# Structlog event names that map to a span boundary
_START_EVENTS = {"tool.call.start", "tool.call"}
_END_EVENTS = {"tool.call.complete", "tool.call.error"}

# An in-flight span whose end event never arrives is swept after this many
# seconds so a dropped event can't leak the span (and exporter memory).
_ORPHAN_TTL_S = 300.0


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
    # In-flight spans keyed by call correlation id. Guarded by a lock because a
    # structlog processor can run on any thread (FastMCP threadpool, asyncio
    # executors). Each value is (span, monotonic_start, wall_start).
    _active: dict[str, Any] = {}
    _lock = threading.Lock()

    def _sweep_orphans(now: float) -> None:
        """End spans whose matching end event never arrived (caller holds lock)."""
        stale = [k for k, (_, _, wall) in _active.items() if now - wall > _ORPHAN_TTL_S]
        for key in stale:
            span, _, _ = _active.pop(key)
            span.set_status(StatusCode.ERROR, "tool call span orphaned (no end event)")
            span.end()

    def processor(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event = event_dict.get("event", "")
        tool_name = event_dict.get("tool") or event_dict.get("tool_id", "unknown")
        call_key = f"{tool_name}:{event_dict.get('session_id', '')}"

        if event in _START_EVENTS:
            span = tracer.start_span(
                f"{_OPERATION} {tool_name}",
                kind=SpanKind.CLIENT,
                attributes={
                    "gen_ai.operation.name": _OPERATION,
                    "gen_ai.tool.name": tool_name,
                    "gen_ai.tool.type": event_dict.get("category", ""),
                    "gen_ai.system": event_dict.get("connector", "elliot"),
                },
            )
            now = time.monotonic()
            with _lock:
                _sweep_orphans(time.time())
                _active[call_key] = (span, now, time.time())

        elif event in _END_EVENTS:
            with _lock:
                entry = _active.pop(call_key, None)
            if entry is not None:
                span, t0, _ = entry
                duration_ms = round((time.monotonic() - t0) * 1000, 1)
                is_error = event == "tool.call.error"
                span.set_attribute("gen_ai.tool.duration_ms", duration_ms)
                if error_code := event_dict.get("error_code"):
                    span.set_attribute("error.type", str(error_code))
                if output_tokens := event_dict.get("output_tokens"):
                    span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
                if input_tokens := event_dict.get("input_tokens"):
                    span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
                if is_error:
                    span.set_status(StatusCode.ERROR, event_dict.get("error", ""))
                else:
                    span.set_status(StatusCode.OK)
                span.end()

        return event_dict

    log.info("otel_bridge.enabled", operation=_OPERATION)
    return processor
