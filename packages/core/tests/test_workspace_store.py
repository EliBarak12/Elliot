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
    # The first 12 bytes are a random nonce — file is not valid JSON
    assert not raw.startswith(b"{")
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
