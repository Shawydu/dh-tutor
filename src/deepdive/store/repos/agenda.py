from collections.abc import Sequence
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.enums import AgendaItemStatus
from deepdive.store.errors import AgendaItemNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import AgendaItem
from deepdive.store.repos._common import IdRepo
from deepdive.store.repos.topics import TopicRepo


class AgendaRepo(IdRepo[AgendaItem]):
    table = "agenda_item"
    model = AgendaItem
    not_found = AgendaItemNotFoundError

    def replace_items(
        self, topic_id: UUID, facets: Sequence[str], *, session_id: UUID | None = None
    ) -> list[AgendaItem]:
        """Atomically swap the topic's agenda for `facets`, all open, in the order given.

        The schema has no charter-version column, so "items for a charter version" means the
        topic's current agenda; the previous items (and their done status) are dropped.
        """
        with transaction(self.conn):
            TopicRepo(self.conn).require(topic_id)
            self._check_session(session_id)
            self.conn.execute("DELETE FROM agenda_item WHERE topic_id = ?", (topic_id,))
            self.conn.executemany(
                'INSERT INTO agenda_item (id, topic_id, facet, status, "order", session_id)'
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (new_id(), topic_id, facet, AgendaItemStatus.OPEN, i, session_id)
                    for i, facet in enumerate(facets, start=1)
                ],
            )
        return self.list_items(topic_id)

    def list_items(self, topic_id: UUID) -> list[AgendaItem]:
        return self._many('WHERE topic_id = ? ORDER BY "order"', (topic_id,))

    def next_open(self, topic_id: UUID) -> AgendaItem | None:
        return self._one(
            'WHERE topic_id = ? AND status = ? ORDER BY "order"', (topic_id, AgendaItemStatus.OPEN)
        )

    def mark_done(self, item_id: UUID, *, session_id: UUID | None = None) -> AgendaItem:
        """Mark the item done; `session_id`, when given, becomes the session that last wrote it."""
        self.require(item_id)
        self._check_session(session_id)
        self.conn.execute(
            "UPDATE agenda_item SET status = ?, session_id = COALESCE(?, session_id) WHERE id = ?",
            (AgendaItemStatus.DONE, session_id, item_id),
        )
        item = self.get(item_id)
        assert item is not None
        return item
