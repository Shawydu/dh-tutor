from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import Facets, Id


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def agenda_set(session_id: Id, topic_id: Id, facets: Facets) -> dict[str, Any]:
        """Replace the topic's agenda with these facets, all open, in the order given."""
        items = ctx.store.agenda.replace_items(topic_id, facets, session_id=session_id)
        return {"items": [i.model_dump(mode="json") for i in items]}

    @server.tool()
    async def agenda_next(topic_id: Id) -> dict[str, Any]:
        """The first open agenda item, or null when every item is done."""
        ctx.require_topic(topic_id)
        item = ctx.store.agenda.next_open(topic_id)
        return {"item": item.model_dump(mode="json") if item else None}

    @server.tool()
    async def agenda_done(session_id: Id, item_id: Id) -> dict[str, Any]:
        """Mark an agenda item done."""
        return ctx.store.agenda.mark_done(item_id, session_id=session_id).model_dump(mode="json")
