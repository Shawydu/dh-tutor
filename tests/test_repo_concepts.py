from datetime import UTC, datetime

import pytest
from conftest import Seed

from deepdive.store.repos import Store
from deepdive.store.repos.concepts import concept_name

AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("  Data   Structures ", "data structure"),
        ("Dependencies", "dependency"),
        ("locks", "lock"),
        ("class", "class"),
        ("status", "status"),
        ("analysis", "analysis"),
        ("GIL", "gil"),
        ("   ", ""),
    ],
    ids=["spaces-plural", "ies", "s", "ss", "us", "is", "lowercase", "blank"],
)
def test_concept_name_normalises(raw: str, want: str) -> None:
    """Names are lowercased, single-spaced and their last word made singular."""
    assert concept_name(raw) == want


def test_tagging_reuses_a_concept_by_name_or_alias(store: Store, seed_topics: Seed) -> None:
    """Same normalised name or a merged-away alias lands on one concept; repeats tag once."""
    q = seed_topics.questions
    with store.db.transaction():
        first = store.concepts.tag_question(q["problem"], ["Snapshots", "snapshot", ""], AT)
        other = store.concepts.ensure(["Snapshot isolation"])[0]
        store.concepts.merge(first[0].id, other.id)
        again = store.concepts.tag_question(q["gil"], ["snapshot isolation"], AT)
        store.concepts.tag_question(q["gil"], ["snapshot"], AT)
    assert [c.name for c in first] == ["snapshot"]
    assert again == first
    assert store.concepts.get(other.id) is None
    assert [c.name for c in store.concepts.list_all()] == ["snapshot"]


def test_merge_keeps_one_tag_per_question_and_claim(store: Store, seed_topics: Seed) -> None:
    """A question or claim tagged with both concepts keeps one tag on the kept concept."""
    q, claim = seed_topics.questions["problem"], seed_topics.claims[0]
    with store.db.transaction():
        a, b = store.concepts.tag_question(q, ["a concept", "b concept"], AT)
        store.concepts.tag_claim(claim, ["a concept", "b concept"])
        store.concepts.merge(a.id, b.id)
    counts = [
        store.db.conn.execute(f"SELECT COUNT(*), MIN(concept_id) FROM {t}").fetchone()
        for t in ("question_concept", "claim_concept")
    ]
    assert counts == [(1, str(a.id))] * 2


def test_list_all_by_topic_covers_question_and_claim_tags(store: Store, seed_topics: Seed) -> None:
    """A topic's concepts are those on its questions or its claims, by name."""
    iceberg = seed_topics.topics["iceberg"]
    with store.db.transaction():
        store.concepts.tag_question(seed_topics.questions["problem"], ["metadata"], AT)
        store.concepts.tag_claim(seed_topics.claims[0], ["commit"])
        store.concepts.tag_question(seed_topics.questions["gil"], ["gil"], AT)
    assert [c.name for c in store.concepts.list_all(iceberg)] == ["commit", "metadata"]


def test_merge_follows_alias_chains_and_drops_a_self_parent(
    store: Store, seed_topics: Seed
) -> None:
    """a into b then b into c: "a" resolves to c, and c, once b's child, has no parent."""
    with store.db.transaction():
        a, b, c = store.concepts.ensure(["a concept", "b concept", "c concept"])
        store.db.conn.execute("UPDATE concept SET parent_concept_id = ? WHERE id = ?", (b.id, c.id))
        store.concepts.merge(b.id, a.id)
        kept = store.concepts.merge(c.id, b.id)
        again = store.concepts.ensure(["a concept"])
    assert again == [kept] and kept.parent_concept_id is None
