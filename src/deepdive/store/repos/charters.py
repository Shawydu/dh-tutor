import json
from collections.abc import Sequence
from uuid import UUID

from deepdive.store.enums import TopicStatus
from deepdive.store.models import Charter
from deepdive.store.repos._common import Repo
from deepdive.store.repos.topics import TopicRepo


class CharterRepo(Repo[Charter]):
    table = "charter"
    model = Charter

    def write(
        self,
        topic_id: UUID,
        *,
        core_questions: Sequence[str],
        in_scope: Sequence[str],
        parked: Sequence[str],
        done_when: str,
        session_id: UUID | None = None,
    ) -> Charter:
        """Store a new charter version: 1 for a topic's first, then one more each time."""
        with self.db.transaction():
            TopicRepo(self.db).require(topic_id)
            self._check_session(session_id)
            version = self.conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM charter WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO charter"
                " (topic_id, version, core_questions, in_scope, parked, done_when, session_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    topic_id,
                    version,
                    json.dumps(list(core_questions)),
                    json.dumps(list(in_scope)),
                    json.dumps(list(parked)),
                    done_when,
                    session_id,
                ),
            )
            # the first charter ends scoping
            self.conn.execute(
                "UPDATE topic SET status = ? WHERE id = ? AND status = ?",
                (TopicStatus.ACTIVE, topic_id, TopicStatus.SCOPING),
            )
        charter = self.get_version(topic_id, version)
        assert charter is not None
        return charter

    def get_latest(self, topic_id: UUID) -> Charter | None:
        return self._one("WHERE topic_id = ? ORDER BY version DESC", (topic_id,))

    def get_version(self, topic_id: UUID, version: int) -> Charter | None:
        return self._one("WHERE topic_id = ? AND version = ?", (topic_id, version))

    def list_versions(self, topic_id: UUID) -> list[Charter]:
        return self._many("WHERE topic_id = ? ORDER BY version", (topic_id,))
