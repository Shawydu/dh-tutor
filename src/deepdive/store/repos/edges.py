import sqlite3
from uuid import UUID

from deepdive.store.enums import QuestionEdgeRelation
from deepdive.store.errors import QuestionNotFoundError
from deepdive.store.models import QuestionEdge
from deepdive.store.repos._common import many, one, require


def add(
    conn: sqlite3.Connection,
    from_id: UUID,
    to_id: UUID,
    relation: QuestionEdgeRelation,
    *,
    confidence: float | None = None,
    classifier: str | None = None,
) -> QuestionEdge:
    """Record how `from_id` relates to `to_id`; re-classifying the same pair replaces the edge."""
    require(conn, "question", from_id, QuestionNotFoundError)
    require(conn, "question", to_id, QuestionNotFoundError)
    conn.execute(
        "INSERT INTO question_edge (from_id, to_id, relation, confidence, classifier)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (from_id, to_id) DO UPDATE SET"
        " relation = excluded.relation, confidence = excluded.confidence,"
        " classifier = excluded.classifier",
        (from_id, to_id, relation, confidence, classifier),
    )
    edge = one(
        conn, QuestionEdge, "question_edge", "WHERE from_id = ? AND to_id = ?", (from_id, to_id)
    )
    assert edge is not None
    return edge


def list_for_question(conn: sqlite3.Connection, question_id: UUID) -> list[QuestionEdge]:
    """Every edge the question is on either end of."""
    return many(
        conn,
        QuestionEdge,
        "question_edge",
        "WHERE from_id = ? OR to_id = ? ORDER BY from_id, to_id",
        (question_id, question_id),
    )
