"""Boot the full Elliot stack in an isolated workspace for end-to-end tests.

The stack is the same triple a real user runs via ``make dev``:

* ``elliot-mcp-plugin`` on :3000  — the MCP HTTP server agents connect to.
* ``elliot-connector-runtime`` on :3001  — connector executor + session log.
* ``elliot-studio`` on :5173  — React UI Playwright drives.

Each test gets a fresh temporary workspace (``ELLIOT_WORKSPACE``) and a
fresh session/observation DB so runs don't leak state between layers.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PLUGIN_PORT = 3000
DEFAULT_RUNTIME_PORT = 3001
DEFAULT_STUDIO_PORT = 5173

READY_TIMEOUT = 90  # seconds — studio Vite cold-start can be slow on first run


@dataclass(frozen=True)
class StackEndpoints:
    """URLs the test layers point their clients at."""

    plugin_url: str
    plugin_mcp_url: str
    runtime_url: str
    studio_url: str
    workspace: Path
    log_dir: Path


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_http_ok(url: str, timeout: float, name: str) -> None:
    """Poll ``url`` until it answers 2xx or the deadline passes."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(0.5)
    raise RuntimeError(f"{name} did not become ready at {url} within {timeout}s: {last_exc}")


def _wait_mcp_ready(plugin_mcp_url: str, timeout: float) -> None:
    """The MCP endpoint requires POST + initialize; just check the port is bound."""
    deadline = time.monotonic() + timeout
    host = "127.0.0.1"
    port = int(plugin_mcp_url.split(":")[2].split("/")[0])
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"plugin MCP port {port} never opened within {timeout}s")


@contextmanager
def elliot_stack(
    *,
    plugin_port: int = DEFAULT_PLUGIN_PORT,
    runtime_port: int = DEFAULT_RUNTIME_PORT,
    studio_port: int = DEFAULT_STUDIO_PORT,
    skip_studio: bool = False,
    skip_runtime: bool = True,
    extra_env: dict[str, str] | None = None,
) -> Iterator[StackEndpoints]:
    """Yield a running Elliot stack scoped to a temp workspace.

    Plugin (always) and optionally studio are launched directly via uvicorn /
    pnpm. The runtime is skipped by default because the canonical "build a
    connector" flow spawns it through ``elliot_start_runtime`` — booting it
    eagerly would port-collide with that call. Set ``skip_runtime=False`` to
    boot it ahead of time (Procfile-style) when a test relies on the
    runtime being live before the agent runs.
    """
    workspace = Path(
        subprocess.check_output(["mktemp", "-d", "-t", "elliot-e2e-XXXX"]).decode().strip()
    )
    (workspace / ".elliot").mkdir(parents=True, exist_ok=True)
    (workspace / "connectors").mkdir(parents=True, exist_ok=True)
    log_dir = workspace / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Sanity: clean ports — refuse to boot on top of a stale dev server.
    ports_to_check: list[tuple[int, str]] = [(plugin_port, "plugin")]
    if not skip_runtime:
        ports_to_check.append((runtime_port, "runtime"))
    if not skip_studio:
        ports_to_check.append((studio_port, "studio"))
    for port, name in ports_to_check:
        if not _port_free(port):
            shutil.rmtree(workspace, ignore_errors=True)
            raise RuntimeError(
                f"port {port} ({name}) is in use — stop the dev server before running e2e"
            )

    env = {**os.environ}
    env.update(
        {
            "ELLIOT_WORKSPACE": str(workspace),
            "ELLIOT_CONNECTORS_DIR": str(workspace / "connectors"),
            "ELLIOT_SESSIONS_LOG": str(workspace / ".elliot" / "sessions.ndjson"),
            "ELLIOT_AUDIT_LOG": str(workspace / ".elliot" / "audit.ndjson"),
            "ELLIOT_DB_URL": f"sqlite:///{workspace}/.elliot/observations.db",
            # Plugin CORS check is exact-match — must match the URL Playwright
            # navigates to (host + port). We use 127.0.0.1 throughout so both
            # the allow-origin and the Origin: header are identical.
            "ELLIOT_STUDIO_ORIGIN": f"http://127.0.0.1:{studio_port}",
            # No auth in e2e — services log a warning but accept anything.
            "ELLIOT_API_KEY": "",
            "VITE_API_KEY": "",
            "VITE_PLUGIN_URL": f"http://localhost:{plugin_port}",
            "VITE_RUNTIME_URL": f"http://localhost:{runtime_port}",
            # The four mock APIs live on 127.0.0.1; without this the SSRF
            # guard (validate_url in elliot_core.http) rejects every
            # discover-source call. Production deployments leave this off.
            "ELLIOT_SSRF_ALLOW_PRIVATE": "1",
            # Keep eval suites + results inside the workspace so tests don't
            # leak files into the repo's .elliot/ directory.
            "ELLIOT_EVAL_DIR": str(workspace / ".elliot" / "eval"),
            "ELLIOT_EVAL_RESULTS_DIR": str(workspace / ".elliot" / "eval-results"),
            # Allow the agent / test to ship connectors anywhere under the
            # workspace — the default lockdown only allows ELLIOT_CONNECTORS_DIR
            # which is fine for production but awkward here.
            "ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH": "1",
            # Bearer-token secret used by the mock /reviews API. The connector
            # config references it as ``{{ env:REVIEWS_TOKEN }}`` (or
            # ``secret_key: "REVIEWS_TOKEN"`` resolved from ELLIOT_SECRET_*).
            "REVIEWS_TOKEN": "e2e-reviews-secret-001",
            "ELLIOT_SECRET_REVIEWS_TOKEN": "e2e-reviews-secret-001",
            "ELLIOT_E2E_REVIEWS_TOKEN": "e2e-reviews-secret-001",
        }
    )
    if extra_env:
        env.update(extra_env)

    plugin_log = (log_dir / "plugin.log").open("wb")
    runtime_log = (log_dir / "runtime.log").open("wb") if not skip_runtime else None
    studio_log = (log_dir / "studio.log").open("wb") if not skip_studio else None

    procs: list[subprocess.Popen[bytes]] = []
    try:
        plugin = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "elliot_mcp_plugin.main:app",
                "--port",
                str(plugin_port),
                "--host",
                "127.0.0.1",
                "--app-dir",
                "packages/mcp-plugin/src",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=plugin_log,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        procs.append(plugin)

        if not skip_runtime:
            runtime = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "elliot_connector_runtime.server:app",
                    "--port",
                    str(runtime_port),
                    "--host",
                    "127.0.0.1",
                    "--app-dir",
                    "packages/connector-runtime/src",
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=runtime_log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
            procs.append(runtime)

        if not skip_studio:
            studio = subprocess.Popen(
                [
                    "pnpm",
                    "--filter",
                    "@elliot/studio",
                    "run",
                    "dev",
                    "--",
                    "--port",
                    str(studio_port),
                    "--strictPort",
                    "--host",
                    "127.0.0.1",
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=studio_log,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
            procs.append(studio)

        plugin_url = f"http://127.0.0.1:{plugin_port}"
        runtime_url = f"http://127.0.0.1:{runtime_port}"
        studio_url = f"http://127.0.0.1:{studio_port}"
        plugin_mcp_url = f"{plugin_url}/mcp/"

        _wait_mcp_ready(plugin_mcp_url, READY_TIMEOUT)
        if not skip_runtime:
            _wait_http_ok(f"{runtime_url}/health", READY_TIMEOUT, "runtime")
        if not skip_studio:
            _wait_http_ok(studio_url, READY_TIMEOUT, "studio")

        yield StackEndpoints(
            plugin_url=plugin_url,
            plugin_mcp_url=plugin_mcp_url,
            runtime_url=runtime_url,
            studio_url=studio_url,
            workspace=workspace,
            log_dir=log_dir,
        )
    finally:
        for proc in procs:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        plugin_log.close()
        if runtime_log is not None:
            runtime_log.close()
        if studio_log is not None:
            studio_log.close()
