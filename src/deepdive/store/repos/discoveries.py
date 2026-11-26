from datetime import datetime
from uuid import UUID

from deepdive.store.enums import ClaimStatus, DiscoveryEffect, DiscoveryTargetType
from deepdive.store.errors import DuplicateSourceError, InvalidTargetError
from deepdive.store.ids import new_id
from deepdive.store.models import AgendaItem, Claim, Discovery, Finding, Question
from deepdive.store.repos._common import Repo
from deepdive.store.repos.agenda import AgendaRepo
from deepdive.store.repos.claims import ClaimRepo
from deepdive.store.repos.probe_runs import ProbeRunRepo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.sources import SourceRepo
from deepdive.store.repos.topics import TopicRepo


def target_text(target: Question | Claim | AgendaItem) -> str:
    if isinstance(target, Question):
        return target.clean_text
    return target.facet if isinstance(target, AgendaItem) else target.text


class DiscoveryRepo(Repo[Discovery]):
    table = "discovery"
    model = Discovery

    def check(
        self, topic_id: UUID, source_id: UUID, target_type: DiscoveryTargetType, target_id: UUID
    ) -> Question | Claim | AgendaItem:
        """Return the target, or refuse: unknown topic or source, a target that isn't a question,
        claim or agenda item of this topic, or a source the topic already cites."""
        TopicRepo(self.db).require(topic_id)
        SourceRepo(self.db).require(source_id)
        target = self._target_repo(target_type).get(target_id)
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

    def _target_repo(
        self, target_type: DiscoveryTargetType
    ) -> QuestionRepo | ClaimRepo | AgendaRepo:
        if target_type == DiscoveryTargetType.QUESTION:
            return QuestionRepo(self.db)
        if target_type == DiscoveryTargetType.CLAIM:
            return ClaimRepo(self.db)
        return AgendaRepo(self.db)

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
            if effect == DiscoveryEffect.WEAKENS and target_type == DiscoveryTargetType.CLAIM:
                ClaimRepo(self.db).set_status(target_id, ClaimStatus.WEAKENED)
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

    def weakening(self, topic_id: UUID | None = None) -> list[Discovery]:
        """The latest weakens discovery on each weakened claim (of the topic, else of all)."""
        # shortcut: "latest" is UUIDv7 id order (discovery has no created_at), which can tie
        # across processes in one millisecond; add a created_at column if that ever matters
        where = "AND discovery.topic_id = ? " if topic_id else ""
        return self._many(
            "JOIN claim c ON c.id = discovery.target_id WHERE c.status = 'weakened' "
            "AND discovery.target_type = 'claim' AND discovery.effect = 'weakens' "
            f"{where}AND NOT EXISTS (SELECT 1 FROM discovery d2 WHERE d2.target_id = c.id "
            "AND d2.effect = 'weakens' AND d2.id > discovery.id) ORDER BY discovery.id",
            (topic_id,) if topic_id else (),
        )

    def mark_read(self, discovery_id: UUID, at: datetime) -> None:
        self.conn.execute(
            "UPDATE discovery SET read_at = COALESCE(read_at, ?) WHERE id = ?", (at, discovery_id)
        )

    def finding(self, d: Discovery) -> Finding:
        """`d` with its target's text and its source's link."""
        target = self._target_repo(d.target_type).get(d.target_id)
        source = SourceRepo(self.db).require(d.source_id)
        assert target is not None  # DiscoveryRepo.check ran on add
        return Finding(
            **d.model_dump(
                include={"id", "topic_id", "effect", "target_type", "summary", "relevance"}
            ),
            target_text=target_text(target),
            source_url=source.url or f"https://doi.org/{source.doi}",
        )
