import sqlite3
from uuid import UUID

from deepdive.store.errors import QuestionNotFoundError, TopicNotFoundError
from deepdive.store.models import Question
from deepdive.store.repos._common import many, require


def add(conn: sqlite3.Connection, topic_id: UUID, question_id: UUID) -> None:
    """Put the question on the topic's frontier; adding it twice is a no-op."""
    require(conn, "topic", topic_id, TopicNotFoundError)
    require(conn, "question", question_id, QuestionNotFoundError)
    conn.execute(
        "INSERT OR IGNORE INTO frontier (topic_id, question_id) VALUES (?, ?)",
        (topic_id, question_id),
    )


def list_for_topic(conn: sqlite3.Connection, topic_id: UUID) -> list[Question]:
    return many(
        conn,
        Question,
        "question",
        "JOIN frontier ON frontier.question_id = question.id"
        " WHERE frontier.topic_id = ? ORDER BY question.id",
        (topic_id,),
    )
