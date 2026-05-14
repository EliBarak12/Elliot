from __future__ import annotations

import json
import os
from pathlib import Path

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from elliot_core.errors import ElliotError

log = structlog.get_logger(__name__)

# Audit finding C2: previously the default `_DEV_PASSPHRASE` was right-padded
# with `0` bytes to 32 bytes and used directly as the AES-GCM key. That means
# `secrets.enc` written with the default was effectively cleartext — anyone
# with the file could decrypt it offline. We now:
#   1. Refuse the dev passphrase outside of development mode unless an
#      explicit opt-in is set (ELLIOT_ALLOW_DEV_SECRET_KEY=1).
#   2. Derive a real 32-byte key via HKDF-SHA256 from the configured
#      passphrase, with a stable salt so the key is reproducible across
#      restarts.
_DEV_PASSPHRASE = "default-dev-key-do-not-use-in-prod"
# Static HKDF salt — published in the source. The salt is not a secret, it
# just domain-separates this KDF from any other use of the same passphrase.
_HKDF_SALT = b"elliot.workspace.secrets.v1"
_HKDF_INFO = b"elliot-secrets-aesgcm-key"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (tmp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically (tmp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _is_dev_environment() -> bool:
    """Return True if the runtime is in a clearly-developmental context.

    Treat unset or ``ELLIOT_ENV=development|dev|test`` as dev. Any other
    value (``production``, ``staging``, …) requires a real key.
    """
    env = os.environ.get("ELLIOT_ENV", "").strip().lower()
    return env in {"", "development", "dev", "test", "testing", "local"}


def _allow_dev_key_override() -> bool:
    return os.environ.get("ELLIOT_ALLOW_DEV_SECRET_KEY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ElliotError(
                "SESSION_LOAD_FAILED",
                "Failed to parse session.json; the file may be corrupt.",
            ) from exc

    def save_session(self, data: dict) -> None:  # type: ignore[type-arg]
        path = self._dir / "session.json"
        _atomic_write_text(path, json.dumps(data, indent=2, default=str))
        log.info("workspace.session.saved", path=str(path))

    def load_secrets(self) -> dict[str, str]:
        path = self._dir / "secrets.enc"
        if not path.exists():
            return {}
        raw = path.read_bytes()
        if len(raw) < 12 + 16:  # nonce + minimal AES-GCM tag
            raise ElliotError(
                "SECRETS_DECRYPT_FAILED",
                "secrets.enc is truncated or empty",
            )
        key = self._get_key()
        nonce, ct = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(key).decrypt(nonce, ct, None)
        except Exception as exc:
            raise ElliotError("SECRETS_DECRYPT_FAILED", "Failed to decrypt secrets file") from exc
        try:
            decoded = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise ElliotError(
                "SECRETS_DECRYPT_FAILED",
                "Decrypted secrets payload is not valid JSON",
            ) from exc
        if not isinstance(decoded, dict):
            raise ElliotError(
                "SECRETS_DECRYPT_FAILED",
                "Decrypted secrets payload is not an object",
            )
        log.info("workspace.secrets.loaded", count=len(decoded))
        return decoded

    def save_secrets(self, secrets: dict[str, str]) -> None:
        key = self._get_key()
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(secrets).encode(), None)
        _atomic_write_bytes(self._dir / "secrets.enc", nonce + ct)
        self._ensure_gitignore()
        log.info("workspace.secrets.saved", count=len(secrets))

    def _get_key(self) -> bytes:
        passphrase = os.environ.get("ELLIOT_SECRET_KEY")
        if passphrase is None or passphrase == _DEV_PASSPHRASE or not passphrase.strip():
            if not (_is_dev_environment() or _allow_dev_key_override()):
                raise ElliotError(
                    "SECRETS_NO_KEY",
                    (
                        "ELLIOT_SECRET_KEY is unset (or set to the developer "
                        "default) but ELLIOT_ENV is not 'development'. Refusing "
                        "to encrypt secrets with a publicly-known key. Generate "
                        "one with: openssl rand -hex 32 — and export it as "
                        "ELLIOT_SECRET_KEY. For one-off dev work, set "
                        "ELLIOT_ALLOW_DEV_SECRET_KEY=1."
                    ),
                )
            # Dev mode: log the choice loudly so it doesn't sneak into a
            # deployment by accident.
            log.warning(
                "workspace.secrets.dev_key_in_use",
                message=(
                    "Using the development passphrase to derive the workspace "
                    "secrets key. DO NOT use this in production."
                ),
            )
            passphrase = _DEV_PASSPHRASE
        return self._derive_key(passphrase)

    @staticmethod
    def _derive_key(passphrase: str) -> bytes:
        """Derive a 32-byte AES-GCM key from a passphrase via HKDF-SHA256."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        )
        return hkdf.derive(passphrase.encode("utf-8"))

    def _ensure_gitignore(self) -> None:
        gi = Path(".gitignore")
        entry = ".elliot/secrets.enc"
        existing = gi.read_text() if gi.exists() else ""
        if entry in existing:
            return
        # Atomic write avoids the race where two CLI runs both `open("a")` and
        # interleave duplicate entries.
        sep = "" if not existing or existing.endswith("\n") else "\n"
        _atomic_write_text(gi, existing + sep + entry + "\n")
