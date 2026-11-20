import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from deepdive.store.enums import ProbeRunStatus
from deepdive.store.errors import ProbeRunNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import ProbeRun, ProbeTopic, TopicOutcome
from deepdive.store.repos._common import IdRepo


class ProbeRunRepo(IdRepo[ProbeRun]):
    table = "probe_run"
    model = ProbeRun
    not_found = ProbeRunNotFoundError

    def create(self, topic_ids: list[UUID], *, at: datetime) -> ProbeRun:
        """A running probe run holding the planned topics."""
        run_id = new_id()
        planned = [ProbeTopic(topic_id=t).model_dump(mode="json") for t in topic_ids]
        self.conn.execute(
            "INSERT INTO probe_run (id, started_at, topics, status) VALUES (?, ?, ?, ?)",
            (run_id, at, json.dumps(planned), ProbeRunStatus.RUNNING),
        )
        self.conn.executemany(
            "INSERT INTO probe_topic (probe_run_id, topic_id) VALUES (?, ?)",
            [(run_id, t) for t in topic_ids],
        )
        return self.require(run_id)

    def spend(
        self, run_id: UUID, topic_id: UUID, kind: Literal["search", "fetch"], limit: int
    ) -> bool:
        """Count one search or fetch against the topic; False, counting nothing, at the limit."""
        column = "searches_used" if kind == "search" else "fetches_used"
        with self.db.transaction():
            done = self.conn.execute(
                f"UPDATE probe_topic SET {column} = {column} + 1"
                f" WHERE probe_run_id = ? AND topic_id = ? AND {column} < ?",
                (run_id, topic_id, limit),
            ).rowcount
            if done and kind == "search":
                self.conn.execute(
                    "UPDATE probe_run SET searches_used = searches_used + 1 WHERE id = ?", (run_id,)
                )
        return done == 1

    def searches_used(self, run_id: UUID, topic_id: UUID) -> int:
        row = self.conn.execute(
            "SELECT searches_used FROM probe_topic WHERE probe_run_id = ? AND topic_id = ?",
            (run_id, topic_id),
        ).fetchone()
        return int(row[0])

    def record(self, run_id: UUID, topic_id: UUID, outcome: TopicOutcome) -> None:
        """Set one topic's outcome inside the run's topic list."""
        with self.db.transaction():
            topics = self.require(run_id).topics
            for t in topics:
                if t.topic_id == topic_id:
                    t.outcome = outcome
            self.conn.execute(
                "UPDATE probe_run SET topics = ? WHERE id = ?",
                (json.dumps([t.model_dump(mode="json") for t in topics]), run_id),
            )

    def finish(self, run_id: UUID, status: ProbeRunStatus) -> ProbeRun:
        self.require(run_id)
        self.conn.execute("UPDATE probe_run SET status = ? WHERE id = ?", (status, run_id))
        return self.require(run_id)
