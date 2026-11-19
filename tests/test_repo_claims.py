from collections.abc import Callable
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
from deepdive.store.repos import Store

SEEN = datetime(2026, 1, 1, tzinfo=UTC)


def _setup(store: Store) -> tuple[UUID, UUID, UUID]:
    topic = store.topics.create("T")
    a = store.sources.register(url="https://e.com/a", kind="docs", tier=1, seen_at=SEEN)
    b = store.sources.register(url="https://e.com/b", kind="docs", tier=2, seen_at=SEEN)
    return topic.id, a.id, b.id


def test_add_claim_creates_evidence_per_source(store: Store) -> None:
    """Adding a claim creates one supporting evidence row per distinct source."""
    topic_id, a, b = _setup(store)
    claim = store.claims.add(topic_id, "GIL serialises bytecode", [a, b, a], excerpt_summary="x")
    assert (claim.topic_id, claim.status) == (topic_id, ClaimStatus.ESTABLISHED)
    assert store.claims.get(claim.id) == claim
    rows = store.evidence.list_for_claim(claim.id)
    assert [(e.source_id, e.stance, e.excerpt_summary) for e in rows] == [
        (a, EvidenceStance.SUPPORTS, "x"),
        (b, EvidenceStance.SUPPORTS, "x"),
    ]


def test_claim_with_a_missing_source_writes_nothing(store: Store) -> None:
    """A claim citing a missing source is refused and writes no claim or evidence."""
    topic_id, a, _ = _setup(store)
    with pytest.raises(SourceNotFoundError):
        store.claims.add(topic_id, "bad", [a, new_id()])
    assert store.claims.list_for_topic(topic_id) == []
    assert store.evidence.list_for_topic(topic_id) == []


type Call = Callable[[Store, UUID, UUID], object]

CASES: list[tuple[type[Exception], Call]] = [
    (SourceRequiredError, lambda s, t, a: s.claims.add(t, "uncited", [])),
    (TopicNotFoundError, lambda s, t, a: s.claims.add(new_id(), "x", [a])),
]


@pytest.mark.parametrize(
    ("error", "call"),
    CASES,
    ids=["no-sources", "unknown-topic"],
)
def test_claim_without_sources_or_with_unknown_topic_fails(
    store: Store, error: type[Exception], call: Call
) -> None:
    """A claim needs a cited source and an existing topic, and a refusal writes nothing."""
    topic_id, a, _ = _setup(store)
    with pytest.raises(error):
        call(store, topic_id, a)
    assert store.claims.list_for_topic(topic_id) == []


def test_add_evidence_to_an_existing_claim(store: Store) -> None:
    """Evidence can be added to an existing claim and is listed for its topic."""
    topic_id, a, b = _setup(store)
    claim = store.claims.add(topic_id, "c", [a])
    added = store.evidence.add(claim.id, b, EvidenceStance.WEAKENS, "counter-example")
    assert store.evidence.get(added.id) == added
    assert (added.claim_id, added.source_id, added.stance) == (claim.id, b, EvidenceStance.WEAKENS)
    assert [e.id for e in store.evidence.list_for_topic(topic_id)][-1] == added.id
    assert store.evidence.get(new_id()) is None


@pytest.mark.parametrize(
    ("error", "call"),
    [
        (ClaimNotFoundError, lambda s, c, a: s.evidence.add(new_id(), a, EvidenceStance.SUPPORTS)),
        (SourceNotFoundError, lambda s, c, a: s.evidence.add(c, new_id(), EvidenceStance.SUPPORTS)),
    ],
    ids=["unknown-claim", "unknown-source"],
)
def test_evidence_needs_an_existing_claim_and_source(
    store: Store, error: type[Exception], call: Call
) -> None:
    """Evidence cannot cite a missing claim or source, and a refusal adds no row."""
    topic_id, a, _ = _setup(store)
    claim = store.claims.add(topic_id, "c", [a])
    with pytest.raises(error):
        call(store, claim.id, a)
    assert len(store.evidence.list_for_claim(claim.id)) == 1
    assert store.evidence.get(new_id()) is None


def test_seeded_claims_per_topic(store: Store, seed_topics: Seed) -> None:
    """Seeded claims and their evidence are listed per topic with the right statuses."""
    python = store.claims.list_for_topic(seed_topics.topics["python-concurrency"])
    iceberg = store.claims.list_for_topic(seed_topics.topics["iceberg"])
    assert (len(python), len(iceberg)) == (3, 2)
    assert [c.status for c in python] == ["established", "established", "weakened"]
    weakening = store.evidence.list_for_claim(python[2].id)
    assert [e.stance for e in weakening] == ["weakens"]
    assert len(store.evidence.list_for_topic(seed_topics.topics["iceberg"])) == 3
