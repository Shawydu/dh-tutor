from datetime import datetime
from uuid import UUID

from deepdive.store.enums import SessionStudentMode
from deepdive.store.errors import SessionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Bookmark, Session
from deepdive.store.repos._common import IdRepo
from deepdive.store.repos.agenda import AgendaRepo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.topics import TopicRepo


class SessionRepo(IdRepo[Session]):
    table = "session"
    model = Session
    not_found = SessionNotFoundError

    def start(self, topic_id: UUID, *, at: datetime) -> Session:
        """Open a session for the topic; `at` is an aware datetime (the store never reads the
        clock)."""
        TopicRepo(self.db).require(topic_id)
        session_id = new_id()
        self.conn.execute(
            "INSERT INTO session (id, topic_id, started_at) VALUES (?, ?, ?)",
            (session_id, topic_id, at),
        )
        return self.require(session_id)

    def bookmark(
        self,
        session_id: UUID,
        *,
        agenda_item_id: UUID | None = None,
        question_id: UUID | None = None,
        note: str | None = None,
    ) -> Session:
        """Replace the session's bookmark with exactly these fields."""
        self.require(session_id)
        if agenda_item_id is not None:
            AgendaRepo(self.db).require(agenda_item_id)
        if question_id is not None:
            QuestionRepo(self.db).require(question_id)
        mark = Bookmark(agenda_item_id=agenda_item_id, question_id=question_id, note=note)
        self.conn.execute(
            "UPDATE session SET bookmark = ? WHERE id = ?", (mark.model_dump_json(), session_id)
        )
        return self.require(session_id)

    def set_student_mode(self, session_id: UUID, mode: SessionStudentMode) -> Session:
        self.require(session_id)
        self.conn.execute("UPDATE session SET student_mode = ? WHERE id = ?", (mode, session_id))
        return self.require(session_id)

    def set_grading(self, session_id: UUID, on: bool) -> Session:
        self.require(session_id)
        self.conn.execute("UPDATE session SET grading = ? WHERE id = ?", (on, session_id))
        return self.require(session_id)

    def end(self, session_id: UUID, summary: str, *, at: datetime) -> Session:
        self.require(session_id)
        self.conn.execute(
            "UPDATE session SET ended_at = ?, summary = ? WHERE id = ?", (at, summary, session_id)
        )
        return self.require(session_id)

    def latest(self, topic_id: UUID, *, recorded: bool = False) -> Session | None:
        """The newest session; with `recorded`, the newest that has a summary or a bookmark."""
        where = "AND (summary IS NOT NULL OR bookmark IS NOT NULL) " if recorded else ""
        return self._one(
            f"WHERE topic_id = ? {where}ORDER BY started_at DESC, id DESC", (topic_id,)
        )

    def list_for_topic(self, topic_id: UUID) -> list[Session]:
        """Every session of the topic, oldest first."""
        return self._many("WHERE topic_id = ? ORDER BY started_at, id", (topic_id,))
