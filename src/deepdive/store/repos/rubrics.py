import json
from collections.abc import Sequence
from uuid import UUID

from deepdive.store.models import Rubric
from deepdive.store.repos._common import Repo
from deepdive.store.repos.questions import QuestionRepo


class RubricRepo(Repo[Rubric]):
    table = "rubric"
    model = Rubric

    def write(
        self, question_id: UUID, key_points: Sequence[str], misconceptions: Sequence[str]
    ) -> Rubric:
        """Store the question's rubric, replacing an earlier one."""
        QuestionRepo(self.db).require(question_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO rubric (question_id, key_points, misconceptions)"
            " VALUES (?, ?, ?)",
            (question_id, json.dumps(list(key_points)), json.dumps(list(misconceptions))),
        )
        rubric = self.get(question_id)
        assert rubric is not None
        return rubric

    def get(self, question_id: UUID) -> Rubric | None:
        return self._one("WHERE question_id = ?", (question_id,))
