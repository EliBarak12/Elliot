from __future__ import annotations

import json
import os
from pathlib import Path

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from elliot_core.errors import ElliotError

log = structlog.get_logger(__name__)


class WorkspaceStore:
    def __init__(self, cwd: str = ".") -> None:
        self._dir = Path(cwd) / ".elliot"
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_session(self) -> dict | None:  # type: ignore[type-arg]
        path = self._dir / "session.json"
        if not path.exists():
            log.debug("workspace.session.missing", path=str(path))
            return None
        log.debug("workspace.session.loaded", path=str(path))
        return json.loads(path.read_text())

    def save_session(self, data: dict) -> None:  # type: ignore[type-arg]
        path = self._dir / "session.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        log.info("workspace.session.saved", path=str(path))

    def load_secrets(self) -> dict[str, str]:
        path = self._dir / "secrets.enc"
        if not path.exists():
            return {}
        key = self._get_key()
        raw = path.read_bytes()
        nonce, ct = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(key).decrypt(nonce, ct, None)
        except Exception as exc:
            raise ElliotError("SECRETS_DECRYPT_FAILED", "Failed to decrypt secrets file") from exc
        log.info("workspace.secrets.loaded", count=len(json.loads(plaintext)))
        return json.loads(plaintext)

    def save_secrets(self, secrets: dict[str, str]) -> None:
        key = self._get_key()
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(secrets).encode(), None)
        (self._dir / "secrets.enc").write_bytes(nonce + ct)
        self._ensure_gitignore()
        log.info("workspace.secrets.saved", count=len(secrets))

    def _get_key(self) -> bytes:
        raw = os.environ.get("ELLIOT_SECRET_KEY", "default-dev-key-do-not-use-in-prod")
        return raw.encode().ljust(32, b"0")[:32]

    def _ensure_gitignore(self) -> None:
        gi = Path(".gitignore")
        entry = ".elliot/secrets.enc"
        if gi.exists() and entry in gi.read_text():
            return
        with gi.open("a") as f:
            f.write(f"\n{entry}\n")
