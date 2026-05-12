"""Tests for elliot_core.otel_bridge."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(event: str, **extra: Any) -> dict[str, Any]:
    return {"event": event, "tool_id": "search_users", "session_id": "sess1", **extra}


def _build_mock_otel() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a minimal OTel SDK mock and return (mock_otel_pkg, mock_trace, mock_tracer, mock_span)."""
    mock_span = MagicMock()
    mock_tracer = MagicMock()
    mock_tracer.start_span.return_value = mock_span

    mock_trace = MagicMock()
    mock_trace.get_tracer.return_value = mock_tracer
    mock_trace.SpanKind = MagicMock(CLIENT=0)
    mock_trace.StatusCode = MagicMock(OK="OK", ERROR="ERROR")

    mock_otel_pkg = MagicMock()
    mock_otel_pkg.trace = mock_trace

    return mock_otel_pkg, mock_trace, mock_tracer, mock_span


# ---------------------------------------------------------------------------
# No-op path (OTel not installed)
# ---------------------------------------------------------------------------


def test_noop_processor_passthrough():
    from elliot_core.otel_bridge import _noop_processor

    d = {"event": "tool.call.start", "tool_id": "x"}
    assert _noop_processor(None, "info", d) is d


def test_build_otel_processor_returns_noop_when_otel_missing():
    """When opentelemetry is not importable, processor is transparent."""
    mods = {k: v for k, v in sys.modules.items()}
    mods.pop("opentelemetry", None)
    mods.pop("opentelemetry.trace", None)
    # Simulate ImportError by patching the import inside the function
    from elliot_core.otel_bridge import _noop_processor

    with (
        patch("builtins.__import__", side_effect=ImportError)
        if False
        else patch(
            "elliot_core.otel_bridge.build_otel_processor",
            wraps=lambda: _noop_processor,
        )
    ):
        pass  # just confirm _noop_processor is importable

    # Real test: if otel raises ImportError the noop is returned
    import elliot_core.otel_bridge as bridge_mod

    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[attr-defined]

    def _block_otel(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in ("opentelemetry", "opentelemetry.trace"):
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_block_otel):
        proc = bridge_mod.build_otel_processor()

    event = _make_event("tool.call.start")
    assert proc(None, "info", event) is event


# ---------------------------------------------------------------------------
# OTel present path
# ---------------------------------------------------------------------------


def test_processor_starts_span_on_start_event():
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", _make_event("tool.call.start", connector="my-connector", category="READ"))
    mock_tracer.start_span.assert_called_once()
    assert mock_tracer.start_span.call_args[0][0] == "mcp.tool.call"


def test_processor_ends_span_on_complete_event():
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", _make_event("tool.call.start"))
    proc(None, "info", _make_event("tool.call.complete", output_tokens=120, input_tokens=40))

    mock_span.end.assert_called_once()
    mock_span.set_attribute.assert_any_call("tool.output_tokens", 120)
    mock_span.set_attribute.assert_any_call("tool.input_tokens", 40)
    mock_span.set_attribute.assert_any_call("tool.is_error", False)


def test_processor_ends_span_with_error():
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", _make_event("tool.call.start"))
    proc(
        None, "warning", _make_event("tool.call.error", error="timeout", error_code="EXEC_TIMEOUT")
    )

    mock_span.end.assert_called_once()
    mock_span.set_attribute.assert_any_call("tool.is_error", True)
    mock_span.set_attribute.assert_any_call("tool.error_code", "EXEC_TIMEOUT")


def test_processor_end_without_start_is_noop():
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", _make_event("tool.call.complete"))
    mock_span.end.assert_not_called()


def test_processor_ignores_unrelated_events():
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", _make_event("connector.loaded"))
    proc(None, "info", _make_event("session.opened"))
    mock_tracer.start_span.assert_not_called()
    mock_span.end.assert_not_called()


def test_processor_uses_tool_name_fallback():
    """tool_id absent — falls back to 'unknown'."""
    mock_otel_pkg, mock_trace, mock_tracer, mock_span = _build_mock_otel()

    with patch.dict(
        sys.modules, {"opentelemetry": mock_otel_pkg, "opentelemetry.trace": mock_trace}
    ):
        import elliot_core.otel_bridge as bridge_mod

        proc = bridge_mod.build_otel_processor()

    proc(None, "info", {"event": "tool.call.start", "session_id": "s1"})
    mock_tracer.start_span.assert_called_once()


# ---------------------------------------------------------------------------
# logging_config integration
# ---------------------------------------------------------------------------


def test_configure_logging_enable_otel_false():
    from elliot_core.logging_config import configure_logging

    configure_logging(enable_otel=False)  # must not raise


def test_configure_logging_auto_detects_endpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    from importlib import reload

    import elliot_core.logging_config as lc

    reload(lc)
    # No-op bridge because opentelemetry-sdk absent — must not raise
    lc.configure_logging()
