from typing import Any

from deepdive.ledger.limits import Id, Note, Summary
from deepdive.ledger.tools._common import Tools


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

    async def session_end(self, session_id: Id, summary: Summary) -> dict[str, Any]:
        """Close the session with a short summary of what happened."""
        return self.ctx.store.sessions.end(session_id, summary, at=self.ctx.now()).model_dump(
            mode="json"
        )
