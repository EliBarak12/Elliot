# 022 — ElliotSession

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 021

## Objective
Singleton session that holds all live state. Shared across all MCP HTTP connections.

## Files to Create

### `packages/core/src/elliot_core/workspace/store.py`
```python
import json
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64
from elliot_core.errors import ElliotError

class WorkspaceStore:
    def __init__(self, cwd: str) -> None:
        self._dir = Path(cwd) / ".elliot"
        self._dir.mkdir(exist_ok=True)

    def load_session(self) -> dict | None:
        path = self._dir / "session.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_session(self, data: dict) -> None:
        (self._dir / "session.json").write_text(json.dumps(data, indent=2, default=str))

    def load_secrets(self) -> dict[str, str]:
        path = self._dir / "secrets.enc"
        if not path.exists():
            return {}
        key = self._get_key()
        raw = path.read_bytes()
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(plaintext)

    def save_secrets(self, secrets: dict[str, str]) -> None:
        key = self._get_key()
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(secrets).encode(), None)
        (self._dir / "secrets.enc").write_bytes(nonce + ct)
        self._ensure_gitignore()

    def _get_key(self) -> bytes:
        raw = os.environ.get("ELLIOT_SECRET_KEY", "default-dev-key-do-not-use-in-prod")
        return raw.encode().ljust(32, b"0")[:32]

    def _ensure_gitignore(self) -> None:
        gi = Path(".") / ".gitignore"
        entry = ".elliot/secrets.enc"
        if gi.exists() and entry in gi.read_text():
            return
        with gi.open("a") as f:
            f.write(f"\n{entry}\n")
```

### `packages/mcp-plugin/src/elliot_mcp_plugin/session.py`
```python
from elliot_core import SQLiteEngine, ToolRegistry, ConnectorBuilder, WorkspaceStore
from elliot_core.types.connector import ProductContext, SourceConfig
from elliot_core.types.tool import ToolDefinition, SkillDefinition
import subprocess, os

class ElliotSession:
    def __init__(self, cwd: str = ".") -> None:
        self.engine = SQLiteEngine()
        self.registry = ToolRegistry()
        self.builder = ConnectorBuilder()
        self.workspace = WorkspaceStore(cwd)
        self.sources: dict[str, SourceConfig] = {}
        self.product_context: ProductContext | None = None
        self.runtime_process: subprocess.Popen | None = None

    def load(self) -> None:
        data = self.workspace.load_session()
        if data:
            self.product_context = ProductContext(**data["product_context"]) if data.get("product_context") else None
            # restore sources, tools, skills...

    def save(self) -> None:
        self.workspace.save_session({
            "product_context": self.product_context.model_dump() if self.product_context else None,
            "sources": [s.model_dump() for s in self.sources.values()],
            "tools": [t.model_dump() for t in self.registry.get_all()],
            "skills": [s.model_dump() for s in self.registry.get_all_skills()],
        })
```

## Done When
- [ ] `save()` then `load()` in a new `ElliotSession` restores identical state
- [ ] `secrets.enc` is binary (not plaintext)
- [ ] `.gitignore` updated on first `save_secrets()` call
