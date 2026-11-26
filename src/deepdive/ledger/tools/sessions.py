from typing import Any

from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Note, Summary
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import SessionStudentMode


class SessionTools(Tools):
    async def session_start(self, topic_id: Id) -> dict[str, Any]:
        """Open a session on a topic. Pass the returned id as session_id to the write tools."""
        return self.ctx.store.sessions.start(topic_id, at=self.ctx.now()).model_dump(mode="json")

    async def session_bookmark(
        self,
        session_id: Id,
        agenda_item_id: Id | None = None,
        question_id: Id | None = None,
        note: Note | None = None,
    ) -> dict[str, Any]:
        """Record where the session left off. Replaces the previous bookmark."""
        return self.ctx.store.sessions.bookmark(
            session_id,
            agenda_item_id=agenda_item_id,
            question_id=question_id,
            note=note,
        ).model_dump(mode="json")

    async def session_student_mode_set(
        self, session_id: Id, mode: SessionStudentMode
    ) -> dict[str, Any]:
        """Choose which student personas the guide calls at checkpoints: off, curious, skeptic or
        both (the default)."""
        return self.ctx.store.sessions.set_student_mode(session_id, mode).model_dump(mode="json")

    async def session_grading_set(self, session_id: Id, on: bool) -> dict[str, Any]:
        """Switch grading on or off for the session (on by default). While off, answer_grade and
        answer_grade_set refuse and recap checks are skipped; self_rate still works."""
        return self.ctx.store.sessions.set_grading(session_id, on).model_dump(mode="json")

    async def session_end(self, session_id: Id, summary: Summary) -> dict[str, Any]:
        """Close the session with a short summary of what happened."""
        return self.ctx.store.sessions.end(session_id, summary, at=self.ctx.now()).model_dump(
            mode="json"
        )

    async def session_attach(self, session_id: Id, agent_session_id: Id) -> dict[str, Any]:
        """Link your agent session id (from the session-start brief) to this open session, so
        the question hook finds the topic. Call right after session_start, and again after
        /resume or /clear."""
        if self.ctx.store.sessions.require(session_id).ended_at is not None:
            raise InvalidInputError("the session has ended")
        return self.ctx.store.agent_sessions.attach(
            agent_session_id, session_id, at=self.ctx.now()
        ).model_dump(mode="json")
