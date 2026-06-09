"""Tests for WorkspaceStore: session persistence and secret encryption."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.errors import ElliotError
from elliot_core.workspace.store import WorkspaceStore


@pytest.fixture()
def store(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(cwd=str(tmp_path))


# ── session persistence ───────────────────────────────────────────────────────


def test_load_session_returns_none_when_missing(store: WorkspaceStore):
    assert store.load_session() is None


def test_save_and_load_session_roundtrip(store: WorkspaceStore):
    data = {"product_context": {"name": "Acme", "base_url": "https://acme.com"}}
    store.save_session(data)
    loaded = store.load_session()
    assert loaded is not None
    assert loaded["product_context"]["name"] == "Acme"


def test_session_file_is_human_readable(store: WorkspaceStore, tmp_path: Path):
    store.save_session({"key": "value"})
    raw = (tmp_path / ".elliot" / "session.json").read_text()
    parsed = json.loads(raw)
    assert parsed["key"] == "value"


# ── secrets encryption ────────────────────────────────────────────────────────


def test_load_secrets_returns_empty_when_missing(store: WorkspaceStore):
    assert store.load_secrets() == {}


def test_save_and_load_secrets_roundtrip(store: WorkspaceStore):
    secrets = {"API_KEY": "abc123", "DB_PASS": "secret"}
    store.save_secrets(secrets)
    loaded = store.load_secrets()
    assert loaded == secrets


def test_secrets_file_is_binary(store: WorkspaceStore, tmp_path: Path):
    store.save_secrets({"TOKEN": "xyz"})
    raw = (tmp_path / ".elliot" / "secrets.enc").read_bytes()
    # The real property is that the secret is encrypted at rest: neither the
    # value nor the key name appears in cleartext, and the file is not the JSON
    # plaintext. (Asserting `not raw.startswith(b"{")` was flaky — the file
    # opens with a random 12-byte nonce, so ~1/256 of the time its first byte
    # is "{" 0x7B and the check failed for a perfectly valid encrypted file.)
    assert b"xyz" not in raw  # secret value never stored in cleartext
    assert b"TOKEN" not in raw  # nor the key name
    with pytest.raises(ValueError):
        json.loads(raw)  # not the human-readable JSON plaintext
    assert len(raw) > 12  # nonce (12 bytes) + ciphertext


def test_secrets_with_custom_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_SECRET_KEY", "my-custom-32-byte-key-00000000000")
    s = WorkspaceStore(cwd=str(tmp_path))
    s.save_secrets({"X": "y"})
    assert s.load_secrets() == {"X": "y"}


def test_load_secrets_wrong_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_SECRET_KEY", "key-a-0000000000000000000000000000")
    s = WorkspaceStore(cwd=str(tmp_path))
    s.save_secrets({"TOKEN": "secret"})

    monkeypatch.setenv("ELLIOT_SECRET_KEY", "key-b-0000000000000000000000000000")
    with pytest.raises(ElliotError) as exc_info:
        s.load_secrets()
    assert exc_info.value.code == "SECRETS_DECRYPT_FAILED"


# ── .gitignore management ─────────────────────────────────────────────────────


def test_save_secrets_adds_gitignore_entry(
    store: WorkspaceStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    store.save_secrets({"K": "v"})
    gi = (tmp_path / ".gitignore").read_text()
    assert ".elliot/secrets.enc" in gi


def test_save_secrets_does_not_duplicate_gitignore_entry(
    store: WorkspaceStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    store.save_secrets({"K": "v"})
    store.save_secrets({"K": "v2"})
    gi = (tmp_path / ".gitignore").read_text()
    assert gi.count(".elliot/secrets.enc") == 1


# ── Audit C2: secret key hardening regression tests ──────────────────────────


def test_save_secrets_refused_in_prod_without_real_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ELLIOT_ENV=production + no ELLIOT_SECRET_KEY must refuse to encrypt."""
    monkeypatch.delenv("ELLIOT_SECRET_KEY", raising=False)
    monkeypatch.delenv("ELLIOT_ALLOW_DEV_SECRET_KEY", raising=False)
    monkeypatch.setenv("ELLIOT_ENV", "production")
    s = WorkspaceStore(cwd=str(tmp_path))
    with pytest.raises(ElliotError) as exc:
        s.save_secrets({"X": "y"})
    assert exc.value.code == "SECRETS_NO_KEY"


def test_save_secrets_refused_in_prod_with_dev_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Using the literal dev-passphrase string in prod must also be refused."""
    monkeypatch.setenv("ELLIOT_ENV", "production")
    monkeypatch.setenv("ELLIOT_SECRET_KEY", "default-dev-key-do-not-use-in-prod")
    monkeypatch.delenv("ELLIOT_ALLOW_DEV_SECRET_KEY", raising=False)
    s = WorkspaceStore(cwd=str(tmp_path))
    with pytest.raises(ElliotError) as exc:
        s.save_secrets({"X": "y"})
    assert exc.value.code == "SECRETS_NO_KEY"


def test_save_secrets_allowed_in_prod_with_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ELLIOT_ALLOW_DEV_SECRET_KEY=1 opts out of the prod refusal."""
    monkeypatch.setenv("ELLIOT_ENV", "production")
    monkeypatch.delenv("ELLIOT_SECRET_KEY", raising=False)
    monkeypatch.setenv("ELLIOT_ALLOW_DEV_SECRET_KEY", "1")
    s = WorkspaceStore(cwd=str(tmp_path))
    s.save_secrets({"X": "y"})  # should not raise
    assert s.load_secrets() == {"X": "y"}


def test_save_secrets_allowed_in_dev_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ELLIOT_ENV unset (or dev) lets the dev key through with a warning."""
    monkeypatch.delenv("ELLIOT_ENV", raising=False)
    monkeypatch.delenv("ELLIOT_SECRET_KEY", raising=False)
    s = WorkspaceStore(cwd=str(tmp_path))
    s.save_secrets({"X": "y"})
    assert s.load_secrets() == {"X": "y"}


def test_load_secrets_truncated_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A truncated secrets.enc must surface SECRETS_DECRYPT_FAILED, not crash."""
    monkeypatch.setenv("ELLIOT_SECRET_KEY", "a-real-passphrase")
    enc = tmp_path / ".elliot" / "secrets.enc"
    enc.parent.mkdir(parents=True, exist_ok=True)
    enc.write_bytes(b"short")  # < 12 + 16 = 28 bytes minimum
    s = WorkspaceStore(cwd=str(tmp_path))
    with pytest.raises(ElliotError) as exc:
        s.load_secrets()
    assert exc.value.code == "SECRETS_DECRYPT_FAILED"


def test_load_session_corrupt_raises(tmp_path: Path):
    """A corrupt session.json must raise SESSION_LOAD_FAILED, not JSONDecodeError."""
    sess = tmp_path / ".elliot" / "session.json"
    sess.parent.mkdir(parents=True, exist_ok=True)
    sess.write_text("not-valid-json{{{")
    s = WorkspaceStore(cwd=str(tmp_path))
    with pytest.raises(ElliotError) as exc:
        s.load_session()
    assert exc.value.code == "SESSION_LOAD_FAILED"


def test_save_session_is_atomic(tmp_path: Path):
    """save_session must not leave a half-written session.json on the disk."""
    s = WorkspaceStore(cwd=str(tmp_path))
    s.save_session({"a": 1})
    # tmp file is os.replace'd into place; nothing should be lying around.
    leftover = (tmp_path / ".elliot" / "session.json.tmp").exists()
    assert not leftover
