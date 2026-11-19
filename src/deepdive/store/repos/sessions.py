import sqlite3
from datetime import datetime
from uuid import UUID

from deepdive.store.errors import (
    AgendaItemNotFoundError,
    QuestionNotFoundError,
    SessionNotFoundError,
    TopicNotFoundError,
)
from deepdive.store.ids import new_id
from deepdive.store.models import Bookmark, Session
from deepdive.store.repos._common import many, one, require


def start(conn: sqlite3.Connection, topic_id: UUID, *, at: datetime) -> Session:
    """Open a session for the topic; `at` is an aware datetime (the store never reads the clock)."""
    require(conn, "topic", topic_id, TopicNotFoundError)
    session_id = new_id()
    conn.execute(
        "INSERT INTO session (id, topic_id, started_at) VALUES (?, ?, ?)",
        (session_id, topic_id, at),
    )
    return _must_get(conn, session_id)


def get(conn: sqlite3.Connection, session_id: UUID) -> Session | None:
    return one(conn, Session, "session", "WHERE id = ?", (session_id,))


def _must_get(conn: sqlite3.Connection, session_id: UUID) -> Session:
    session = get(conn, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    return session


def bookmark(
    conn: sqlite3.Connection,
    session_id: UUID,
    *,
    agenda_item_id: UUID | None = None,
    question_id: UUID | None = None,
    note: str | None = None,
) -> Session:
    """Replace the session's bookmark with exactly these fields."""
    require(conn, "session", session_id, SessionNotFoundError)
    if agenda_item_id is not None:
        require(conn, "agenda_item", agenda_item_id, AgendaItemNotFoundError)
    if question_id is not None:
        require(conn, "question", question_id, QuestionNotFoundError)
    mark = Bookmark(agenda_item_id=agenda_item_id, question_id=question_id, note=note)
    conn.execute(
        "UPDATE session SET bookmark = ? WHERE id = ?", (mark.model_dump_json(), session_id)
    )
    return _must_get(conn, session_id)


def end(conn: sqlite3.Connection, session_id: UUID, summary: str, *, at: datetime) -> Session:
    require(conn, "session", session_id, SessionNotFoundError)
    conn.execute(
        "UPDATE session SET ended_at = ?, summary = ? WHERE id = ?", (at, summary, session_id)
    )
    return _must_get(conn, session_id)


def latest(conn: sqlite3.Connection, topic_id: UUID, *, recorded: bool = False) -> Session | None:
    """The newest session; with `recorded`, the newest that has a summary or a bookmark."""
    where = "AND (summary IS NOT NULL OR bookmark IS NOT NULL) " if recorded else ""
    return one(
        conn,
        Session,
        "session",
        f"WHERE topic_id = ? {where}ORDER BY started_at DESC, id DESC",
        (topic_id,),
    )


def list_for_topic(conn: sqlite3.Connection, topic_id: UUID) -> list[Session]:
    """Every session of the topic, oldest first."""
    return many(conn, Session, "session", "WHERE topic_id = ? ORDER BY started_at, id", (topic_id,))
