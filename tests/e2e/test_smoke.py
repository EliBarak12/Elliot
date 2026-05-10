"""E2E smoke test: start the connector-runtime server, hit /health, /v1/audit."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

MINIMAL_CONNECTOR = {
    "name": "Smoke Test Connector",
    "slug": "smoke",
    "version": "1.0.0",
    "sources": [],
    "tools": [
        {
            "id": "ping",
            "name": "Ping",
            "description": "Return a constant ping response",
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT 1 AS ok",
            "parameters": [],
        }
    ],
    "skills": [],
}


def _wait_for_health(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    return False


@pytest.mark.e2e
def test_runtime_health_and_audit(tmp_path: Path) -> None:
    connector_file = tmp_path / "smoke.connector.json"
    connector_file.write_text(json.dumps(MINIMAL_CONNECTOR))

    audit_file = tmp_path / "audit.ndjson"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "elliot_connector_runtime.server:app",
            "--port=13001",
            "--app-dir=packages/connector-runtime/src",
        ],
        env={
            **__import__("os").environ,
            "ELLIOT_CONNECTOR_PATH": str(connector_file),
            "ELLIOT_AUDIT_LOG": str(audit_file),
        },
        cwd=str(Path(__file__).parents[2]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        alive = _wait_for_health("http://localhost:13001/health", timeout=15.0)
        assert alive, "Server did not become healthy within 15s"

        r = httpx.get("http://localhost:13001/health", timeout=5.0)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"

        r2 = httpx.get("http://localhost:13001/v1/audit", timeout=5.0)
        assert r2.status_code == 200
        assert isinstance(r2.json(), list)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
