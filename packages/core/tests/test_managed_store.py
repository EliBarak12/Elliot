"""Tests for the managed ("elliot") source store — schema, CRUD, row scoping."""

from __future__ import annotations

import pytest

from elliot_core.errors import ElliotError, NotFoundError
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.managed_store import (
    ManagedStore,
    managed_db_path,
    managed_flat_table,
    managed_table_name,
)
from elliot_core.types.source import ManagedColumn, SourceConfig
from elliot_core.user_identity import (
    UserScope,
    managed_owner_id,
    managed_read_owner_ids,
    managed_write_owner_ids,
    reset_current_user_id,
    reset_current_user_scope,
    set_current_user_id,
    set_current_user_scope,
)


def _source(**overrides) -> SourceConfig:
    base = {
        "id": "notes",
        "name": "notes",
        "type": "elliot",
        "table_name": "notes",
        "columns": [
            ManagedColumn(name="title", required=True),
            ManagedColumn(name="done", type="boolean"),
            ManagedColumn(name="priority", type="integer"),
        ],
    }
    base.update(overrides)
    return SourceConfig(**base)


@pytest.fixture
def store() -> ManagedStore:
    s = ManagedStore(":memory:")
    yield s
    s.close()


class TestManagedStoreCrud:
    def test_insert_returns_row_with_system_columns(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "buy milk", "done": True}, "user-a")
        assert row["title"] == "buy milk"
        assert row["done"] == 1
        assert row["_owner_id"] == "user-a"
        assert row["_id"]
        assert row["_created_at"] and row["_updated_at"]

    def test_insert_missing_required_column_rejected(self, store):
        src = _source()
        with pytest.raises(ElliotError) as exc:
            store.insert_row(src, {"done": False}, "user-a")
        assert exc.value.code == "VALIDATION_REQUIRED"

    def test_insert_unknown_column_rejected(self, store):
        src = _source()
        with pytest.raises(ElliotError) as exc:
            store.insert_row(src, {"title": "x", "nope": 1}, "user-a")
        assert exc.value.code == "UNKNOWN_COLUMN"

    def test_update_changes_only_given_columns(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "a", "priority": 1}, "user-a")
        updated = store.update_row(src, row["_id"], {"priority": 2}, ["user-a"])
        assert updated["priority"] == 2
        assert updated["title"] == "a"
        assert updated["_updated_at"] >= row["_updated_at"]

    def test_update_empty_values_rejected(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "a"}, "user-a")
        with pytest.raises(ElliotError):
            store.update_row(src, row["_id"], {}, ["user-a"])

    def test_delete_removes_row(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "a"}, "user-a")
        result = store.delete_row(src, row["_id"], ["user-a"])
        assert result == {"deleted": True, "_id": row["_id"]}
        assert store.read_rows(src, None) == []

    def test_delete_missing_row_raises_not_found(self, store):
        src = _source()
        with pytest.raises(NotFoundError):
            store.delete_row(src, "nope", None)

    def test_non_managed_source_rejected(self, store):
        src = SourceConfig(id="r", name="r", type="rest", url="https://example.com")
        with pytest.raises(ElliotError) as exc:
            store.ensure_table(src)
        assert exc.value.code == "INVALID_SOURCE"

    def test_reserved_column_name_rejected(self, store):
        src = _source(columns=[ManagedColumn(name="_owner_id")])
        with pytest.raises(ElliotError) as exc:
            store.ensure_table(src)
        assert exc.value.code == "INVALID_SOURCE"


class TestRowScoping:
    def test_reads_scoped_to_allowed_owners(self, store):
        src = _source()
        store.insert_row(src, {"title": "mine"}, "user-a")
        store.insert_row(src, {"title": "theirs"}, "user-b")
        assert [r["title"] for r in store.read_rows(src, ["user-a"])] == ["mine"]
        assert [r["title"] for r in store.read_rows(src, ["user-b"])] == ["theirs"]
        # A grant widens the read set.
        assert len(store.read_rows(src, ["user-a", "user-b"])) == 2
        # Unscoped (local single-user mode) sees everything.
        assert len(store.read_rows(src, None)) == 2

    def test_shared_table_ignores_scoping(self, store):
        src = _source(user_scoped=False)
        store.insert_row(src, {"title": "anyone"}, "user-a")
        assert len(store.read_rows(src, ["user-b"])) == 1

    def test_cross_user_update_and_delete_blocked(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "mine"}, "user-a")
        with pytest.raises(NotFoundError):
            store.update_row(src, row["_id"], {"title": "hax"}, ["user-b"])
        with pytest.raises(NotFoundError):
            store.delete_row(src, row["_id"], ["user-b"])
        # The write grant unlocks it.
        assert store.update_row(src, row["_id"], {"title": "ok"}, ["user-b", "user-a"])


class TestSchemaEvolution:
    def test_new_declared_column_added_without_data_loss(self, store):
        src = _source()
        row = store.insert_row(src, {"title": "keep me"}, "user-a")
        evolved = _source(
            columns=[*_source().columns, ManagedColumn(name="tags")],
        )
        store.ensure_table(evolved)
        rows = store.read_rows(evolved, None)
        assert rows[0]["_id"] == row["_id"]
        assert rows[0]["title"] == "keep me"
        assert "tags" in rows[0]


class TestFlatTable:
    def test_managed_flat_table_preserves_store_ids(self, store):
        """The generic flattener renumbers _id; the managed shape must not."""
        src = _source()
        row = store.insert_row(src, {"title": "x", "priority": 3}, "user-a")
        engine = SQLiteEngine()
        try:
            engine.load_result(managed_flat_table(src, store.read_rows(src, None)))
            got = engine.query('SELECT _id, title, priority FROM "notes"')
            assert got == [{"_id": row["_id"], "title": "x", "priority": 3}]
        finally:
            engine.close()

    def test_empty_table_loads_with_full_schema(self):
        src = _source()
        engine = SQLiteEngine()
        try:
            engine.load_result(managed_flat_table(src, []))
            cols = {c["name"] for c in engine.get_table_schema("notes")}
            assert {"_id", "_owner_id", "title", "done", "priority"} <= cols
        finally:
            engine.close()


class TestHelpers:
    def test_managed_table_name_prefers_table_name(self):
        assert managed_table_name(_source()) == "notes"
        assert managed_table_name(_source(table_name=None)) == "notes"

    def test_managed_db_path_env_override(self, monkeypatch):
        monkeypatch.setenv("ELLIOT_MANAGED_DB", "/tmp/custom.db")
        assert managed_db_path() == "/tmp/custom.db"
        monkeypatch.delenv("ELLIOT_MANAGED_DB")
        assert managed_db_path() == ".elliot/managed.db"


class TestUserScopeHelpers:
    def test_unscoped_local_mode(self):
        assert managed_read_owner_ids() is None
        assert managed_write_owner_ids() is None
        assert managed_owner_id() == "local"

    def test_user_id_only_scopes_to_self(self):
        token = set_current_user_id("u1")
        try:
            assert managed_read_owner_ids() == ["u1"]
            assert managed_write_owner_ids() == ["u1"]
            assert managed_owner_id() == "u1"
        finally:
            reset_current_user_id(token)

    def test_full_scope_adds_granted_owners(self):
        scope = UserScope(
            user_id="u1",
            email="u1@example.com",
            readable_owner_ids=("u2", "u3"),
            writable_owner_ids=("u2",),
        )
        token = set_current_user_scope(scope)
        try:
            assert managed_read_owner_ids() == ["u1", "u2", "u3"]
            assert managed_write_owner_ids() == ["u1", "u2"]
            assert managed_owner_id() == "u1"
        finally:
            reset_current_user_scope(token)
