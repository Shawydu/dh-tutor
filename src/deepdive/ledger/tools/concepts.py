from typing import Annotated, Any

from pydantic import Field

from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Concepts, Id
from deepdive.ledger.tools._common import Tools


class ConceptTools(Tools):
    """Concept tags: what links questions across topics and what knowledge is tracked by."""

    async def concept_tag(
        self, question_id: Id, concepts: Annotated[Concepts, Field(min_length=1)]
    ) -> dict[str, Any]:
        """Tag a stored question (such as the one the question matcher just stored) with 1-4
        concept names: short, general ideas such as "optimistic concurrency", not the topic."""
        with self.ctx.store.db.transaction():
            tagged = self.ctx.store.concepts.tag_question(question_id, concepts, self.ctx.now())
        return {"concepts": [c.model_dump(mode="json") for c in tagged]}

    async def concept_list(self, topic_id: Id | None = None) -> dict[str, Any]:
        """Every concept by name, or those tagged on the topic's questions and claims."""
        if topic_id is not None:
            self.ctx.store.topics.require(topic_id)
        rows = self.ctx.store.concepts.list_all(topic_id)
        return {"concepts": [c.model_dump(mode="json") for c in rows]}

    async def concept_merge(self, a: Id, b: Id) -> dict[str, Any]:
        """Merge concept b into a: b's tags and knowledge move to a, b's name becomes an alias."""
        if a == b:
            raise InvalidInputError("a and b must be different concepts")
        store = self.ctx.store
        with store.db.transaction():
            store.concepts.require(b)
            self.ctx.knowledge.merge_concepts(b, a)
            kept = store.concepts.merge(a, b)
        return kept.model_dump(mode="json")
