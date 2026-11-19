from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import Id, Note, Summary


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def session_start(topic_id: Id) -> dict[str, Any]:
        """Open a session on a topic. Pass the returned id as session_id to the write tools."""
        return ctx.store.sessions.start(topic_id, at=ctx.now()).model_dump(mode="json")

    @server.tool()
    async def session_bookmark(
        session_id: Id,
        agenda_item_id: Id | None = None,
        question_id: Id | None = None,
        note: Note | None = None,
    ) -> dict[str, Any]:
        """Record where the session left off. Replaces the previous bookmark."""
        return ctx.store.sessions.bookmark(
            session_id,
            agenda_item_id=agenda_item_id,
            question_id=question_id,
            note=note,
        ).model_dump(mode="json")

    @server.tool()
    async def session_end(session_id: Id, summary: Summary) -> dict[str, Any]:
        """Close the session with a short summary of what happened."""
        return ctx.store.sessions.end(session_id, summary, at=ctx.now()).model_dump(mode="json")
