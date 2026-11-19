import sqlite3
from uuid import UUID

from deepdive.store.enums import TopicStatus
from deepdive.store.errors import ChildDepthError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Topic, TopicNode, TopicOverview, TopicStats
from deepdive.store.repos._common import many, one, require


def _check_parent(conn: sqlite3.Connection, parent_id: UUID) -> None:
    parent = get(conn, parent_id)
    if parent is None:
        raise TopicNotFoundError(parent_id)
    if parent.parent_topic_id is not None:
        raise ChildDepthError(
            f"topic {parent_id} is itself a child; child topics are one level deep"
        )


def create(
    conn: sqlite3.Connection,
    title: str,
    *,
    parent_topic_id: UUID | None = None,
    status: TopicStatus = TopicStatus.SCOPING,
) -> Topic:
    if parent_topic_id is not None:
        _check_parent(conn, parent_topic_id)
    topic_id = new_id()
    try:
        conn.execute(
            "INSERT INTO topic (id, title, parent_topic_id, status) VALUES (?, ?, ?, ?)",
            (topic_id, title, parent_topic_id, status),
        )
    except sqlite3.IntegrityError as err:
        if "one level deep" in str(err):  # the trigger, if a concurrent write beat the check
            raise ChildDepthError(str(err)) from err
        raise
    return _must_get(conn, topic_id)


def get(conn: sqlite3.Connection, topic_id: UUID) -> Topic | None:
    return one(conn, Topic, "topic", "WHERE id = ?", (topic_id,))


def _must_get(conn: sqlite3.Connection, topic_id: UUID) -> Topic:
    topic = get(conn, topic_id)
    if topic is None:
        raise TopicNotFoundError(topic_id)
    return topic


def list_all(conn: sqlite3.Connection) -> list[TopicNode]:
    """Top-level topics (pinned first), each with its children."""
    children: dict[UUID, list[Topic]] = {}
    for child in many(conn, Topic, "topic", "WHERE parent_topic_id IS NOT NULL ORDER BY id"):
        assert child.parent_topic_id is not None
        children.setdefault(child.parent_topic_id, []).append(child)
    roots = many(conn, Topic, "topic", "WHERE parent_topic_id IS NULL ORDER BY pinned DESC, id")
    return [TopicNode(**t.model_dump(), children=children.get(t.id, [])) for t in roots]


def set_status(conn: sqlite3.Connection, topic_id: UUID, status: TopicStatus) -> Topic:
    require(conn, "topic", topic_id, TopicNotFoundError)
    conn.execute("UPDATE topic SET status = ? WHERE id = ?", (status, topic_id))
    return _must_get(conn, topic_id)


def _set_pinned(conn: sqlite3.Connection, topic_id: UUID, pinned: bool) -> Topic:
    require(conn, "topic", topic_id, TopicNotFoundError)
    conn.execute("UPDATE topic SET pinned = ? WHERE id = ?", (int(pinned), topic_id))
    return _must_get(conn, topic_id)


def pin(conn: sqlite3.Connection, topic_id: UUID) -> Topic:
    return _set_pinned(conn, topic_id, True)


def unpin(conn: sqlite3.Connection, topic_id: UUID) -> Topic:
    return _set_pinned(conn, topic_id, False)


def overview(conn: sqlite3.Connection) -> list[TopicOverview]:
    """Top-level topics (pinned first) with per-topic counts and their children, in one query."""
    rows = conn.execute(
        "SELECT id, title, parent_topic_id, status, pinned,"
        " (SELECT MAX(version) FROM charter WHERE topic_id = t.id),"
        " (SELECT COUNT(*) FROM agenda_item WHERE topic_id = t.id AND status = 'done'),"
        " (SELECT COUNT(*) FROM agenda_item WHERE topic_id = t.id),"
        " (SELECT COUNT(*) FROM question WHERE topic_id = t.id AND status = 'open'),"
        " (SELECT COUNT(*) FROM question WHERE topic_id = t.id AND status = 'parked'),"
        " (SELECT MAX(started_at) FROM session WHERE topic_id = t.id)"
        " FROM topic t ORDER BY pinned DESC, id"
    ).fetchall()
    stats = [
        TopicStats.model_validate(dict(zip(TopicStats.model_fields, r, strict=True))) for r in rows
    ]
    children: dict[UUID, list[TopicStats]] = {}
    for s in stats:
        if s.parent_topic_id is not None:
            children.setdefault(s.parent_topic_id, []).append(s)
    return [
        TopicOverview(**s.model_dump(), children=children.get(s.id, []))
        for s in stats
        if s.parent_topic_id is None
    ]
