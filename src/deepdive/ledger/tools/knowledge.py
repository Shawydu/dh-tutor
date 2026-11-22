"""MCP tools for the knowledge model: knowledge_view and self_rate."""

from typing import Any

from deepdive.knowledge.update import record
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import ConceptName, Id, Level
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import KnowledgeEvidenceKind


class KnowledgeTools(Tools):
    """What the engine thinks the user knows, and the user's own say in it."""

    async def knowledge_view(self, topic_id: Id | None = None) -> dict[str, Any]:
        """Concepts with knowledge, by name: level (0-4), confidence (0-1), next_recap_at and
        last_evidence_at. With topic_id, only the topic's concepts."""
        if topic_id is not None:
            self.ctx.store.topics.require(topic_id)
        rows = []
        for c in self.ctx.store.concepts.list_all(topic_id):
            if s := self.ctx.knowledge.get_state(c.id):
                rows.append(
                    {"concept": c.name, "level": round(s.level, 1)}
                    | {"confidence": round(s.confidence, 2)}
                    | s.model_dump(mode="json", include={"next_recap_at", "last_evidence_at"})
                )
        return {"concepts": rows}

    async def self_rate(self, concept: ConceptName, level: Level) -> dict[str, Any]:
        """Record the user's own rating of a concept, 0 (none) to 4 (expert): "I know X well".
        The name is normalised like concept_tag's and created when new. It counts less than a
        graded answer."""
        # shortcut: self-rated concepts have no topic link, so topic views and resume recaps skip
        # them until a question or claim tags them; add a concept-topic link if that bites
        with self.ctx.store.db.transaction():
            found = self.ctx.store.concepts.ensure([concept])
            if not found:
                raise InvalidInputError("concept must not be blank")
            record(
                self.ctx.knowledge, found[0].id, KnowledgeEvidenceKind.SELF_RATING,
                self.ctx.now(), level=level,
            )  # fmt: skip
        return {"concept": found[0].name, "level": level}
