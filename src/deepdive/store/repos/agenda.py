import sqlite3
from collections.abc import Sequence
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.enums import AgendaItemStatus
from deepdive.store.errors import AgendaItemNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import AgendaItem
from deepdive.store.repos._common import check_session, many, one, require


def replace_items(
    conn: sqlite3.Connection,
    topic_id: UUID,
    facets: Sequence[str],
    *,
    session_id: UUID | None = None,
) -> list[AgendaItem]:
    """Atomically swap the topic's agenda for `facets`, all open, in the order given.

    The schema has no charter-version column, so "items for a charter version" means the topic's
    current agenda; the previous items (and their done status) are dropped.
    """
    with transaction(conn):
        require(conn, "topic", topic_id, TopicNotFoundError)
        check_session(conn, session_id)
        conn.execute("DELETE FROM agenda_item WHERE topic_id = ?", (topic_id,))
        conn.executemany(
            'INSERT INTO agenda_item (id, topic_id, facet, status, "order", session_id)'
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (new_id(), topic_id, facet, AgendaItemStatus.OPEN, i, session_id)
                for i, facet in enumerate(facets, start=1)
            ],
        )
    return list_items(conn, topic_id)


def list_items(conn: sqlite3.Connection, topic_id: UUID) -> list[AgendaItem]:
    return many(conn, AgendaItem, "agenda_item", 'WHERE topic_id = ? ORDER BY "order"', (topic_id,))


def next_open(conn: sqlite3.Connection, topic_id: UUID) -> AgendaItem | None:
    return one(
        conn,
        AgendaItem,
        "agenda_item",
        'WHERE topic_id = ? AND status = ? ORDER BY "order"',
        (topic_id, AgendaItemStatus.OPEN),
    )


def mark_done(
    conn: sqlite3.Connection, item_id: UUID, *, session_id: UUID | None = None
) -> AgendaItem:
    """Mark the item done; `session_id`, when given, becomes the session that last wrote it."""
    require(conn, "agenda_item", item_id, AgendaItemNotFoundError)
    check_session(conn, session_id)
    conn.execute(
        "UPDATE agenda_item SET status = ?, session_id = COALESCE(?, session_id) WHERE id = ?",
        (AgendaItemStatus.DONE, session_id, item_id),
    )
    item = one(conn, AgendaItem, "agenda_item", "WHERE id = ?", (item_id,))
    assert item is not None
    return item
