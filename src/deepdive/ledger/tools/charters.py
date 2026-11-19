from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import Id, Items, Text, Version
from deepdive.store.errors import CharterNotFoundError


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def charter_write(
        session_id: Id,
        topic_id: Id,
        core_questions: Items,
        in_scope: Items,
        parked: Items,
        done_when: Text,
    ) -> dict[str, Any]:
        """Store a new charter version for the topic (1 first, then one more each time)."""
        return ctx.store.charters.write(
            topic_id,
            core_questions=core_questions,
            in_scope=in_scope,
            parked=parked,
            done_when=done_when,
            session_id=session_id,
        ).model_dump(mode="json")

    @server.tool()
    async def charter_get(topic_id: Id, version: Version | None = None) -> dict[str, Any]:
        """The topic's latest charter, or the given version."""
        ctx.require_topic(topic_id)
        found = (
            ctx.store.charters.get_latest(topic_id)
            if version is None
            else ctx.store.charters.get_version(topic_id, version)
        )
        if found is None:
            which = "has no charter yet" if version is None else f"has no charter version {version}"
            raise CharterNotFoundError(f"topic {topic_id} {which}")
        return found.model_dump(mode="json")
