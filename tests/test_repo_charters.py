from uuid import UUID

import pytest

from deepdive.store.errors import TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store


def _write(store: Store, topic_id: UUID, done_when: str = "done") -> int:
    return store.charters.write(
        topic_id,
        core_questions=["why?"],
        in_scope=["a", "b"],
        parked=[],
        done_when=done_when,
        search_terms=["Py"],
    ).version


def test_versions_count_up_per_topic(store: Store) -> None:
    """Charter versions count up independently per topic."""
    one = store.topics.create("One")
    two = store.topics.create("Two")
    assert [_write(store, one.id), _write(store, one.id), _write(store, two.id)] == [1, 2, 1]
    assert [c.version for c in store.charters.list_versions(one.id)] == [1, 2]


def test_get_latest_and_get_version_round_trip_the_lists(store: Store) -> None:
    """get_latest and get_version return the stored charter with its lists intact."""
    topic = store.topics.create("One")
    _write(store, topic.id, "first")
    _write(store, topic.id, "second")
    latest = store.charters.get_latest(topic.id)
    assert latest is not None
    assert (latest.version, latest.done_when) == (2, "second")
    assert (latest.core_questions, latest.in_scope, latest.parked, latest.search_terms) == (
        ["why?"],
        ["a", "b"],
        [],
        ["Py"],
    )
    old = store.charters.get_version(topic.id, 1)
    assert old is not None
    assert old.done_when == "first"


def test_missing_charter_and_unknown_topic(store: Store) -> None:
    """A topic without a charter yields None or empty; writing for an unknown topic fails."""
    topic = store.topics.create("One")
    assert store.charters.get_latest(topic.id) is None
    assert store.charters.get_version(topic.id, 1) is None
    assert store.charters.list_versions(topic.id) == []
    with pytest.raises(TopicNotFoundError):
        _write(store, new_id())
