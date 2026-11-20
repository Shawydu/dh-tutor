from datetime import datetime
from uuid import UUID

from deepdive.store.models import AgentSession
from deepdive.store.repos._common import Repo


class AgentSessionRepo(Repo[AgentSession]):
    table = "agent_session"
    model = AgentSession

    def attach(self, agent_session_id: UUID, session_id: UUID, *, at: datetime) -> AgentSession:
        """Point the agent session at an engine session; attaching again replaces the old link."""
        self._check_session(session_id)
        self.conn.execute(
            "INSERT INTO agent_session (agent_session_id, session_id, attached_at)"
            " VALUES (?, ?, ?) ON CONFLICT (agent_session_id)"
            " DO UPDATE SET session_id = excluded.session_id, attached_at = excluded.attached_at",
            (agent_session_id, session_id, at),
        )
        found = self.get(agent_session_id)
        assert found is not None
        return found

    def get(self, agent_session_id: UUID) -> AgentSession | None:
        return self._one("WHERE agent_session_id = ?", (agent_session_id,))
