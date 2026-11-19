from uuid import UUID

from deepdive.store.enums import QuestionEdgeRelation
from deepdive.store.models import QuestionEdge
from deepdive.store.repos._common import Repo
from deepdive.store.repos.questions import QuestionRepo


class EdgeRepo(Repo[QuestionEdge]):
    table = "question_edge"
    model = QuestionEdge

    def add(
        self,
        from_id: UUID,
        to_id: UUID,
        relation: QuestionEdgeRelation,
        *,
        confidence: float | None = None,
        classifier: str | None = None,
    ) -> QuestionEdge:
        """Record how `from_id` relates to `to_id`; re-classifying the same pair replaces the
        edge."""
        questions = QuestionRepo(self.conn)
        questions.require(from_id)
        questions.require(to_id)
        self.conn.execute(
            "INSERT INTO question_edge (from_id, to_id, relation, confidence, classifier)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT (from_id, to_id) DO UPDATE SET"
            " relation = excluded.relation, confidence = excluded.confidence,"
            " classifier = excluded.classifier",
            (from_id, to_id, relation, confidence, classifier),
        )
        edge = self._one("WHERE from_id = ? AND to_id = ?", (from_id, to_id))
        assert edge is not None
        return edge

    def list_for_question(self, question_id: UUID) -> list[QuestionEdge]:
        """Every edge the question is on either end of."""
        return self._many(
            "WHERE from_id = ? OR to_id = ? ORDER BY from_id, to_id", (question_id, question_id)
        )
