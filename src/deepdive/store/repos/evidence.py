from uuid import UUID

from deepdive.store.enums import EvidenceStance
from deepdive.store.errors import EvidenceNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Evidence
from deepdive.store.repos._common import IdRepo
from deepdive.store.repos.sources import SourceRepo


class EvidenceRepo(IdRepo[Evidence]):
    table = "evidence"
    model = Evidence
    not_found = EvidenceNotFoundError

    def insert(
        self,
        claim_id: UUID,
        source_id: UUID,
        stance: EvidenceStance,
        excerpt_summary: str | None,
        session_id: UUID | None = None,
    ) -> UUID:
        """Check claim and source, then write the row. `ClaimRepo.add` calls this in its own
        transaction, so it must not open one."""
        from deepdive.store.repos.claims import ClaimRepo  # claims.py imports this module

        ClaimRepo(self.conn).require(claim_id)
        SourceRepo(self.conn).require(source_id)
        self._check_session(session_id)
        evidence_id = new_id()
        self.conn.execute(
            "INSERT INTO evidence (id, claim_id, source_id, stance, excerpt_summary, session_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (evidence_id, claim_id, source_id, stance, excerpt_summary, session_id),
        )
        return evidence_id

    def add(
        self,
        claim_id: UUID,
        source_id: UUID,
        stance: EvidenceStance,
        excerpt_summary: str | None = None,
        session_id: UUID | None = None,
    ) -> Evidence:
        """Attach a source to an existing claim, for or against it."""
        evidence = self.get(self.insert(claim_id, source_id, stance, excerpt_summary, session_id))
        assert evidence is not None
        return evidence

    def list_for_claim(self, claim_id: UUID) -> list[Evidence]:
        return self._many("WHERE claim_id = ? ORDER BY id", (claim_id,))

    def list_for_topic(self, topic_id: UUID) -> list[Evidence]:
        return self._many(
            "JOIN claim ON claim.id = evidence.claim_id"
            " WHERE claim.topic_id = ? ORDER BY evidence.id",
            (topic_id,),
        )
