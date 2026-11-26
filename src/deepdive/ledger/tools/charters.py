from typing import Any

from deepdive.ledger.limits import Id, Items, SearchTerms, Text, Version
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import CharterDriver
from deepdive.store.errors import CharterNotFoundError


class CharterTools(Tools):
    async def charter_write(
        self,
        session_id: Id,
        topic_id: Id,
        core_questions: Items,
        in_scope: Items,
        parked: Items,
        done_when: Text,
        search_terms: SearchTerms | None = None,
        driver: CharterDriver | None = None,
        decision_choice: Text | None = None,
        decision_reasons: Text | None = None,
    ) -> dict[str, Any]:
        """Store a new charter version for the topic (1 first, then one more each time).
        search_terms: up to two words every web search for this topic must contain.
        driver: what drives the topic (decision, curiosity, interview, other). For a decision, the
        learner's own choice and reasons go in decision_choice and decision_reasons. Left out, all
        three carry over from the previous version."""
        prev = self.ctx.store.charters.get_latest(topic_id)
        if prev is not None:
            driver = driver or prev.driver
            decision_choice = decision_choice or prev.decision_choice
            decision_reasons = decision_reasons or prev.decision_reasons
        return self.ctx.store.charters.write(
            topic_id,
            core_questions=core_questions,
            in_scope=in_scope,
            parked=parked,
            done_when=done_when,
            search_terms=search_terms or [],
            driver=driver,
            decision_choice=decision_choice,
            decision_reasons=decision_reasons,
            session_id=session_id,
        ).model_dump(mode="json")

    async def charter_get(self, topic_id: Id, version: Version | None = None) -> dict[str, Any]:
        """The topic's latest charter, or the given version."""
        self.ctx.store.topics.require(topic_id)
        found = (
            self.ctx.store.charters.get_latest(topic_id)
            if version is None
            else self.ctx.store.charters.get_version(topic_id, version)
        )
        if found is None:
            which = "has no charter yet" if version is None else f"has no charter version {version}"
            raise CharterNotFoundError(f"topic {topic_id} {which}")
        return found.model_dump(mode="json")
