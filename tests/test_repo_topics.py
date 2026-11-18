import sqlite3

import pytest

from deepdive.store.enums import TopicStatus
from deepdive.store.errors import ChildDepthError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import topics


def test_create_get_and_default_status(db: sqlite3.Connection) -> None:
    created = topics.create(db, "Threads")
    assert (created.title, created.status, created.pinned) == (
        "Threads",
        TopicStatus.SCOPING,
        False,
    )
    assert created.parent_topic_id is None
    assert topics.get(db, created.id) == created
    assert topics.get(db, new_id()) is None


def test_list_all_nests_children_and_puts_pinned_first(db: sqlite3.Connection) -> None:
    first = topics.create(db, "First")
    second = topics.create(db, "Second")
    child = topics.create(db, "Child of second", parent_topic_id=second.id)
    assert [t.id for t in topics.list_all(db)] == [first.id, second.id]
    topics.pin(db, second.id)
    listed = topics.list_all(db)
    assert [t.id for t in listed] == [second.id, first.id]
    assert [c.id for c in listed[0].children] == [child.id]
    assert listed[1].children == []
    assert topics.unpin(db, second.id).pinned is False


def test_set_status(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "Threads")
    assert topics.set_status(db, topic.id, TopicStatus.ACTIVE).status == "active"


def test_unknown_topic_is_a_typed_error(db: sqlite3.Connection) -> None:
    with pytest.raises(TopicNotFoundError):
        topics.set_status(db, new_id(), TopicStatus.ACTIVE)
    with pytest.raises(TopicNotFoundError):
        topics.pin(db, new_id())
    with pytest.raises(TopicNotFoundError):
        topics.create(db, "Orphan", parent_topic_id=new_id())


def test_child_of_a_child_is_refused(db: sqlite3.Connection) -> None:
    parent = topics.create(db, "Parent")
    child = topics.create(db, "Child", parent_topic_id=parent.id)
    with pytest.raises(ChildDepthError):
        topics.create(db, "Grandchild", parent_topic_id=child.id)
    assert [t.title for t in topics.list_all(db)] == ["Parent"]
    assert len(topics.list_all(db)[0].children) == 1


def test_db_trigger_error_becomes_child_depth_error_too(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = topics.create(db, "Parent")
    child = topics.create(db, "Child", parent_topic_id=parent.id)
    monkeypatch.setattr(topics, "_check_parent", lambda conn, parent_id: None)
    with pytest.raises(ChildDepthError):
        topics.create(db, "Grandchild", parent_topic_id=child.id)
