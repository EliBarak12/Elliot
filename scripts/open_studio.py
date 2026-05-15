#!/usr/bin/env python3
"""Open the Elliot Studio in the user's browser once it's reachable.

When `make dev` boots the Elliot stack, Studio (port 5173) takes a few seconds
to be ready. This script polls Studio's HTTP endpoint and opens the user's
default browser as soon as it responds. After that, it exits — it never blocks
honcho or any other parent process.

Disabled by:
  - `ELLIOT_OPEN_BROWSER=0` (or "false", "no")
  - Linux with no $DISPLAY (headless CI, Docker without X)
  - `STUDIO_URL` unreachable after the timeout (silent give-up; never errors)
"""

from __future__ import annotations

import logging
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser

logging.basicConfig(level=logging.INFO, format="[open_studio] %(message)s")
log = logging.getLogger("open_studio")

STUDIO_URL = os.environ.get("ELLIOT_STUDIO_URL", "http://localhost:5173")
POLL_TIMEOUT_S = float(os.environ.get("ELLIOT_BROWSER_TIMEOUT", "60"))
POLL_INTERVAL_S = float(os.environ.get("ELLIOT_BROWSER_POLL_INTERVAL", "1.0"))

_TRUTHY_OFF = {"0", "false", "no", "off"}


def is_enabled() -> bool:
    raw = os.environ.get("ELLIOT_OPEN_BROWSER", "1").strip().lower()
    if raw in _TRUTHY_OFF:
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        # Headless Linux — opening the browser would either fail or block.
        return False
    return True


def studio_is_up(url: str) -> bool:
    try:
        # SSRF-safe: URL is operator-supplied (ELLIOT_STUDIO_URL env or the
        # localhost default). Studio is the user's own dev server.
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            return resp.status < 500
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def wait_for_studio(url: str, timeout_s: float, interval_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if studio_is_up(url):
            return True
        time.sleep(interval_s)
    return False


def main() -> int:
    if not is_enabled():
        log.info("disabled (ELLIOT_OPEN_BROWSER=0 or headless)")
        return 0

    log.info("waiting for Studio at %s ...", STUDIO_URL)
    if not wait_for_studio(STUDIO_URL, POLL_TIMEOUT_S, POLL_INTERVAL_S):
        log.info("Studio did not come up within %.0fs — skipping browser open", POLL_TIMEOUT_S)
        return 0

    log.info("Studio is up — opening browser at %s", STUDIO_URL)
    try:
        webbrowser.open(STUDIO_URL, new=2, autoraise=True)
    except webbrowser.Error as exc:
        log.info("could not open browser: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
