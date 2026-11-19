from uuid import UUID

from deepdive.store.models import Question
from deepdive.store.repos._common import Repo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.topics import TopicRepo


class FrontierRepo(Repo[Question]):
    """Reads `question` rows through the `frontier` join table, so `model` is Question."""

    table = "question"
    model = Question

    def add(self, topic_id: UUID, question_id: UUID) -> None:
        """Put the question on the topic's frontier; adding it twice is a no-op."""
        TopicRepo(self.conn).require(topic_id)
        QuestionRepo(self.conn).require(question_id)
        self.conn.execute(
            "INSERT OR IGNORE INTO frontier (topic_id, question_id) VALUES (?, ?)",
            (topic_id, question_id),
        )

    def list_for_topic(self, topic_id: UUID) -> list[Question]:
        return self._many(
            "JOIN frontier ON frontier.question_id = question.id"
            " WHERE frontier.topic_id = ? ORDER BY question.id",
            (topic_id,),
        )
