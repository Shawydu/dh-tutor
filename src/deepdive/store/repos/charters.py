import json
import sqlite3
from collections.abc import Sequence
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.errors import TopicNotFoundError
from deepdive.store.models import Charter
from deepdive.store.repos._common import check_session, many, one, require


def write(
    conn: sqlite3.Connection,
    topic_id: UUID,
    *,
    core_questions: Sequence[str],
    in_scope: Sequence[str],
    parked: Sequence[str],
    done_when: str,
    session_id: UUID | None = None,
) -> Charter:
    """Store a new charter version: 1 for a topic's first, then one more each time."""
    with transaction(conn):
        require(conn, "topic", topic_id, TopicNotFoundError)
        check_session(conn, session_id)
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM charter WHERE topic_id = ?", (topic_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO charter"
            " (topic_id, version, core_questions, in_scope, parked, done_when, session_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                topic_id,
                version,
                json.dumps(list(core_questions)),
                json.dumps(list(in_scope)),
                json.dumps(list(parked)),
                done_when,
                session_id,
            ),
        )
    charter = get_version(conn, topic_id, version)
    assert charter is not None
    return charter


def get_latest(conn: sqlite3.Connection, topic_id: UUID) -> Charter | None:
    return one(conn, Charter, "charter", "WHERE topic_id = ? ORDER BY version DESC", (topic_id,))


def get_version(conn: sqlite3.Connection, topic_id: UUID, version: int) -> Charter | None:
    return one(conn, Charter, "charter", "WHERE topic_id = ? AND version = ?", (topic_id, version))


def list_versions(conn: sqlite3.Connection, topic_id: UUID) -> list[Charter]:
    return many(conn, Charter, "charter", "WHERE topic_id = ? ORDER BY version", (topic_id,))
