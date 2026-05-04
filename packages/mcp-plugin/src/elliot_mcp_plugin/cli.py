from __future__ import annotations

import asyncio
import sys

from elliot_core.logging_config import configure_logging

from .connector_loader import load_connector, load_secrets
from .server import run_stdio


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Elliot MCP Server")
    parser.add_argument("--connector", metavar="PATH", help="Path to connector JSON file")
    args = parser.parse_args()

    configure_logging()

    try:
        config = load_connector(args.connector)
        secrets = load_secrets()
        asyncio.run(run_stdio(config, secrets))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
