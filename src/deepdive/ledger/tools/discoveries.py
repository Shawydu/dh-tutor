from typing import Any

from deepdive.classify import Choice, Classifier, ClassifierUnavailable, YesNo
from deepdive.config import Config
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Finding, Id
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import DiscoveryEffect, DiscoveryTargetType


class DiscoveryTools(Tools):
    """Probe-only: a finding tied to a question or claim, kept when it is relevant enough."""

    def __init__(self, ctx: LedgerContext, config: Config, classifier: Classifier) -> None:
        super().__init__(ctx)
        self.threshold = config.classifier.auto_threshold
        self.classifier = classifier

    async def discovery_add(
        self,
        probe_run_id: Id,
        topic_id: Id,
        source_id: Id,
        target_type: DiscoveryTargetType,
        target_id: Id,
        summary: Finding,
    ) -> dict[str, Any]:
        """Record a finding (two-sentence summary) about a question or claim of this topic.

        The source must be registered (from search or fetch) and not already cited by the topic.
        The engine scores relevance and effect; a finding below the threshold is dropped
        ({"dropped": true}), not stored.
        """
        scope = self.ctx.probe
        if scope is None or (scope.probe_run_id, scope.topic_id) != (probe_run_id, topic_id):
            raise InvalidInputError("probe_run_id and topic_id must be this probe's own")
        store = self.ctx.store
        target = store.discoveries.check(
            topic_id, source_id, target_type, target_id
        )  # pre-classify
        source = store.sources.require(source_id)
        text = target.clean_text if hasattr(target, "clean_text") else target.text
        state = (
            f"Finding ({source.url or source.doi}): {summary}\n{target_type} of the topic: {text}"
        )
        try:
            answers = self.classifier.classify(
                state,
                {
                    "relevant": YesNo(
                        prompt="Is the finding relevant to the topic's open question or claim?"
                    ),
                    "effect": Choice(
                        prompt="What does the finding do to it?",
                        options=[e.value for e in DiscoveryEffect],
                    ),
                },
            ).answers
        except ClassifierUnavailable as err:
            return {"error": "classifier_unavailable", "detail": str(err)}
        relevance = answers["relevant"].probs["yes"]
        if relevance < self.threshold:
            return {"dropped": True, "relevance": relevance, "threshold": self.threshold}
        found = store.discoveries.add(
            probe_run_id, topic_id, source_id, target_type, target_id,
            DiscoveryEffect(answers["effect"].top[0]), relevance, summary,
        )  # fmt: skip
        return found.model_dump(mode="json")
