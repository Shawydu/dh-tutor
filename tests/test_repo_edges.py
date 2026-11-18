import sqlite3
from uuid import UUID

import pytest
from conftest import Seed

from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation
from deepdive.store.errors import QuestionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import edges, questions, topics


def _two(db: sqlite3.Connection) -> tuple[UUID, UUID]:
    topic = topics.create(db, "T")
    return (
        questions.add(db, topic.id, QuestionAsker.USER, "a", "a").id,
        questions.add(db, topic.id, QuestionAsker.USER, "b", "b").id,
    )


def test_add_and_list_from_either_end(db: sqlite3.Connection) -> None:
    a, b = _two(db)
    edge = edges.add(db, a, b, QuestionEdgeRelation.NARROWER, confidence=0.8, classifier="fake")
    assert (edge.from_id, edge.to_id, edge.relation, edge.confidence) == (a, b, "narrower", 0.8)
    assert edge.classifier == "fake"
    assert edges.list_for_question(db, a) == [edge]
    assert edges.list_for_question(db, b) == [edge]


def test_classifying_the_same_pair_again_replaces_the_edge(db: sqlite3.Connection) -> None:
    a, b = _two(db)
    edges.add(db, a, b, QuestionEdgeRelation.ASPECT)
    edges.add(db, a, b, QuestionEdgeRelation.SAME, confidence=1.0)
    (only,) = edges.list_for_question(db, a)
    assert (only.relation, only.confidence) == ("same", 1.0)


def test_unknown_question_and_bad_values_fail(db: sqlite3.Connection) -> None:
    a, b = _two(db)
    with pytest.raises(QuestionNotFoundError):
        edges.add(db, a, new_id(), QuestionEdgeRelation.SAME)
    with pytest.raises(QuestionNotFoundError):
        edges.add(db, new_id(), b, QuestionEdgeRelation.SAME)
    with pytest.raises(sqlite3.IntegrityError):  # a value outside the enum table
        edges.add(db, a, b, "bogus")  # type: ignore[arg-type]
    with pytest.raises(sqlite3.IntegrityError):
        edges.add(db, a, b, QuestionEdgeRelation.SAME, confidence=1.5)
    assert edges.list_for_question(db, a) == []


def test_seeded_relations(db: sqlite3.Connection, seed_topics: Seed) -> None:
    q = seed_topics.questions
    by_other = {(e.from_id, e.to_id): e.relation for e in edges.list_for_question(db, q["gil"])}
    assert by_other[(q["threads_io"], q["gil"])] == "aspect"
    assert by_other[(q["free_threaded"], q["gil"])] == "clashes"
    cross = edges.list_for_question(db, q["commit_concurrent"])
    assert {e.to_id for e in cross if e.relation == "aspect"} == {q["locks_needed"]}
