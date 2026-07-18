"""Demo-connector preload (task 081): a runtime with no configured connector
serves the bundled demo instead of the no-connector 503 app — unless the
operator opts out, the demo file is absent, or it fails to load."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from elliot_connector_runtime.server import _load_demo_connector, create_app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEMO_PATH = _REPO_ROOT / "connectors" / "my-saas.connector.json"


@pytest.fixture(autouse=True)
def _isolated_runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every runtime side effect at tmp and the demo at the repo copy."""
    monkeypatch.chdir(_REPO_ROOT)  # demo data files resolve relative to cwd
    monkeypatch.setenv("ELLIOT_CONNECTOR", str(tmp_path / "missing.connector.json"))
    monkeypatch.setenv("ELLIOT_DEMO_CONNECTOR", str(_DEMO_PATH))
    monkeypatch.delenv("ELLIOT_PRELOAD_DEMO", raising=False)
    monkeypatch.setenv("ELLIOT_DB_URL", f"sqlite:///{tmp_path / 'observations.db'}")
    monkeypatch.setenv("ELLIOT_AUDIT_LOG", str(tmp_path / "audit.ndjson"))
    monkeypatch.setenv("ELLIOT_SESSIONS_LOG", str(tmp_path / "sessions.ndjson"))
    monkeypatch.setenv("ELLIOT_VAULT_DB", str(tmp_path / "credentials.db"))


def test_load_demo_connector_finds_the_bundled_demo() -> None:
    loaded = _load_demo_connector()
    assert loaded is not None
    config, path = loaded
    assert config.slug == "my-saas"
    assert path == str(_DEMO_PATH)


def test_preload_serves_full_runtime_when_configured_path_missing() -> None:
    app = create_app()
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["connector"] == str(_DEMO_PATH)


@pytest.mark.parametrize("off_value", ["false", "0", "no", "off", "FALSE"])
def test_preload_disabled_by_env_flag(monkeypatch: pytest.MonkeyPatch, off_value: str) -> None:
    monkeypatch.setenv("ELLIOT_PRELOAD_DEMO", off_value)
    assert _load_demo_connector() is None
    app = create_app()
    health = TestClient(app).get("/health").json()
    assert health["status"] == "no_connector"


def test_preload_skipped_when_demo_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ELLIOT_DEMO_CONNECTOR", str(tmp_path / "nope.connector.json"))
    assert _load_demo_connector() is None
    app = create_app()
    assert TestClient(app).get("/health").json()["status"] == "no_connector"


def test_corrupt_demo_degrades_to_no_connector_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.connector.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("ELLIOT_DEMO_CONNECTOR", str(broken))
    assert _load_demo_connector() is None
    app = create_app()
    assert TestClient(app).get("/health").json()["status"] == "no_connector"


def test_configured_connector_wins_over_demo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "real.connector.json"
    configured.write_text(
        _DEMO_PATH.read_text(encoding="utf-8").replace('"my-saas"', '"real-saas"', 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("ELLIOT_CONNECTOR", str(configured))
    app = create_app()
    health = TestClient(app).get("/health").json()
    assert health["status"] == "ok"
    assert health["connector"] == str(configured)
