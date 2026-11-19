import sqlite3

import pytest
from conftest import Seed

from deepdive.store.errors import QuestionNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import frontier


def test_add_is_idempotent_and_lists_the_question(
    db: sqlite3.Connection, seed_topics: Seed
) -> None:
    topic = next(iter(seed_topics.topics.values()))
    qid = seed_topics.questions["locks_needed"]
    frontier.add(db, topic, qid)
    frontier.add(db, topic, qid)
    assert [q.id for q in frontier.list_for_topic(db, topic)] == [qid]
    other = seed_topics.topics[
        next(k for k in seed_topics.topics if seed_topics.topics[k] != topic)
    ]
    assert frontier.list_for_topic(db, other) == []


def test_unknown_ids_are_typed_errors(db: sqlite3.Connection, seed_topics: Seed) -> None:
    topic = next(iter(seed_topics.topics.values()))
    with pytest.raises(TopicNotFoundError):
        frontier.add(db, new_id(), seed_topics.questions["locks_needed"])
    with pytest.raises(QuestionNotFoundError):
        frontier.add(db, topic, new_id())
