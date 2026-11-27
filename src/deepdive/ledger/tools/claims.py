from typing import Any
from uuid import UUID

from deepdive.domain_packs import DomainPack
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Concepts, Doi, Id, Kind, SourceIds, Summary, Text, Tier, Url
from deepdive.ledger.tools._common import Tools
from deepdive.search.fetch import FetchError, check_url
from deepdive.store.enums import ClaimStatus, EvidenceStance
from deepdive.store.errors import ClaimNotFoundError
from deepdive.store.models import Evidence


class ClaimTools(Tools):
    def __init__(self, ctx: LedgerContext, pack: DomainPack) -> None:
        super().__init__(ctx)
        self.allowlist = pack.fetch_allowlist

    def _with_source(self, row: Evidence) -> dict[str, Any]:
        source = self.ctx.store.sources.get(row.source_id)
        return {
            **row.model_dump(mode="json"),
            "source": source.model_dump(mode="json") if source else None,
        }

    async def source_register(
        self,
        session_id: Id,
        kind: Kind,
        tier: Tier,
        url: Url | None = None,
        doi: Doi | None = None,
    ) -> dict[str, Any]:
        """Register a source by url or doi (one is required). Returns the existing row if known.

        Claims and evidence can only cite a source that is registered here. A url off the domain
        allowlist is refused unless this session opened it with the built-in WebFetch.
        """
        if url and not self.ctx.store.sessions.fetched(session_id, url):
            try:
                check_url(url, self.allowlist)
            except FetchError as exc:
                raise InvalidInputError(
                    f"{url} refused: {exc}; allowlist {self.allowlist}. A page off the allowlist "
                    "can be cited only after opening it with WebFetch in this session"
                ) from exc
        return self.ctx.store.sources.register(
            url=url,
            doi=doi,
            kind=kind,
            tier=tier,
            seen_at=self.ctx.now(),
            session_id=session_id,
        ).model_dump(mode="json")

    async def claim_add(
        self,
        session_id: Id,
        topic_id: Id,
        text: Text,
        source_ids: SourceIds,
        status: ClaimStatus = ClaimStatus.ESTABLISHED,
        stance: EvidenceStance = EvidenceStance.SUPPORTS,
        excerpt_summary: Summary | None = None,
        concepts: Concepts | None = None,
    ) -> dict[str, Any]:
        """Add a claim with one evidence row per source in source_ids, tagged with 1-4 concept
        names.

        Every id must be a registered source, else nothing is written (source_not_found).
        """
        claim = self.ctx.store.claims.add(
            topic_id,
            text,
            source_ids,
            status=status,
            stance=stance,
            excerpt_summary=excerpt_summary,
            session_id=session_id,
        )
        if concepts:  # shortcut: tagged after the claim commits, as Tools._tag
            with self.ctx.store.db.transaction():
                self.ctx.store.concepts.tag_claim(claim.id, concepts)
        rows = self.ctx.store.evidence.list_for_claim(claim.id)
        return {
            "claim": claim.model_dump(mode="json"),
            "evidence": [self._with_source(e) for e in rows],
        }

    async def claim_list(self, topic_id: Id) -> dict[str, Any]:
        """The topic's claims, each with its evidence rows and the sources they cite."""
        self.ctx.store.topics.require(topic_id)
        by_claim: dict[UUID, list[Evidence]] = {}
        for row in self.ctx.store.evidence.list_for_topic(topic_id):
            by_claim.setdefault(row.claim_id, []).append(row)
        return {
            "claims": [
                {
                    **c.model_dump(mode="json"),
                    "evidence": [self._with_source(e) for e in by_claim.get(c.id, [])],
                }
                for c in self.ctx.store.claims.list_for_topic(topic_id)
            ]
        }

    async def claim_set_status(self, claim_id: Id, status: ClaimStatus) -> dict[str, Any]:
        """Clear a weakened claim after reviewing it with the user: set it open or established."""
        if status == ClaimStatus.WEAKENED:
            raise InvalidInputError("only a discovery can weaken a claim; give open or established")
        if self.ctx.store.claims.require(claim_id).status != ClaimStatus.WEAKENED:
            raise InvalidInputError("only a weakened claim can be cleared")
        return self.ctx.store.claims.set_status(claim_id, status).model_dump(mode="json")

    async def evidence_add(
        self,
        session_id: Id,
        claim_id: Id,
        source_id: Id,
        stance: EvidenceStance,
        excerpt_summary: Summary | None = None,
    ) -> dict[str, Any]:
        """Attach a registered source to an existing claim, supporting or weakening it."""
        row = self.ctx.store.evidence.add(
            claim_id, source_id, stance, excerpt_summary, session_id=session_id
        )
        return self._with_source(row)

    async def evidence_list(
        self, claim_id: Id | None = None, topic_id: Id | None = None
    ) -> dict[str, Any]:
        """Evidence rows (with their sources) for one claim, or for every claim of one topic."""
        if (claim_id is None) == (topic_id is None):
            raise InvalidInputError("give exactly one of claim_id or topic_id")
        if claim_id is not None:
            if self.ctx.store.claims.get(claim_id) is None:
                raise ClaimNotFoundError(claim_id)
            rows = self.ctx.store.evidence.list_for_claim(claim_id)
        else:
            assert topic_id is not None
            self.ctx.store.topics.require(topic_id)
            rows = self.ctx.store.evidence.list_for_topic(topic_id)
        return {"evidence": [self._with_source(e) for e in rows]}
