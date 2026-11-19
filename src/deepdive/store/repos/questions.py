import re
from uuid import UUID

from deepdive.store.enums import QuestionAsker, QuestionStatus
from deepdive.store.errors import QuestionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Question
from deepdive.store.repos._common import IdRepo
from deepdive.store.repos.topics import TopicRepo

# Words that match half the registry and tell the ranker nothing. Single letters (such as the "t"
# of "can't") are dropped separately.
_STOP_WORDS = frozenset(
    "a about all also am an and any are as at be been being but by can could did do does doing "
    "for from get got had has have how i if in into is it its just me my no not of on or our "
    "should so than that the their them then there these they this to too up us use was we were "
    "what when where which who why will with would you your".split()
)


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 query: quoted word tokens joined with OR; '' if none."""
    tokens = re.findall(r"[^\W_]+", text.casefold())
    keep = dict.fromkeys(t for t in tokens if len(t) > 1 and t not in _STOP_WORDS)
    return " OR ".join(f'"{t}"' for t in keep)


class QuestionRepo(IdRepo[Question]):
    table = "question"
    model = Question
    not_found = QuestionNotFoundError

    def add(
        self,
        topic_id: UUID,
        asker: QuestionAsker,
        raw_text: str,
        clean_text: str,
        *,
        session_id: UUID | None = None,
        status: QuestionStatus = QuestionStatus.OPEN,
    ) -> Question:
        TopicRepo(self.conn).require(topic_id)
        self._check_session(session_id)
        question_id = new_id()
        self.conn.execute(
            "INSERT INTO question (id, topic_id, session_id, asker, raw_text, clean_text, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (question_id, topic_id, session_id, asker, raw_text, clean_text, status),
        )
        return self._must_get(question_id)

    def set_status(self, question_id: UUID, status: QuestionStatus) -> Question:
        self.require(question_id)
        self.conn.execute("UPDATE question SET status = ? WHERE id = ?", (status, question_id))
        return self._must_get(question_id)

    def set_answer_summary(
        self, question_id: UUID, summary: str, *, status: QuestionStatus | None = None
    ) -> Question:
        """Store the answer summary; with `status`, set that in the same statement."""
        self.require(question_id)
        self.conn.execute(
            "UPDATE question SET answer_summary = ?, status = COALESCE(?, status) WHERE id = ?",
            (summary, status, question_id),
        )
        return self._must_get(question_id)

    def park(self, question_id: UUID) -> Question:
        return self.set_status(question_id, QuestionStatus.PARKED)

    def list_parked(self, topic_id: UUID | None = None) -> list[Question]:
        """Parked questions of one topic, or of every topic when `topic_id` is None."""
        if topic_id is None:
            return self._many("WHERE status = ? ORDER BY id", (QuestionStatus.PARKED,))
        return self._many(
            "WHERE status = ? AND topic_id = ? ORDER BY id", (QuestionStatus.PARKED, topic_id)
        )

    def list_by_status(self, topic_id: UUID, status: QuestionStatus) -> list[Question]:
        return self._many("WHERE topic_id = ? AND status = ? ORDER BY id", (topic_id, status))

    def fts_candidates(
        self, text: str, limit: int = 10, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        """The questions, from all topics, that share the most (rarest) words with `text`, best
        first.

        With `status`, only questions in that status.

        Free text is reduced to word tokens, so punctuation and FTS operators in it cannot break
        the MATCH; text with no usable word returns []. Ranking is bm25 over the porter-stemmed
        index.
        """
        query = _fts_query(text)
        if not query or limit < 1:
            return []
        return self._many(
            "JOIN question_fts ON question_fts.question_id = question.id"
            " WHERE question_fts MATCH ? AND (? IS NULL OR question.status = ?)"
            " ORDER BY bm25(question_fts), question.id LIMIT ?",
            (query, status, status, limit),
        )
