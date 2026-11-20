from typing import Any

from deepdive.ledger.limits import Facets, Id
from deepdive.ledger.tools._common import Tools


class AgendaTools(Tools):
    async def agenda_set(self, session_id: Id, topic_id: Id, facets: Facets) -> dict[str, Any]:
        """Replace the topic's agenda with these facets, all open, in the order given."""
        items = self.ctx.store.agenda.replace_items(topic_id, facets, session_id=session_id)
        return {"items": [i.model_dump(mode="json") for i in items]}

    async def agenda_next(self, topic_id: Id) -> dict[str, Any]:
        """The first open agenda item, or null when every item is done."""
        self.ctx.require_topic(topic_id)
        item = self.ctx.store.agenda.next_open(topic_id)
        return {"item": item.model_dump(mode="json") if item else None}

    async def agenda_done(self, session_id: Id, item_id: Id) -> dict[str, Any]:
        """Mark an agenda item done."""
        return self.ctx.store.agenda.mark_done(item_id, session_id=session_id).model_dump(
            mode="json"
        )
