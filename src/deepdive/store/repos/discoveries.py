from datetime import datetime
from uuid import UUID

from deepdive.store.enums import DiscoveryEffect, DiscoveryTargetType
from deepdive.store.errors import DuplicateSourceError, InvalidTargetError
from deepdive.store.ids import new_id
from deepdive.store.models import Claim, Discovery, Finding, Question
from deepdive.store.repos._common import Repo
from deepdive.store.repos.claims import ClaimRepo
from deepdive.store.repos.probe_runs import ProbeRunRepo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.sources import SourceRepo
from deepdive.store.repos.topics import TopicRepo


class DiscoveryRepo(Repo[Discovery]):
    table = "discovery"
    model = Discovery

    def check(
        self, topic_id: UUID, source_id: UUID, target_type: DiscoveryTargetType, target_id: UUID
    ) -> Question | Claim:
        """Return the target, or refuse: unknown topic or source, a target that isn't a question
        or claim of this topic, or a source the topic already cites."""
        TopicRepo(self.db).require(topic_id)
        SourceRepo(self.db).require(source_id)
        target = (
            QuestionRepo(self.db)
            if target_type == DiscoveryTargetType.QUESTION
            else ClaimRepo(self.db)
        ).get(target_id)
        if target is None or target.topic_id != topic_id:
            raise InvalidTargetError(f"{target_type} {target_id} is not in topic {topic_id}")
        # url and doi are UNIQUE on source, so one source row is one url/doi
        if self.conn.execute(
            "SELECT 1 FROM discovery WHERE topic_id = ? AND source_id = ? UNION ALL"
            " SELECT 1 FROM evidence e JOIN claim c ON c.id = e.claim_id"
            " WHERE c.topic_id = ? AND e.source_id = ?",
            (topic_id, source_id, topic_id, source_id),
        ).fetchone():
            raise DuplicateSourceError(f"topic {topic_id} already cites source {source_id}")
        return target

    def add(
        self,
        probe_run_id: UUID,
        topic_id: UUID,
        source_id: UUID,
        target_type: DiscoveryTargetType,
        target_id: UUID,
        effect: DiscoveryEffect,
        relevance: float,
        summary: str,
    ) -> Discovery:
        """Record a finding, after `check`."""
        with self.db.transaction():
            ProbeRunRepo(self.db).require(probe_run_id)
            self.check(topic_id, source_id, target_type, target_id)
            found_id = new_id()
            self.conn.execute(
                "INSERT INTO discovery (id, topic_id, probe_run_id, source_id, target_type,"
                " target_id, effect, relevance, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (found_id, topic_id, probe_run_id, source_id, target_type, target_id, effect,
                 relevance, summary),
            )  # fmt: skip
        found = self._one("WHERE id = ?", (found_id,))
        assert found is not None
        return found

    def list_for_topic(self, topic_id: UUID) -> list[Discovery]:
        return self._many("WHERE topic_id = ? ORDER BY id", (topic_id,))

    def get(self, discovery_id: UUID) -> Discovery | None:
        return self._one("WHERE id = ?", (discovery_id,))

    def list_unread(
        self, topic_id: UUID | None = None, since: datetime | None = None
    ) -> list[Discovery]:
        """Discoveries never opened, best first; with `since`, only those whose probe run started
        at or after it (a discovery has no time of its own)."""
        where = ""
        params: list[object] = []
        if topic_id:
            where, params = where + "AND topic_id = ? ", [*params, topic_id]
        if since:
            where, params = where + "AND r.started_at >= ? ", [*params, since]
        return self._many(
            "JOIN probe_run r ON r.id = discovery.probe_run_id WHERE read_at IS NULL "
            f"{where}ORDER BY relevance DESC, discovery.id",
            tuple(params),
        )

    def mark_read(self, discovery_id: UUID, at: datetime) -> None:
        self.conn.execute(
            "UPDATE discovery SET read_at = COALESCE(read_at, ?) WHERE id = ?", (at, discovery_id)
        )

    def finding(self, d: Discovery) -> Finding:
        """`d` with its target's text and its source's link."""
        target = (
            QuestionRepo(self.db).get(d.target_id)
            if d.target_type == DiscoveryTargetType.QUESTION
            else ClaimRepo(self.db).get(d.target_id)
        )
        source = SourceRepo(self.db).require(d.source_id)
        assert target is not None  # DiscoveryRepo.check ran on add
        return Finding(
            **d.model_dump(
                include={"id", "topic_id", "effect", "target_type", "summary", "relevance"}
            ),
            target_text=target.clean_text if isinstance(target, Question) else target.text,
            source_url=source.url or f"https://doi.org/{source.doi}",
        )
