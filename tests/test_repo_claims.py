import sqlite3
from datetime import UTC, datetime
from uuid import UUID

import pytest
from conftest import Seed

from deepdive.store.enums import ClaimStatus, EvidenceStance
from deepdive.store.errors import (
    ClaimNotFoundError,
    SourceNotFoundError,
    SourceRequiredError,
    TopicNotFoundError,
)
from deepdive.store.ids import new_id
from deepdive.store.repos import claims, evidence, sources, topics

SEEN = datetime(2026, 1, 1, tzinfo=UTC)


def _setup(db: sqlite3.Connection) -> tuple[UUID, UUID, UUID]:
    topic = topics.create(db, "T")
    a = sources.register(db, url="https://e.com/a", kind="docs", tier=1, seen_at=SEEN)
    b = sources.register(db, url="https://e.com/b", kind="docs", tier=2, seen_at=SEEN)
    return topic.id, a.id, b.id


def test_add_claim_creates_evidence_per_source(db: sqlite3.Connection) -> None:
    topic_id, a, b = _setup(db)
    claim = claims.add(db, topic_id, "GIL serialises bytecode", [a, b, a], excerpt_summary="x")
    assert (claim.topic_id, claim.status) == (topic_id, ClaimStatus.ESTABLISHED)
    assert claims.get(db, claim.id) == claim
    rows = evidence.list_for_claim(db, claim.id)
    assert [(e.source_id, e.stance, e.excerpt_summary) for e in rows] == [
        (a, EvidenceStance.SUPPORTS, "x"),
        (b, EvidenceStance.SUPPORTS, "x"),
    ]


def test_claim_with_a_missing_source_writes_nothing(db: sqlite3.Connection) -> None:
    topic_id, a, _ = _setup(db)
    with pytest.raises(SourceNotFoundError):
        claims.add(db, topic_id, "bad", [a, new_id()])
    assert claims.list_for_topic(db, topic_id) == []
    assert evidence.list_for_topic(db, topic_id) == []


def test_claim_without_sources_or_with_unknown_topic_fails(db: sqlite3.Connection) -> None:
    topic_id, a, _ = _setup(db)
    with pytest.raises(SourceRequiredError):
        claims.add(db, topic_id, "uncited", [])
    with pytest.raises(TopicNotFoundError):
        claims.add(db, new_id(), "x", [a])
    assert claims.list_for_topic(db, topic_id) == []


def test_add_evidence_to_an_existing_claim(db: sqlite3.Connection) -> None:
    topic_id, a, b = _setup(db)
    claim = claims.add(db, topic_id, "c", [a])
    added = evidence.add(db, claim.id, b, EvidenceStance.WEAKENS, "counter-example")
    assert evidence.get(db, added.id) == added
    assert (added.claim_id, added.source_id, added.stance) == (claim.id, b, EvidenceStance.WEAKENS)
    assert [e.id for e in evidence.list_for_topic(db, topic_id)][-1] == added.id


def test_evidence_needs_an_existing_claim_and_source(db: sqlite3.Connection) -> None:
    topic_id, a, _ = _setup(db)
    claim = claims.add(db, topic_id, "c", [a])
    with pytest.raises(ClaimNotFoundError):
        evidence.add(db, new_id(), a, EvidenceStance.SUPPORTS)
    with pytest.raises(SourceNotFoundError):
        evidence.add(db, claim.id, new_id(), EvidenceStance.SUPPORTS)
    assert len(evidence.list_for_claim(db, claim.id)) == 1
    assert evidence.get(db, new_id()) is None


def test_seeded_claims_per_topic(db: sqlite3.Connection, seed_topics: Seed) -> None:
    python = claims.list_for_topic(db, seed_topics.topics["python-concurrency"])
    iceberg = claims.list_for_topic(db, seed_topics.topics["iceberg"])
    assert (len(python), len(iceberg)) == (3, 2)
    assert [c.status for c in python] == ["established", "established", "weakened"]
    weakening = evidence.list_for_claim(db, python[2].id)
    assert [e.stance for e in weakening] == ["weakens"]
    assert len(evidence.list_for_topic(db, seed_topics.topics["iceberg"])) == 3
