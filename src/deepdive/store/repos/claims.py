from collections.abc import Sequence
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.enums import ClaimStatus, EvidenceStance
from deepdive.store.errors import ClaimNotFoundError, SourceRequiredError
from deepdive.store.ids import new_id
from deepdive.store.models import Claim
from deepdive.store.repos._common import IdRepo
from deepdive.store.repos.evidence import EvidenceRepo
from deepdive.store.repos.topics import TopicRepo


class ClaimRepo(IdRepo[Claim]):
    table = "claim"
    model = Claim
    not_found = ClaimNotFoundError

    def add(
        self,
        topic_id: UUID,
        text: str,
        source_ids: Sequence[UUID],
        *,
        status: ClaimStatus = ClaimStatus.ESTABLISHED,
        stance: EvidenceStance = EvidenceStance.SUPPORTS,
        excerpt_summary: str | None = None,
        session_id: UUID | None = None,
    ) -> Claim:
        """Add a claim with one evidence row per source, all or nothing.

        The design links claims to sources only through evidence, so a claim that must cite a real
        source (invariant 2) is created together with its first evidence rows.
        """
        if not source_ids:
            raise SourceRequiredError("a claim must cite at least one source")
        with transaction(self.conn):
            TopicRepo(self.conn).require(topic_id)
            self._check_session(session_id)
            claim_id = new_id()
            self.conn.execute(
                "INSERT INTO claim (id, topic_id, text, status, session_id) VALUES (?, ?, ?, ?, ?)",
                (claim_id, topic_id, text, status, session_id),
            )
            evidence = EvidenceRepo(self.conn)
            for source_id in dict.fromkeys(source_ids):
                evidence.insert(claim_id, source_id, stance, excerpt_summary, session_id)
        claim = self.get(claim_id)
        assert claim is not None
        return claim

    def list_for_topic(self, topic_id: UUID) -> list[Claim]:
        return self._many("WHERE topic_id = ? ORDER BY id", (topic_id,))
