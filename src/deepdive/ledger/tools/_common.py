"""The base class the tool classes share: the context, tool registration, shared helpers."""

import inspect
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext


class Tools:
    """A group of ledger tools: every public `async def` a subclass itself defines is one MCP tool.

    Tool classes subclass `Tools` directly; tools inherited from a further subclass are not seen.
    """

    def __init__(self, ctx: LedgerContext) -> None:
        self.ctx = ctx

    def register(self, server: MCPServer[None]) -> None:
        # vars() keeps definition order and skips inherited members
        for name, member in vars(type(self)).items():
            if not name.startswith("_") and inspect.iscoroutinefunction(member):
                server.tool()(getattr(self, name))

    def _claims_with_sources(self, topic_id: UUID) -> list[dict[str, Any]]:
        """The topic's claims, each with its cited sources as `{id, url}`."""
        store = self.ctx.store
        cited: dict[str, dict[str, dict[str, str | None]]] = {}
        for e in store.evidence.list_for_topic(topic_id):
            s = store.sources.get(e.source_id)
            sid = str(e.source_id)
            cited.setdefault(str(e.claim_id), {})[sid] = {"id": sid, "url": s.url if s else None}
        return [
            {
                "id": str(c.id),
                "text": c.text,
                "status": c.status,
                "sources": list(cited.get(str(c.id), {}).values()),
            }
            for c in store.claims.list_for_topic(topic_id)
        ]
