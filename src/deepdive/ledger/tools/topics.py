from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import Id, Title
from deepdive.store.repos import topics


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def topic_create(title: Title, parent_topic_id: Id | None = None) -> dict[str, Any]:
        """Create a topic. A child topic names a top-level parent; children are one level deep."""
        return topics.create(ctx.conn, title, parent_topic_id=parent_topic_id).model_dump(
            mode="json"
        )

    @server.tool()
    async def topic_get(topic_id: Id) -> dict[str, Any]:
        """One topic: id, title, parent_topic_id, status, pinned."""
        ctx.require_topic(topic_id)
        topic = topics.get(ctx.conn, topic_id)
        assert topic is not None
        return topic.model_dump(mode="json")

    @server.tool()
    async def topic_list() -> dict[str, Any]:
        """Top-level topics (pinned first), each with its child topics."""
        return {"topics": [t.model_dump(mode="json") for t in topics.list_all(ctx.conn)]}

    @server.tool()
    async def topic_pin(topic_id: Id, pinned: bool) -> dict[str, Any]:
        """Pin a topic to the top of the list, or unpin it."""
        pin = topics.pin if pinned else topics.unpin
        return pin(ctx.conn, topic_id).model_dump(mode="json")
