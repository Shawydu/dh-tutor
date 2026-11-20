from datetime import datetime
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
        repeat: bool = False,
        at: datetime | None = None,
    ) -> QuestionEdge:
        """Record how `from_id` relates to `to_id`; re-classifying the same pair replaces the
        edge: `created_at` restarts when the relation changes, else the first one is kept."""
        questions = QuestionRepo(self.db)
        questions.require(from_id)
        questions.require(to_id)
        self.conn.execute(
            "INSERT INTO question_edge (from_id, to_id, relation, confidence, classifier, repeat,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (from_id, to_id) DO UPDATE SET"
            " relation = excluded.relation, confidence = excluded.confidence,"
            " classifier = excluded.classifier, repeat = repeat OR excluded.repeat,"
            " created_at = CASE WHEN relation != excluded.relation THEN excluded.created_at"
            " ELSE COALESCE(created_at, excluded.created_at) END",
            (from_id, to_id, relation, confidence, classifier, repeat, at),
        )
        edge = self._one("WHERE from_id = ? AND to_id = ?", (from_id, to_id))
        assert edge is not None
        return edge

    def list_for_question(self, question_id: UUID) -> list[QuestionEdge]:
        """Every edge the question is on either end of."""
        return self._many(
            "WHERE from_id = ? OR to_id = ? ORDER BY from_id, to_id", (question_id, question_id)
        )

    def list_cross_topic(self, since: datetime | None = None) -> list[QuestionEdge]:
        """Related questions (not `unrelated`) in different topics, created at or after `since`
        (every edge when None; edges with no time never count as new)."""
        since_sql = "" if since is None else "AND question_edge.created_at >= ? "
        return self._many(
            "JOIN question a ON a.id = from_id JOIN question b ON b.id = to_id"
            " WHERE a.topic_id != b.topic_id AND relation != 'unrelated' "
            + since_sql
            + "ORDER BY from_id, to_id",
            () if since is None else (since,),
        )
