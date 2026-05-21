"""SQLAlchemy-backed observation store (SQLite default, MySQL optional)."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from sqlalchemy import Column, Float, Integer, String, Text, create_engine, event, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

log = structlog.get_logger(__name__)

_RETENTION_DAYS = 30


class _Base(DeclarativeBase):
    pass


class _AgentSession(_Base):
    __tablename__ = "agent_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), unique=True, nullable=False, index=True)
    started_at = Column(Float, nullable=False)
    ended_at = Column(Float)
    agent_hint = Column(String(255))
    agent_client = Column(String(64), index=True)
    agent_client_version = Column(String(64))
    agent_model = Column(String(128), index=True)
    agent_modality = Column(String(64))
    user_agent = Column(String(512))
    connector_slug = Column(String(128))
    total_tool_calls = Column(Integer, default=0)
    total_tokens_estimated = Column(Integer, default=0)
    total_duration_ms = Column(Float, default=0)
    error_count = Column(Integer, default=0)


class _ToolCall(_Base):
    __tablename__ = "tool_calls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), index=True)
    ts = Column(Float, nullable=False, index=True)
    tool_id = Column(String(128), nullable=False, index=True)
    arguments = Column(Text)
    result_row_count = Column(Integer, default=0)
    result_token_estimate = Column(Integer, default=0)
    duration_ms = Column(Float, default=0)
    error = Column(Text)
    connector_slug = Column(String(128))


class _AgentFeedback(_Base):
    """Free-form feedback an agent submits about a connector's tools.

    Written by the built-in ``elliot_feedback`` tool exposed on every running
    connector. Lets the connector author see, per tool, why the agent chose it,
    what it passed and got back, and whether the call succeeded or failed.
    """

    __tablename__ = "agent_feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), index=True)
    ts = Column(Float, nullable=False, index=True)
    connector_slug = Column(String(128), index=True)
    tool_id = Column(String(128), index=True)
    outcome = Column(String(32), index=True)  # success | failure | partial
    why_chosen = Column(Text)
    input_summary = Column(Text)
    output_summary = Column(Text)
    detail = Column(Text)
    agent_client = Column(String(64))
    agent_model = Column(String(128))


class ObservationStore:
    """
    Dual-backend store: SQLite (default) or MySQL via ELLIOT_DB_URL.

    SQLite:  ObservationStore()  or  ObservationStore("sqlite:///path/to/obs.db")
    MySQL:   ObservationStore("mysql+pymysql://user:pass@host:3306/elliot")
    """

    def __init__(self, db_url: str = "sqlite:///.elliot/observations.db") -> None:
        connect_args: dict[str, Any] = (
            {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        )
        self._engine = create_engine(
            db_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if db_url.startswith("sqlite"):
            _enable_sqlite_concurrency(self._engine)
        _Base.metadata.create_all(self._engine)
        self._migrate_agent_identity_columns()
        log.info("observation_store.ready", db_url=db_url.split("@")[-1])

    def _migrate_agent_identity_columns(self) -> None:
        """Add the structured-identity columns to pre-existing databases.

        SQLAlchemy ``create_all`` is idempotent for missing tables but does
        not retro-fit columns onto a table that already exists, so an Elliot
        deployment upgraded across this change would otherwise miss the new
        ``agent_client`` / ``agent_model`` columns and silently lose data.
        """
        inspector = sa_inspect(self._engine)
        if "agent_sessions" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("agent_sessions")}
        additions = [
            ("agent_client", "VARCHAR(64)"),
            ("agent_client_version", "VARCHAR(64)"),
            ("agent_model", "VARCHAR(128)"),
            ("agent_modality", "VARCHAR(64)"),
            ("user_agent", "VARCHAR(512)"),
        ]
        with self._engine.begin() as conn:
            for col_name, col_type in additions:
                if col_name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE agent_sessions ADD COLUMN {col_name} {col_type}")
                    )

    # ------------------------------------------------------------------ writes

    def write_tool_call(
        self,
        session_id: str | None,
        tool_id: str,
        arguments: dict[str, Any],
        result_row_count: int,
        result_token_estimate: int,
        duration_ms: float,
        error: str | None = None,
        connector_slug: str | None = None,
    ) -> None:
        # Redact secret-bearing argument fields before persisting — same
        # policy as AuditLog.record and SessionTracker.record_tool_call, so
        # the observation DB never holds raw API keys / tokens.
        from elliot_core.redaction import redact_audit_arguments

        with Session(self._engine) as db:
            db.add(
                _ToolCall(
                    session_id=session_id,
                    ts=time.time(),
                    tool_id=tool_id,
                    arguments=json.dumps(redact_audit_arguments(arguments), default=str),
                    result_row_count=result_row_count,
                    result_token_estimate=result_token_estimate,
                    duration_ms=round(duration_ms, 2),
                    error=error,
                    connector_slug=connector_slug,
                )
            )
            db.commit()

    def write_feedback(
        self,
        tool_id: str,
        outcome: str,
        session_id: str | None = None,
        connector_slug: str | None = None,
        why_chosen: str = "",
        input_summary: str = "",
        output_summary: str = "",
        detail: str = "",
        agent_identity: dict[str, Any] | None = None,
    ) -> None:
        identity = agent_identity or {}
        with Session(self._engine) as db:
            db.add(
                _AgentFeedback(
                    session_id=session_id,
                    ts=time.time(),
                    connector_slug=connector_slug,
                    tool_id=tool_id,
                    outcome=outcome,
                    why_chosen=why_chosen or None,
                    input_summary=input_summary or None,
                    output_summary=output_summary or None,
                    detail=detail or None,
                    agent_client=identity.get("client"),
                    agent_model=identity.get("model"),
                )
            )
            db.commit()
        log.info("agent_feedback.written", tool_id=tool_id, outcome=outcome)

    def open_session(
        self,
        session_id: str,
        agent_hint: str | None = None,
        connector_slug: str | None = None,
        agent_identity: dict[str, Any] | None = None,
    ) -> None:
        identity = agent_identity or {}
        with Session(self._engine) as db:
            if db.query(_AgentSession).filter_by(session_id=session_id).first() is None:
                db.add(
                    _AgentSession(
                        session_id=session_id,
                        started_at=time.time(),
                        agent_hint=agent_hint,
                        connector_slug=connector_slug,
                        agent_client=identity.get("client"),
                        agent_client_version=identity.get("client_version"),
                        agent_model=identity.get("model"),
                        agent_modality=identity.get("modality"),
                        user_agent=identity.get("user_agent"),
                    )
                )
                db.commit()

    def close_session(self, session_id: str) -> None:
        with Session(self._engine) as db:
            session = db.query(_AgentSession).filter_by(session_id=session_id).first()
            if session is None:
                return
            calls = db.query(_ToolCall).filter_by(session_id=session_id).all()
            n_calls = len([c for c in calls if not c.error])
            tok_sum = sum(int(c.result_token_estimate or 0) for c in calls)
            dur_sum = sum(float(c.duration_ms or 0) for c in calls)
            err_sum = sum(1 for c in calls if c.error is not None)
            session.ended_at = time.time()  # type: ignore[assignment]
            session.total_tool_calls = n_calls  # type: ignore[assignment]
            session.total_tokens_estimated = tok_sum  # type: ignore[assignment]
            session.total_duration_ms = dur_sum  # type: ignore[assignment]
            session.error_count = err_sum  # type: ignore[assignment]
            db.commit()
        log.info("session.closed_to_store", session_id=session_id)

    # ------------------------------------------------------------------ reads

    def recent_sessions(self, n: int = 20) -> list[dict[str, Any]]:
        with Session(self._engine) as db:
            rows = db.query(_AgentSession).order_by(_AgentSession.started_at.desc()).limit(n).all()
        return [_row_to_dict(r) for r in rows]

    def recent_tool_calls(self, n: int = 100, tool_id: str | None = None) -> list[dict[str, Any]]:
        with Session(self._engine) as db:
            q = db.query(_ToolCall).order_by(_ToolCall.ts.desc())
            if tool_id:
                q = q.filter(_ToolCall.tool_id == tool_id)
            rows = q.limit(n).all()
        return [_row_to_dict(r) for r in rows]

    def recent_feedback(
        self, n: int = 50, connector_slug: str | None = None
    ) -> list[dict[str, Any]]:
        with Session(self._engine) as db:
            q = db.query(_AgentFeedback).order_by(_AgentFeedback.ts.desc())
            if connector_slug:
                q = q.filter(_AgentFeedback.connector_slug == connector_slug)
            rows = q.limit(n).all()
        return [_row_to_dict(r) for r in rows]

    def token_efficiency(self) -> list[dict[str, Any]]:
        with Session(self._engine) as db:
            rows = db.execute(
                text("""
                    SELECT
                        tool_id,
                        COUNT(*)                                          AS call_count,
                        AVG(result_token_estimate)                        AS avg_tokens,
                        MAX(result_token_estimate)                        AS max_tokens,
                        AVG(duration_ms)                                  AS avg_duration_ms,
                        SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS error_count
                    FROM tool_calls
                    GROUP BY tool_id
                    ORDER BY avg_tokens DESC
                """)
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    # --------------------------------------------------------------- retention

    def harness_breakdown(self) -> list[dict[str, Any]]:
        """Aggregate tool calls by the agent harness that made them.

        Joins ``tool_calls`` to ``agent_sessions`` on ``session_id`` so the
        Metrics page can compare how Claude Code / Codex / Cursor (and plain
        MCP traffic) each use the connector.
        """
        with Session(self._engine) as db:
            rows = db.execute(
                text("""
                    SELECT
                        COALESCE(s.agent_client, 'unknown')               AS harness,
                        COUNT(DISTINCT t.session_id)                       AS sessions,
                        COUNT(*)                                           AS tool_calls,
                        SUM(CASE WHEN t.error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
                        COALESCE(SUM(t.result_token_estimate), 0)          AS tokens,
                        AVG(t.duration_ms)                                 AS avg_duration_ms
                    FROM tool_calls t
                    LEFT JOIN agent_sessions s ON s.session_id = t.session_id
                    GROUP BY harness
                    ORDER BY tool_calls DESC
                """)
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def prune(self) -> int:
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        with Session(self._engine) as db:
            r1 = db.query(_ToolCall).filter(_ToolCall.ts < cutoff).delete()
            r2 = db.query(_AgentSession).filter(_AgentSession.started_at < cutoff).delete()
            r3 = db.query(_AgentFeedback).filter(_AgentFeedback.ts < cutoff).delete()
            db.commit()
        deleted = r1 + r2 + r3
        if deleted:
            log.info("observation_store.pruned", deleted=deleted)
        return deleted


def _enable_sqlite_concurrency(engine: Engine) -> None:
    """Put SQLite into WAL mode with a busy timeout.

    The default rollback journal serializes readers against a writer and
    fails a contended write immediately with "database is locked". WAL lets
    readers and a writer proceed concurrently; busy_timeout makes a blocked
    writer wait instead of erroring — both are needed once the FastMCP
    threadpool drives concurrent writes.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
