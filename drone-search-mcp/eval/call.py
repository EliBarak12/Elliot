"""Call one tool on a running drone-search MCP server (HTTP transport) and print the result.

    python -m server --allow-actuation --transport http &      # long-lived server
    python eval/call.py get_status
    python eval/call.py plan_search '{"center_lat": 47.3977, "center_lon": 8.5456, "radius_m": 40}'

Images in the result are saved next to --img-dir and their paths printed, so a human (or
an agent driving this from a shell) can look at them. Used for hands-on sessions where the
MCP tools cannot be loaded into the client directly.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from fastmcp import Client


async def run(url: str, tool: str, args: dict[str, object], img_dir: Path) -> int:
    async with Client(url, timeout=3600) as c:
        t0 = time.time()
        r = await c.call_tool(tool, args, raise_on_error=False)
        img_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        for i, x in enumerate(r.content):
            if x.type == "text":
                print(x.text)
            elif x.type == "image":
                p = img_dir / f"{stamp}_{tool}_{i}.jpg"
                p.write_bytes(base64.b64decode(x.data))
                print(f"[image saved: {p}]")
        print(f"[{tool} took {time.time() - t0:.1f}s]", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("tool")
    p.add_argument("args", nargs="?", default="{}")
    p.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    p.add_argument("--img-dir", type=Path, default=Path("output/agent_images"))
    a = p.parse_args()
    return asyncio.run(run(a.url, a.tool, json.loads(a.args), a.img_dir))


if __name__ == "__main__":
    sys.exit(main())
