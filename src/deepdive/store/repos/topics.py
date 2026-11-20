import sqlite3
from uuid import UUID

from deepdive.store.enums import TopicStatus
from deepdive.store.errors import ChildDepthError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Topic, TopicNode, TopicOverview, TopicStats
from deepdive.store.repos._common import IdRepo


class TopicRepo(IdRepo[Topic]):
    table = "topic"
    model = Topic
    not_found = TopicNotFoundError

    def _check_parent(self, parent_id: UUID) -> None:
        parent = self.get(parent_id)
        if parent is None:
            raise TopicNotFoundError(parent_id)
        if parent.parent_topic_id is not None:
            raise ChildDepthError(
                f"topic {parent_id} is itself a child; child topics are one level deep"
            )

    def create(
        self,
        title: str,
        *,
        parent_topic_id: UUID | None = None,
        status: TopicStatus = TopicStatus.SCOPING,
    ) -> Topic:
        if parent_topic_id is not None:
            self._check_parent(parent_topic_id)
        topic_id = new_id()
        try:
            self.conn.execute(
                "INSERT INTO topic (id, title, parent_topic_id, status) VALUES (?, ?, ?, ?)",
                (topic_id, title, parent_topic_id, status),
            )
        except sqlite3.IntegrityError as err:
            if "one level deep" in str(err):  # the trigger, if a concurrent write beat the check
                raise ChildDepthError(str(err)) from err
            raise
        return self.require(topic_id)

    def list_all(self) -> list[TopicNode]:
        """Top-level topics (pinned first), each with its children."""
        children: dict[UUID, list[Topic]] = {}
        for child in self._many("WHERE parent_topic_id IS NOT NULL ORDER BY id"):
            assert child.parent_topic_id is not None
            children.setdefault(child.parent_topic_id, []).append(child)
        roots = self._many("WHERE parent_topic_id IS NULL ORDER BY pinned DESC, id")
        return [TopicNode(**t.model_dump(), children=children.get(t.id, [])) for t in roots]

    def set_status(self, topic_id: UUID, status: TopicStatus) -> Topic:
        self.require(topic_id)
        self.conn.execute("UPDATE topic SET status = ? WHERE id = ?", (status, topic_id))
        return self.require(topic_id)

    def _set_pinned(self, topic_id: UUID, pinned: bool) -> Topic:
        self.require(topic_id)
        self.conn.execute("UPDATE topic SET pinned = ? WHERE id = ?", (int(pinned), topic_id))
        return self.require(topic_id)

    def pin(self, topic_id: UUID) -> Topic:
        return self._set_pinned(topic_id, True)

    def unpin(self, topic_id: UUID) -> Topic:
        return self._set_pinned(topic_id, False)

    def overview(self) -> list[TopicOverview]:
        """Top-level topics (pinned, then most recently active counting their children's sessions)
        with per-topic counts and their children, in one query."""
        rows = self.conn.execute(
            "SELECT id, title, parent_topic_id, status, pinned,"
            " (SELECT MAX(version) FROM charter WHERE topic_id = t.id),"
            " (SELECT COUNT(*) FROM agenda_item WHERE topic_id = t.id AND status = 'done'),"
            " (SELECT COUNT(*) FROM agenda_item WHERE topic_id = t.id),"
            " (SELECT COUNT(*) FROM question WHERE topic_id = t.id AND status = 'open'),"
            " (SELECT COUNT(*) FROM question WHERE topic_id = t.id AND status = 'parked'),"
            " (SELECT MAX(started_at) FROM session WHERE topic_id = t.id) AS last_session_at"
            " FROM topic t ORDER BY pinned DESC,"
            " (SELECT MAX(s.started_at) FROM session s JOIN topic c ON c.id = s.topic_id"
            "  WHERE c.id = t.id OR c.parent_topic_id = t.id) DESC, id DESC"
        ).fetchall()
        stats = [
            TopicStats.model_validate(dict(zip(TopicStats.model_fields, r, strict=True)))
            for r in rows
        ]
        children: dict[UUID, list[TopicStats]] = {}
        for s in stats:
            if s.parent_topic_id is not None:
                children.setdefault(s.parent_topic_id, []).append(s)
        return [
            TopicOverview(**s.model_dump(), children=children.get(s.id, []))
            for s in stats
            if s.parent_topic_id is None
        ]
