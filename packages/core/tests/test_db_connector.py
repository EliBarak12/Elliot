"""Tests for db_connector: covers query_database with mocked SQLAlchemy engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from elliot_core.errors import ElliotError, SourceFetchError
from elliot_core.types.source import SourceConfig


def _pg_source(**kwargs: object) -> SourceConfig:
    base: dict[str, object] = dict(id="db", name="DB", type="postgres", table="users")
    base.update(kwargs)
    return SourceConfig(**base)  # type: ignore[arg-type]


def _mysql_source(**kwargs: object) -> SourceConfig:
    base: dict[str, object] = dict(id="db", name="DB", type="mysql", table="orders")
    base.update(kwargs)
    return SourceConfig(**base)  # type: ignore[arg-type]


def _make_engine_mock(rows: list[dict[str, object]]) -> MagicMock:
    """Build a mock SQLAlchemy engine that returns the given rows."""
    row_mocks = [MagicMock(_mapping=row) for row in rows]
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter(row_mocks))
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.execute.return_value = result_mock
    engine_mock = MagicMock()
    engine_mock.connect.return_value = conn_mock
    engine_mock.dispose = MagicMock()
    return engine_mock


# create_engine is imported lazily inside _run_query; patch it in sqlalchemy directly
_PATCH_ENGINE = "sqlalchemy.create_engine"


@pytest.fixture(autouse=True)
def _clear_engine_cache() -> None:
    """Engines are cached by DSN; clear the cache so each test sees its own mock."""
    from elliot_core.sources import db_connector

    db_connector._engine_cache.clear()


class TestQueryDatabase:
    def test_table_generates_select_sql(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="users")
        engine = _make_engine_mock([{"id": 1, "name": "Alice"}])

        with patch(_PATCH_ENGINE, return_value=engine):
            result = query_database(source, {})

        assert len(result.rows) == 1
        assert result.rows[0]["id"] == 1

    def test_explicit_query_used_when_set(self) -> None:
        from elliot_core.sources.db_connector import query_database

        sql = "SELECT id FROM users WHERE active = 1"
        source = _pg_source(url="postgresql://localhost/test", query=sql)
        engine = _make_engine_mock([{"id": 42}])

        with patch(_PATCH_ENGINE, return_value=engine):
            result = query_database(source, {})

        executed = engine.connect.return_value.execute.call_args[0][0]
        assert "active" in str(executed)
        assert result.rows[0]["id"] == 42

    def test_env_var_dsn_resolved_from_secrets(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="{{ env:DB_URL }}")
        engine = _make_engine_mock([])

        with patch(_PATCH_ENGINE, return_value=engine) as ce:
            query_database(source, {"DB_URL": "postgresql://localhost/resolved"})

        dsn_used = ce.call_args[0][0]
        assert dsn_used == "postgresql://localhost/resolved"

    def test_env_var_dsn_falls_back_to_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from elliot_core.sources.db_connector import query_database

        monkeypatch.setenv("DB_URL", "postgresql://localhost/from-env")
        source = _pg_source(url="{{ env:DB_URL }}")
        engine = _make_engine_mock([])

        with patch(_PATCH_ENGINE, return_value=engine) as ce:
            query_database(source, {})

        assert ce.call_args[0][0] == "postgresql://localhost/from-env"

    def test_missing_dsn_raises_elliot_error(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url=None, table="t")
        with pytest.raises(ElliotError) as exc_info:
            query_database(source, {})
        assert "no connection URL" in str(exc_info.value)

    def test_no_table_or_query_raises_elliot_error(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = SourceConfig(id="db", name="DB", type="postgres", url="postgresql://localhost/x")
        with pytest.raises(ElliotError) as exc_info:
            query_database(source, {})
        assert "no query or table" in str(exc_info.value)

    def test_invalid_sql_raises_elliot_error(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", query="DROP TABLE users")
        with pytest.raises(ElliotError) as exc_info:
            query_database(source, {})
        assert exc_info.value.code == "INVALID_SQL"

    def test_engine_exception_raises_source_fetch_error(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="users")
        engine_mock = MagicMock()
        conn_mock = MagicMock()
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=False)
        conn_mock.execute.side_effect = Exception("connection refused")
        engine_mock.connect.return_value = conn_mock
        engine_mock.dispose = MagicMock()

        with (
            patch(_PATCH_ENGINE, return_value=engine_mock),
            pytest.raises(SourceFetchError, match="Query failed"),
        ):
            query_database(source, {})

    def test_engine_cached_and_reused_across_queries(self) -> None:
        """The Engine is created once per DSN and reused, not rebuilt per query."""
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="users")
        engine = _make_engine_mock([{"id": 1}])

        with patch(_PATCH_ENGINE, return_value=engine) as ce:
            query_database(source, {})
            query_database(source, {})

        ce.assert_called_once()

    def test_create_engine_failure_raises_source_fetch_error(self) -> None:
        """A bad DSN that makes create_engine raise surfaces as SourceFetchError,
        not a NameError from a finally block referencing an unbound engine."""
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="users")

        with (
            patch(_PATCH_ENGINE, side_effect=Exception("bad dsn")),
            pytest.raises(SourceFetchError, match="Query failed"),
        ):
            query_database(source, {})

    def test_mysql_source_uses_same_code_path(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _mysql_source(url="mysql+pymysql://root:pass@localhost/test")
        engine = _make_engine_mock([{"order_id": 99}])

        with patch(_PATCH_ENGINE, return_value=engine):
            result = query_database(source, {})

        assert result.rows[0]["order_id"] == 99

    def test_postgres_uses_read_only_connect_args(self) -> None:
        """Postgres connections must enforce a read-only transaction so any
        write/DDL the validator missed is rejected by the server itself."""
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="users")
        engine = _make_engine_mock([])

        with patch(_PATCH_ENGINE, return_value=engine) as ce:
            query_database(source, {})

        connect_args = ce.call_args.kwargs["connect_args"]
        options = connect_args["options"]
        assert "default_transaction_read_only=on" in options
        assert "statement_timeout=30000" in options

    def test_mysql_uses_read_only_init_command(self) -> None:
        """MySQL must enforce a read-only session (init_command) so a write/DDL
        the validator missed is rejected by MySQL itself — not the Postgres-only
        options string."""
        from elliot_core.sources.db_connector import query_database

        source = _mysql_source(url="mysql+pymysql://root:pass@localhost/test")
        engine = _make_engine_mock([])

        with patch(_PATCH_ENGINE, return_value=engine) as ce:
            query_database(source, {})

        connect_args = ce.call_args.kwargs["connect_args"]
        assert "options" not in connect_args  # not the Postgres options string
        assert connect_args["init_command"] == "SET SESSION TRANSACTION READ ONLY"

    def test_fetch_result_has_fetched_at(self) -> None:
        from elliot_core.sources.db_connector import query_database

        source = _pg_source(url="postgresql://localhost/test", table="t")
        engine = _make_engine_mock([])

        with patch(_PATCH_ENGINE, return_value=engine):
            result = query_database(source, {})

        assert result.fetched_at


class TestRunSelect:
    """run_select pushes a tool's compiled, parameterized SELECT to the DB."""

    def test_rejects_non_select_sql(self) -> None:
        from elliot_core.sources.db_connector import run_select

        source = _pg_source(url="postgresql://localhost/test")
        with pytest.raises(ElliotError) as exc_info:
            run_select(source, {}, "DROP TABLE users", {})
        assert exc_info.value.code == "INVALID_SQL"

    def test_binds_params_to_execute(self) -> None:
        from elliot_core.sources.db_connector import run_select

        source = _pg_source(url="postgresql://localhost/test")
        engine = _make_engine_mock([{"id": 7}])
        with patch(_PATCH_ENGINE, return_value=engine):
            result = run_select(source, {}, 'SELECT * FROM "t" WHERE id = :id', {"id": 7})

        # _run_query passes the bound params as the 2nd positional arg to execute().
        call = engine.connect.return_value.execute.call_args
        assert call[0][1] == {"id": 7}
        assert result.rows[0]["id"] == 7

    def test_returns_fetch_result_for_mysql_source(self) -> None:
        from elliot_core.sources.db_connector import run_select

        source = _mysql_source(url="mysql+pymysql://root:pass@localhost/test")
        engine = _make_engine_mock([{"order_id": 1}, {"order_id": 2}])
        with patch(_PATCH_ENGINE, return_value=engine):
            result = run_select(source, {}, "SELECT * FROM `orders`", None)

        assert len(result.rows) == 2
        assert result.fetched_at
