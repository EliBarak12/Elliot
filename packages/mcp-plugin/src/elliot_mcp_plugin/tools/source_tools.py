"""Source management tools — discover, preview, profile and manage data sources."""

from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.paths import PathEscape, safe_join
from elliot_core.sources.api_fetcher import _resolve_secret, fetch_endpoint
from elliot_core.sources.db_connector import query_database
from elliot_core.sources.file_reader import read_file
from elliot_core.sqlite.flattener import flatten
from elliot_core.types.source import SourceConfig
from elliot_mcp_plugin.oauth_login import LOGIN_TTL_S, start_login
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

# Accepted source_type values, including friendly aliases for agents
# (api/file/db) and the canonical names used in SourceConfig and the Studio
# UI (rest/file/postgres/mysql). All map to a SourceConfig Literal.
_TYPE_MAP: dict[str, str] = {
    "api": "rest",
    "rest": "rest",
    "http": "rest",
    "file": "file",
    "csv": "file",
    "json": "file",
    "db": "postgres",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
}

# Uploaded file basename rules (used by elliot_upload_file). Bounded length,
# no traversal, only printable ASCII letters / digits / `.-_`.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_UPLOAD_SUFFIXES = frozenset(
    {".json", ".jsonl", ".ndjson", ".csv", ".txt", ".yaml", ".yml"}
)
_DEFAULT_UPLOAD_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB


def _upload_max_bytes() -> int:
    raw = os.environ.get("ELLIOT_UPLOAD_MAX_BYTES", "")
    try:
        v = int(raw) if raw else _DEFAULT_UPLOAD_MAX_BYTES
        return max(1024, v)
    except ValueError:
        return _DEFAULT_UPLOAD_MAX_BYTES


def _sources_dir(session: ElliotSession) -> Path:
    """Return the Elliot-managed uploads directory for this session.

    Lives under the workspace's ``.elliot/sources/`` so it is inside the
    file_reader allowlist by default (no ELLIOT_FILE_ROOT tuning needed).
    """
    d = Path(session.workspace._dir) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


_AUTH_ALIAS_KEYS = ("token", "username", "password")


def _normalize_auth(config: dict[str, Any]) -> dict[str, Any]:
    """Accept ergonomic auth aliases and normalize them to SourceConfig's shape.

    ``SourceConfig.AuthConfig`` only accepts ``secret_key``, but agents naturally
    write ``{"type":"bearer","token":"x"}`` or
    ``{"type":"basic","username":"u","password":"p"}`` — which previously hit a
    cryptic pydantic ``secret_key Field required`` error (the single biggest
    cluster of harness failures). Map those aliases to ``secret_key`` here.
    Returns a new config dict; never mutates the input.
    """
    auth = config.get("auth")
    if not isinstance(auth, dict):
        return config
    has_alias = any(auth.get(k) for k in _AUTH_ALIAS_KEYS)
    if not has_alias:
        return config
    if auth.get("secret_key"):
        raise ElliotError(
            "VALIDATION_ERROR",
            "auth: provide either 'secret_key' or the token/username+password aliases, not both.",
        )
    auth = dict(auth)
    atype = str(auth.get("type", "")).lower()
    if atype == "bearer" and auth.get("token"):
        auth["secret_key"] = auth.pop("token")
    elif atype == "basic" and (auth.get("username") or auth.get("password")):
        user = auth.pop("username", "") or ""
        pw = auth.pop("password", "") or ""
        auth["secret_key"] = f"{user}:{pw}"
    # Drop any leftover alias keys so AuthConfig's extra="forbid" doesn't reject
    # them (e.g. a stray "token" passed to a non-bearer type).
    for k in _AUTH_ALIAS_KEYS:
        auth.pop(k, None)
    out = dict(config)
    out["auth"] = auth
    return out


def _build_source_config(
    source_type: str, config: dict[str, Any], source_id: str, name: str
) -> SourceConfig:
    """Validate a raw config dict into a SourceConfig, mapping friendly types."""
    mapped_type = _TYPE_MAP[source_type.lower()]
    config = _normalize_auth(config)
    merged = {"id": source_id, "type": mapped_type, "name": name, **config}
    return SourceConfig.model_validate(merged)


async def _resolve_build_oauth_token(
    session: ElliotSession, cfg: SourceConfig, name: str, secrets: dict[str, str]
) -> str | None:
    """Return a bearer token to fetch discovery samples for an OAuth source.

    For ``auth.type == "oauth2"`` sources the connector ships ``scope:
    per_user`` so end users authenticate themselves at runtime — but the
    *builder* still needs a token to fetch sample rows now. If they've started
    an interactive login via ``elliot_connect_source``, block briefly for it to
    complete and return that token. If a real static token happens to be
    configured (a shared-auth env var), return ``None`` so the normal
    secret-resolution path handles it. Otherwise raise an actionable
    ``AUTH_REQUIRED`` telling the agent to run ``elliot_connect_source`` first.

    The returned token is used only for this fetch — it is never written into
    the connector file.
    """
    auth = cfg.auth
    if auth is None or auth.type != "oauth2":
        return None

    login = session.oauth_logins.get(name)
    if login is not None:
        try:
            token = await login.wait_and_exchange()
        except TimeoutError as exc:
            raise ElliotError(
                "AUTH_REQUIRED",
                f"Still waiting for you to finish logging in to '{name}'. Open the "
                "authorize_url from elliot_connect_source, complete the login, then "
                "re-run elliot_discover_source.",
                detail={"source": name, "connect_id": login.connect_id},
            ) from exc
        except Exception as exc:
            session.oauth_logins.pop(name, None)
            login.shutdown()
            raise ElliotError(
                "AUTH_FAILED",
                f"OAuth login for '{name}' failed; restart it with elliot_connect_source.",
                detail={"source": name},
            ) from exc
        # Token captured — the loopback listener is no longer needed, but keep
        # the login (with its cached token) so a re-discover/refresh in this
        # session reuses it without forcing another login.
        login.shutdown()
        return token

    # No interactive login in progress. If a concrete static token is wired up
    # (e.g. shared oauth2 against a service-account env var), let the normal
    # path use it. An empty or still-templated value means "no token yet".
    resolved = _resolve_secret(auth.secret_key, secrets)
    if resolved and "{{" not in resolved:
        return None
    raise ElliotError(
        "AUTH_REQUIRED",
        f"Source '{name}' uses OAuth and no token is available yet. Call "
        "elliot_connect_source(source_type, config, name) with these same "
        "arguments to log in via your browser, then re-run elliot_discover_source. "
        "Do not ask the user to paste a token.",
        detail={"source": name},
    )


def _decode_upload(file_name: str, content: str, encoding: str) -> bytes:
    """Validate an upload's encoding, name, and extension, then return its
    decoded bytes — enforcing the size cap. Raises ElliotError on any
    violation so the handler can map it to an MCP error response.
    """
    if encoding not in ("text", "base64"):
        raise ElliotError(
            "VALIDATION_ERROR",
            "encoding must be 'text' or 'base64'",
            detail={"encoding": encoding},
        )
    if not _FILENAME_RE.match(file_name):
        raise ElliotError(
            "INVALID_FILE_NAME",
            "file_name must be a plain basename (letters, digits, dot, dash, "
            "underscore only) with no path separators",
            detail={"file_name": file_name},
        )
    suffix = Path(file_name).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise ElliotError(
            "INVALID_FILE_NAME",
            f"unsupported file extension {suffix!r}; allowed: "
            + ", ".join(sorted(_ALLOWED_UPLOAD_SUFFIXES)),
            detail={"file_name": file_name},
        )

    if encoding == "base64":
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ElliotError(
                "VALIDATION_ERROR",
                "content is not valid base64",
            ) from exc
    else:
        data = content.encode("utf-8")

    max_bytes = _upload_max_bytes()
    if len(data) > max_bytes:
        raise ElliotError(
            "FILE_TOO_LARGE",
            f"file exceeds {max_bytes} bytes; set ELLIOT_UPLOAD_MAX_BYTES "
            "to raise the cap if the source is genuinely large",
            detail={"bytes": len(data), "limit": max_bytes},
        )
    return data


def _unknown_source_type_error(source_type: str) -> dict[str, str] | None:
    """The error dict an MCP source tool returns for an unrecognized
    ``source_type``, or None when the type is valid. Shared by
    elliot_connect_source and elliot_discover_source so the message and shape
    stay identical."""
    if source_type.lower() in _TYPE_MAP:
        return None
    return {
        "error": (
            f"Unknown source_type: {source_type!r}. Valid values: {', '.join(sorted(_TYPE_MAP))}"
        )
    }


def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_upload_file(
        file_name: str,
        content: str,
        encoding: str = "text",
    ) -> dict:  # type: ignore[type-arg]
        """Stage a file inside Elliot's managed sources directory and return its path.

        Use this before elliot_discover_source when the file lives on the
        user's machine. The agent reads the local file, sends the contents
        here, and Elliot saves them under .elliot/sources/. The returned
        managed_path is always inside the file-reader allowlist, so the
        agent does NOT need to configure ELLIOT_FILE_ROOT.

        Workflow:
            up = elliot_upload_file(file_name="data.json", content="...")
            elliot_discover_source(
                source_type="json",
                config={"path": up["managed_path"]},
                name="my_source",
            )

        Args:
            file_name: basename only (no directory parts). Must match
                ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ and end in one of
                .json / .jsonl / .ndjson / .csv / .txt / .yaml / .yml.
            content: file body as UTF-8 text (default) or base64-encoded
                bytes (set encoding="base64" for binary).
            encoding: "text" or "base64". Defaults to "text".
        """
        try:
            log.info("source.upload.start", file_name=file_name, encoding=encoding)
            data = _decode_upload(file_name, content, encoding)

            # safe_join guarantees the resolved destination stays under the
            # session's sources/ directory — even though _FILENAME_RE already
            # forbids `..` / `/`, this is defence-in-depth.
            dest_root = _sources_dir(session)
            try:
                dest = safe_join(dest_root, file_name)
            except PathEscape as exc:
                raise ElliotError(
                    "INVALID_FILE_NAME",
                    "file_name resolves outside the managed sources directory",
                ) from exc

            # Atomic write — readers never see a half-written file even if
            # the agent re-uploads while a discover is in-flight.
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)

            log.info("source.upload.saved", path=str(dest), bytes=len(data))
            return {
                "managed_path": str(dest),
                "file_name": file_name,
                "size_bytes": len(data),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("source.upload.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", "upload failed"))

    @mcp.tool()
    def elliot_connect_source(
        source_type: str,
        config: dict,  # type: ignore[type-arg]
        name: str,
    ) -> dict:  # type: ignore[type-arg]
        """Start a browser OAuth login so discover can fetch an auth'd API as you.

        Use this BEFORE elliot_discover_source when the source's auth.type is
        "oauth2" and you don't already have a token in an env var. Do NOT ask the
        user to paste a token — that's exactly what this avoids.

        Pass the SAME source_type / config / name you'll pass to
        elliot_discover_source. The config must include an oauth2 auth block, e.g.:
            "auth": {
              "type": "oauth2", "scope": "per_user",
              "secret_key": "{{ user_oauth:acme }}",
              "oauth2": {
                "authorization_url": "https://acme.com/oauth/authorize",
                "token_url": "https://acme.com/oauth/token",
                "scopes": ["read"],
                "client_id_secret": "{{ env:ACME_CLIENT_ID }}",
                "client_secret_secret": "{{ env:ACME_CLIENT_SECRET }}"
              }
            }

        PREREQUISITE — tell the user before calling this: an oauth2 source needs
        an OAuth *app* registered with the provider. Proactively explain that
        they must (1) create an OAuth app in the provider's developer settings,
        (2) allow a http://127.0.0.1 loopback redirect URL, and (3) export the
        resulting Client ID + Client Secret as the env vars named in
        client_id_secret / client_secret_secret. These are app-level, one-time
        credentials (also used by their end users' runtime login), NOT a personal
        token. If they aren't set this tool returns AUTH_REQUIRED.

        Returns {status: "awaiting_authorization", authorize_url, connect_id}.
        Surface authorize_url to the user; they open it, log in to the upstream
        API, and Elliot captures the token on a loopback callback. Then call
        elliot_discover_source with the same arguments — it blocks until the
        login completes and uses that token to fetch the schema.

        The builder token is used for discovery ONLY: it is never written into
        the connector file. End users still authenticate themselves at runtime
        via the per_user OAuth flow you configured here.
        """
        try:
            type_error = _unknown_source_type_error(source_type)
            if type_error is not None:
                return type_error
            key = source_type.lower()
            source_id = str(uuid.uuid4())
            cfg = _build_source_config(key, config, source_id, name)
            if cfg.type != "rest" or cfg.auth is None or cfg.auth.type != "oauth2":
                raise ElliotError(
                    "VALIDATION_ERROR",
                    "elliot_connect_source is only for REST sources with auth.type "
                    "'oauth2'. For api_key/bearer/basic auth, set the credential as a "
                    "{{ env:VAR }} secret and call elliot_discover_source directly.",
                    detail={"type": cfg.type, "auth": cfg.auth.type if cfg.auth else None},
                )
            oauth2 = cfg.auth.oauth2
            if oauth2 is None:
                raise ElliotError(
                    "VALIDATION_ERROR",
                    "auth.oauth2 block is required (authorization_url, token_url, "
                    "client_id_secret, client_secret_secret).",
                )
            secrets = session.workspace.load_secrets()
            client_id = _resolve_secret(oauth2.client_id_secret, secrets)
            client_secret = _resolve_secret(oauth2.client_secret_secret, secrets)
            if not client_id or "{{" in client_id:
                raise ElliotError(
                    "AUTH_REQUIRED",
                    "Your OAuth app's client id is not set. Tell the user to register "
                    "an OAuth app with the provider (in its developer settings), allow a "
                    "http://127.0.0.1 loopback redirect URL, and export the Client ID and "
                    f"Client Secret as the env vars {oauth2.client_id_secret} and "
                    f"{oauth2.client_secret_secret}. These are app-level, one-time "
                    "credentials (the same ones their end users' login uses), NOT a "
                    "personal token — do not ask the user to paste a token instead.",
                    detail={
                        "client_id_secret": oauth2.client_id_secret,
                        "client_secret_secret": oauth2.client_secret_secret,
                    },
                )

            # Restart cleanly if a previous login for this name is still around.
            prev = session.oauth_logins.pop(name, None)
            if prev is not None:
                prev.shutdown()

            connect_id = str(uuid.uuid4())
            login = start_login(
                oauth2=oauth2,
                client_id=client_id,
                client_secret=client_secret,
                name=name,
                connect_id=connect_id,
            )
            session.oauth_logins[name] = login
            log.info("source.connect.start", name=name, connect_id=connect_id, port=login.port)
            return {
                "status": "awaiting_authorization",
                "connect_id": connect_id,
                "authorize_url": login.authorize_url,
                "expires_in": int(LOGIN_TTL_S),
                "next_step": (
                    "Open authorize_url in a browser and log in to the API, then call "
                    "elliot_discover_source with the same source_type/config/name."
                ),
            }
        except ElliotError as exc:
            log.error("source.connect.failed", error=exc.message)
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("source.connect.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", "connect failed"))

    @mcp.tool()
    async def elliot_discover_source(
        source_type: str,
        config: dict,  # type: ignore[type-arg]
        name: str,
    ) -> dict:  # type: ignore[type-arg]
        """Fetch a data source (API / file / DB) and load it into in-memory SQLite.

        source_type: 'api'|'rest'|'http' for REST APIs, 'file'|'csv'|'json' for files,
                     'db'|'postgres'|'postgresql'|'mysql' for databases.
        config: source-specific config dict. Common keys:
            - url / path / table — the source location.
            - auth — {"type": "api_key", "header_name": "...", "secret_key": "..."}
              or {"type": "bearer", "token": "..."} or
              {"type": "basic", "username": "...", "password": "..."}.
            - data_path — jmespath to the array inside a wrapped REST response,
              e.g. "products" for {"total":..,"products":[...]}. Usually
              auto-detected; pass it explicitly when the rows are nested under
              a non-obvious key or there are several arrays.
        name: logical name used as the SQLite table prefix
        """
        try:
            type_error = _unknown_source_type_error(source_type)
            if type_error is not None:
                return type_error
            key = source_type.lower()
            source_id = str(uuid.uuid4())
            cfg = _build_source_config(key, config, source_id, name)
            secrets = session.workspace.load_secrets()

            rows: list[dict[str, Any]]
            if cfg.type == "file":
                result = read_file(cfg)
                rows = result.rows

            elif cfg.type == "rest":
                token_override = await _resolve_build_oauth_token(session, cfg, name, secrets)
                if token_override is not None:
                    result = await fetch_endpoint(cfg, secrets, auth_token_override=token_override)
                else:
                    result = await fetch_endpoint(cfg, secrets)
                rows = result.rows

            else:  # postgres / mysql
                result = query_database(cfg, secrets)
                rows = result.rows

            flat = flatten(rows, table_name=name)
            session.engine.load_result(flat)

            cfg.table_name = name
            cfg.row_count = len(rows)
            cfg.config_snapshot = config
            session.sources[source_id] = cfg
            session.save()

            log.info(
                "source.discovered",
                source_id=source_id,
                table=name,
                rows=len(rows),
            )
            # Surface BOTH flatten warnings and fetch/read warnings. The latter
            # carry the build-time smoke-test signal — e.g. "couldn't locate the
            # records array; set data_path" — which previously never reached the
            # builder, so a connector whose tools return [] looked healthy.
            warnings = list(flat.warnings) + list(getattr(result, "warnings", []) or [])
            return {
                "source_id": source_id,
                "table_name": name,
                "row_count": len(rows),
                "columns": [c.name for c in flat.primary_table.columns],
                "warnings": warnings,
            }

        except ElliotError as exc:
            log.error("source.discover.failed", error=exc.message)
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("source.discover.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_sources() -> dict:  # type: ignore[type-arg]
        """List all loaded sources with their table names, row counts, and columns."""
        try:
            # Pick up sources the agent discovered since our last list — even
            # if the agent runs in a separate plugin process sharing the
            # same workspace.
            session.refresh_from_disk()
            sources: list[dict[str, Any]] = []
            for sid, src in session.sources.items():
                columns: list[dict[str, str]] = []
                if src.table_name:
                    try:
                        schema = session.engine.get_table_schema(src.table_name)
                        columns = [{"name": c["name"], "type": c["type"]} for c in schema]
                    except Exception:
                        columns = []
                sources.append(
                    {
                        # Both keys for backwards compatibility: 'id' is the
                        # canonical SourceConfig field name; 'source_id' is
                        # the historical name used by other source tools.
                        "id": sid,
                        "source_id": sid,
                        "name": src.name,
                        "type": src.type,
                        "table_name": src.table_name,
                        "row_count": src.row_count,
                        "columns": columns,
                    }
                )
            return {"sources": sources, "count": len(sources)}
        except Exception as exc:
            log.error("source.list.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_preview_source(table_name: str, limit: int = 10) -> dict:  # type: ignore[type-arg]
        """Return the first N rows from a loaded source table."""
        try:
            rows = session.engine.query(f'SELECT * FROM "{table_name}" LIMIT :n', {"n": limit})
            schema = session.engine.get_table_schema(table_name)
            return {"rows": rows, "row_count": len(rows), "schema": schema}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return {"error": f"Table '{table_name}' not found or query failed: {exc}"}

    @mcp.tool()
    def elliot_profile_source(table_name: str) -> dict:  # type: ignore[type-arg]
        """Return column statistics (min, max, nulls, distinct, top values) for a table."""
        try:
            schema = session.engine.get_table_schema(table_name)
            stats = session.engine.get_table_stats(table_name)
            profiles = {
                col["name"]: session.engine.profile_column(table_name, col["name"])
                for col in schema
            }
            return {
                "table": table_name,
                "row_count": stats["row_count"],
                "columns": profiles,
            }
        except Exception as exc:
            log.error("source.profile.failed", table=table_name, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    async def elliot_refresh_source(source_id: str) -> dict:  # type: ignore[type-arg]
        """Re-fetch a source from its origin and reload the table in SQLite."""
        try:
            src = session.sources.get(source_id)
            if src is None:
                return {"error": f"Source not found: {source_id}"}
            # Map SourceConfig.type back to friendly type
            reverse_map = {v: k for k, v in _TYPE_MAP.items()}
            friendly_type = reverse_map.get(src.type, src.type)
            return await elliot_discover_source(
                source_type=friendly_type,
                config=src.config_snapshot or {},
                name=src.name,
            )
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_delete_source(source_id: str) -> dict:  # type: ignore[type-arg]
        """Delete a source and cascade-delete any tools bound to it.

        Use this to prune an orphaned source — e.g. one you discovered, then
        rebuilt your tools onto a differently-named source, leaving the old one
        materialized as dead weight (it is still fetched/loaded on every build).
        WARNING: any tool whose source_ids include this source is deleted too —
        re-point or re-create those tools against the source you kept.
        """
        try:
            if session.sources.get(source_id) is None:
                return {"error": f"Source not found: {source_id}"}
            return session.remove_source(source_id)
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("source.delete.failed", source_id=source_id, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def studio_remove_source(source_id: str) -> dict:  # type: ignore[type-arg]
        """Remove a source and cascade-delete its tools. Studio/dashboard only — not
        exposed to coding agents (filtered by the studio_ prefix gate)."""
        try:
            return session.remove_source(source_id)
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
