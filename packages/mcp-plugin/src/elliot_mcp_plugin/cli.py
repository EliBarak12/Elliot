from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import structlog

from elliot_core.logging_config import configure_logging

from .connector_loader import load_connector, load_secrets
from .server import run_stdio

log = structlog.get_logger(__name__)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Elliot MCP Server")
    parser.add_argument("--connector", metavar="PATH", help="Path to connector JSON file")
    args = parser.parse_args()

    configure_logging()

    try:
        config = load_connector(args.connector)
        secrets = load_secrets()
        connector_dir = Path(args.connector).resolve().parent if args.connector else None
        asyncio.run(run_stdio(config, secrets, connector_dir=connector_dir))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        # CLAUDE.md: never `print()`; everything goes through structlog so
        # downstream log processors can capture both message and structured
        # context (exc_info adds the stack trace for diagnostic visibility).
        log.error("cli.fatal", error=str(exc), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
