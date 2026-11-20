"""Shortlist the past questions the classifier will compare a new question with."""

from deepdive.matcher.embed import Embedder
from deepdive.store.models import Question
from deepdive.store.repos import Store


class CandidateFinder:
    def __init__(self, store: Store, embedder: Embedder, limit: int) -> None:
        self.store = store
        self.embedder = embedder
        self.limit = limit

    def find(self, text: str) -> list[Question]:
        """Keyword hits first, then meaning hits, deduped and capped, across all topics."""
        found = {q.id: q for q in self.store.questions.fts_candidates(text, self.limit)}
        for question_id in self.embedder.nearest(text, self.limit):
            if question_id not in found:
                found[question_id] = self.store.questions.require(question_id)
        return list(found.values())[: self.limit]
