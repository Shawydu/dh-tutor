import sqlite3
from uuid import UUID

import pytest

from deepdive.store.errors import TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import charters, topics


def _write(db: sqlite3.Connection, topic_id: UUID, done_when: str = "done") -> int:
    return charters.write(
        db,
        topic_id,
        core_questions=["why?"],
        in_scope=["a", "b"],
        parked=[],
        done_when=done_when,
    ).version


def test_versions_count_up_per_topic(db: sqlite3.Connection) -> None:
    one = topics.create(db, "One")
    two = topics.create(db, "Two")
    assert [_write(db, one.id), _write(db, one.id), _write(db, two.id)] == [1, 2, 1]
    assert [c.version for c in charters.list_versions(db, one.id)] == [1, 2]


def test_get_latest_and_get_version_round_trip_the_lists(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "One")
    _write(db, topic.id, "first")
    _write(db, topic.id, "second")
    latest = charters.get_latest(db, topic.id)
    assert latest is not None
    assert (latest.version, latest.done_when) == (2, "second")
    assert (latest.core_questions, latest.in_scope, latest.parked) == (["why?"], ["a", "b"], [])
    old = charters.get_version(db, topic.id, 1)
    assert old is not None
    assert old.done_when == "first"


def test_missing_charter_and_unknown_topic(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "One")
    assert charters.get_latest(db, topic.id) is None
    assert charters.get_version(db, topic.id, 1) is None
    assert charters.list_versions(db, topic.id) == []
    with pytest.raises(TopicNotFoundError):
        _write(db, new_id())
