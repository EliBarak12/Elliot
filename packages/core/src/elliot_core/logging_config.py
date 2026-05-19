from __future__ import annotations

import logging
import os
import sys
from typing import Any, TextIO

import structlog


def configure_logging(enable_otel: bool | None = None, stream: TextIO | None = None) -> None:
    """Call once at process startup, before creating the FastAPI app.

    enable_otel: wire the OTel bridge if True, skip if False, auto-detect if None.
    Auto-detection enables OTel when the OTEL_EXPORTER_OTLP_ENDPOINT env var is set.

    stream: where log lines are written. Defaults to stderr so stdout stays
    clean — critical for the stdio MCP server, whose stdout carries the
    JSON-RPC protocol stream.
    """
    if stream is None:
        stream = sys.stderr
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    if enable_otel is None:
        enable_otel = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if enable_otel:
        from elliot_core.otel_bridge import build_otel_processor

        processors.append(build_otel_processor())

    processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(stream),
    )

    # Route stdlib logging (uvicorn, httpx, etc.) through structlog as JSON
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=level,
        force=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
