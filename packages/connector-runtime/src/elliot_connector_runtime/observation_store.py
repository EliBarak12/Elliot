"""SQLAlchemy-backed observation store (SQLite default, MySQL optional)."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

log = structlog.get_logger(__name__)

_RETENTION_DAYS = 30


class _Base(DeclarativeBase):
    pass


class _AgentSession(_Base):
    __tablename__ = "agent_sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(32), unique=True, nullable=False, index=True)
    started_at = Column(Float, nullable=False)
    ended_at = Column(Float)
    agent_hint = Column(String(255))
    connector_slug = Column(String(128))
    total_tool_calls = Column(Integer, default=0)
    total_tokens_estimated = Column(Integer, default=0)
    total_duration_ms = Column(Float, default=0)
    error_count = Column(Integer, default=0)


class _ToolCall(_Base):
    __tablename__ = "tool_calls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(32), index=True)
    ts = Column(Float, nullable=False, index=True)
    tool_id = Column(String(128), nullable=False, index=True)
    arguments = Column(Text)
    result_row_count = Column(Integer, default=0)
    result_token_estimate = Column(Integer, default=0)
    duration_ms = Column(Float, default=0)
    error = Column(Text)
    connector_slug = Column(String(128))


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
        _Base.metadata.create_all(self._engine)
        log.info("observation_store.ready", db_url=db_url.split("@")[-1])

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
        with Session(self._engine) as db:
            db.add(
                _ToolCall(
                    session_id=session_id,
                    ts=time.time(),
                    tool_id=tool_id,
                    arguments=json.dumps(arguments, default=str),
                    result_row_count=result_row_count,
                    result_token_estimate=result_token_estimate,
                    duration_ms=round(duration_ms, 2),
                    error=error,
                    connector_slug=connector_slug,
                )
            )
            db.commit()

    def open_session(
        self,
        session_id: str,
        agent_hint: str | None = None,
        connector_slug: str | None = None,
    ) -> None:
        with Session(self._engine) as db:
            if db.query(_AgentSession).filter_by(session_id=session_id).first() is None:
                db.add(
                    _AgentSession(
                        session_id=session_id,
                        started_at=time.time(),
                        agent_hint=agent_hint,
                        connector_slug=connector_slug,
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

    def prune(self) -> int:
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        with Session(self._engine) as db:
            r1 = db.query(_ToolCall).filter(_ToolCall.ts < cutoff).delete()
            r2 = db.query(_AgentSession).filter(_AgentSession.started_at < cutoff).delete()
            db.commit()
        deleted = r1 + r2
        if deleted:
            log.info("observation_store.pruned", deleted=deleted)
        return deleted


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
