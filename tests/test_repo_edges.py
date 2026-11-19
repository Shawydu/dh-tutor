import sqlite3
from collections.abc import Callable
from uuid import UUID

import pytest
from conftest import Seed

from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation
from deepdive.store.errors import QuestionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store


def _two(store: Store) -> tuple[UUID, UUID]:
    topic = store.topics.create("T")
    return (
        store.questions.add(topic.id, QuestionAsker.USER, "a", "a").id,
        store.questions.add(topic.id, QuestionAsker.USER, "b", "b").id,
    )


def test_add_and_list_from_either_end(store: Store) -> None:
    """An edge is stored with its attributes and listed from both questions."""
    a, b = _two(store)
    edge = store.edges.add(a, b, QuestionEdgeRelation.NARROWER, confidence=0.8, classifier="fake")
    assert (edge.from_id, edge.to_id, edge.relation, edge.confidence) == (a, b, "narrower", 0.8)
    assert edge.classifier == "fake"
    assert store.edges.list_for_question(a) == [edge]
    assert store.edges.list_for_question(b) == [edge]


def test_classifying_the_same_pair_again_replaces_the_edge(store: Store) -> None:
    """Re-adding an edge for the same pair replaces the earlier one."""
    a, b = _two(store)
    store.edges.add(a, b, QuestionEdgeRelation.ASPECT)
    store.edges.add(a, b, QuestionEdgeRelation.SAME, confidence=1.0)
    (only,) = store.edges.list_for_question(a)
    assert (only.relation, only.confidence) == ("same", 1.0)


type Call = Callable[[Store, UUID, UUID], object]

CASES: list[tuple[type[Exception], Call]] = [
    (
        QuestionNotFoundError,
        lambda s, a, b: s.edges.add(a, new_id(), QuestionEdgeRelation.SAME),
    ),
    (
        QuestionNotFoundError,
        lambda s, a, b: s.edges.add(new_id(), b, QuestionEdgeRelation.SAME),
    ),
    (sqlite3.IntegrityError, lambda s, a, b: s.edges.add(a, b, "bogus")),  # type: ignore[arg-type]  # str past the enum to hit the CHECK
    (
        sqlite3.IntegrityError,
        lambda s, a, b: s.edges.add(a, b, QuestionEdgeRelation.SAME, confidence=1.5),
    ),
]


@pytest.mark.parametrize(
    ("error", "call"),
    CASES,
    ids=["unknown-to", "unknown-from", "bad-relation", "confidence-out-of-range"],
)
def test_unknown_question_and_bad_values_fail(
    store: Store, error: type[Exception], call: Call
) -> None:
    """Edges to missing questions or with invalid values are refused and write nothing."""
    a, b = _two(store)
    with pytest.raises(error):
        call(store, a, b)
    assert store.edges.list_for_question(a) == []


def test_seeded_relations(store: Store, seed_topics: Seed) -> None:
    """Seeded edges, including the cross-topic one, are listed with the right relations."""
    q = seed_topics.questions
    by_other = {(e.from_id, e.to_id): e.relation for e in store.edges.list_for_question(q["gil"])}
    assert by_other[(q["threads_io"], q["gil"])] == "aspect"
    assert by_other[(q["free_threaded"], q["gil"])] == "clashes"
    cross = store.edges.list_for_question(q["commit_concurrent"])
    assert {e.to_id for e in cross if e.relation == "aspect"} == {q["locks_needed"]}
