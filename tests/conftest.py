import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from deepdive import clock
from deepdive.store.db import connect, migrate
from deepdive.store.enums import (
    ClaimStatus,
    EvidenceStance,
    QuestionAsker,
    QuestionEdgeRelation,
    QuestionStatus,
    TopicStatus,
)
from deepdive.store.repos import agenda, charters, claims, edges, questions, sources, topics

TOPIC_FIXTURES = Path(__file__).parent / "fixtures" / "topics"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A fresh, migrated database file; the real schema, no mocks."""
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def frozen_clock() -> Iterator[datetime]:
    """Pin deepdive.clock to a fixed instant for the test, then release it."""
    pinned = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    clock.set_now(pinned)
    yield pinned
    clock.set_now(None)


@dataclass
class Seed:
    """Ids of the seeded rows, by the keys used in tests/fixtures/topics/*.json."""

    topics: dict[str, UUID]
    questions: dict[str, UUID]
    sources: dict[str, UUID]
    claims: list[UUID]


def _load(conn: sqlite3.Connection, path: Path, seed: Seed) -> None:
    data: dict[str, Any] = json.loads(path.read_text())
    topic = topics.create(conn, data["title"], status=TopicStatus(data["status"]))
    seed.topics[path.stem] = topic.id
    charters.write(conn, topic.id, **data["charter"])
    agenda.replace_items(conn, topic.id, data["agenda"])
    local_sources: dict[str, UUID] = {}
    for key, src in data["sources"].items():
        source = sources.register(conn, **src, seen_at=datetime(2026, 1, 1, tzinfo=UTC))
        local_sources[key] = seed.sources[key] = source.id
    for claim in data["claims"]:
        added = claims.add(
            conn,
            topic.id,
            claim["text"],
            [local_sources[s] for s in claim["sources"]],
            status=ClaimStatus(claim["status"]),
            stance=EvidenceStance(claim.get("stance", "supports")),
        )
        seed.claims.append(added.id)
    local_questions: dict[str, UUID] = {}
    for key, q in data["questions"].items():
        added_q = questions.add(
            conn,
            topic.id,
            QuestionAsker(q["asker"]),
            q["raw"],
            q["clean"],
            status=QuestionStatus(q["status"]),
        )
        local_questions[key] = seed.questions[key] = added_q.id
    for edge in data["edges"]:
        edges.add(
            conn,
            local_questions[edge["from"]],
            local_questions[edge["to"]],
            QuestionEdgeRelation(edge["relation"]),
            confidence=edge.get("confidence"),
            classifier=edge.get("classifier"),
        )


@pytest.fixture
def seed_topics(db: sqlite3.Connection) -> Seed:
    """The two design example topics (15 questions in all) loaded through the repos.

    Plus one cross-topic edge: the Iceberg commit question is an aspect of the Python locks one.
    """
    seed = Seed(topics={}, questions={}, sources={}, claims=[])
    for path in sorted(TOPIC_FIXTURES.glob("*.json")):
        _load(db, path, seed)
    edges.add(
        db,
        seed.questions["commit_concurrent"],
        seed.questions["locks_needed"],
        QuestionEdgeRelation.ASPECT,
    )
    return seed
