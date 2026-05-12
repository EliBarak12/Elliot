from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging(enable_otel: bool | None = None) -> None:
    """Call once at process startup, before creating the FastAPI app.

    enable_otel: wire the OTel bridge if True, skip if False, auto-detect if None.
    Auto-detection enables OTel when the OTEL_EXPORTER_OTLP_ENDPOINT env var is set.
    """
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
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
    )

    # Route stdlib logging (uvicorn, httpx, etc.) through structlog as JSON
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
