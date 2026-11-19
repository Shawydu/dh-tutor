from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Doi, Id, Kind, SourceIds, Summary, Text, Tier, Url
from deepdive.store.enums import ClaimStatus, EvidenceStance
from deepdive.store.errors import ClaimNotFoundError
from deepdive.store.models import Evidence


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    def with_source(row: Evidence) -> dict[str, Any]:
        source = ctx.store.sources.get(row.source_id)
        return {
            **row.model_dump(mode="json"),
            "source": source.model_dump(mode="json") if source else None,
        }

    @server.tool()
    async def source_register(
        session_id: Id,
        kind: Kind,
        tier: Tier,
        url: Url | None = None,
        doi: Doi | None = None,
    ) -> dict[str, Any]:
        """Register a source by url or doi (one is required). Returns the existing row if known.

        Claims and evidence can only cite a source that is registered here.
        """
        return ctx.store.sources.register(
            url=url,
            doi=doi,
            kind=kind,
            tier=tier,
            seen_at=ctx.now(),
            session_id=session_id,
        ).model_dump(mode="json")

    @server.tool()
    async def claim_add(
        session_id: Id,
        topic_id: Id,
        text: Text,
        source_ids: SourceIds,
        status: ClaimStatus = ClaimStatus.ESTABLISHED,
        stance: EvidenceStance = EvidenceStance.SUPPORTS,
        excerpt_summary: Summary | None = None,
    ) -> dict[str, Any]:
        """Add a claim with one evidence row per source in source_ids.

        Every id must be a registered source, else nothing is written (source_not_found).
        """
        claim = ctx.store.claims.add(
            topic_id,
            text,
            source_ids,
            status=status,
            stance=stance,
            excerpt_summary=excerpt_summary,
            session_id=session_id,
        )
        rows = ctx.store.evidence.list_for_claim(claim.id)
        return {"claim": claim.model_dump(mode="json"), "evidence": [with_source(e) for e in rows]}

    @server.tool()
    async def claim_list(topic_id: Id) -> dict[str, Any]:
        """The topic's claims, each with its evidence rows and the sources they cite."""
        ctx.require_topic(topic_id)
        by_claim: dict[UUID, list[Evidence]] = {}
        for row in ctx.store.evidence.list_for_topic(topic_id):
            by_claim.setdefault(row.claim_id, []).append(row)
        return {
            "claims": [
                {
                    **c.model_dump(mode="json"),
                    "evidence": [with_source(e) for e in by_claim.get(c.id, [])],
                }
                for c in ctx.store.claims.list_for_topic(topic_id)
            ]
        }

    @server.tool()
    async def evidence_add(
        session_id: Id,
        claim_id: Id,
        source_id: Id,
        stance: EvidenceStance,
        excerpt_summary: Summary | None = None,
    ) -> dict[str, Any]:
        """Attach a registered source to an existing claim, supporting or weakening it."""
        row = ctx.store.evidence.add(
            claim_id, source_id, stance, excerpt_summary, session_id=session_id
        )
        return with_source(row)

    @server.tool()
    async def evidence_list(
        claim_id: Id | None = None, topic_id: Id | None = None
    ) -> dict[str, Any]:
        """Evidence rows (with their sources) for one claim, or for every claim of one topic."""
        if (claim_id is None) == (topic_id is None):
            raise InvalidInputError("give exactly one of claim_id or topic_id")
        if claim_id is not None:
            if ctx.store.claims.get(claim_id) is None:
                raise ClaimNotFoundError(claim_id)
            rows = ctx.store.evidence.list_for_claim(claim_id)
        else:
            assert topic_id is not None
            ctx.require_topic(topic_id)
            rows = ctx.store.evidence.list_for_topic(topic_id)
        return {"evidence": [with_source(e) for e in rows]}
