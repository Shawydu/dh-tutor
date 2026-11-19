import sqlite3
from datetime import UTC, datetime

import pytest
from conftest import Seed

from deepdive.store.enums import TopicStatus
from deepdive.store.errors import ChildDepthError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import agenda, sessions, topics


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


def test_overview_counts_on_seeded_topics(db: sqlite3.Connection, seed_topics: Seed) -> None:
    py, ice = seed_topics.topics["python-concurrency"], seed_topics.topics["iceberg"]
    first = agenda.list_items(db, py)[0]
    agenda.mark_done(db, first.id)
    session = sessions.start(db, py, at=datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC))
    child = topics.create(db, "GIL deep dive", parent_topic_id=py)
    topics.pin(db, ice)
    got = topics.overview(db)
    assert [t.id for t in got] == [ice, py]  # pinned first; the child is not top level
    by_id = {t.id: t for t in got}
    assert (by_id[py].agenda_done, by_id[py].agenda_total) == (1, 4)
    assert (by_id[py].open_questions, by_id[py].parked_questions) == (3, 1)
    assert (by_id[ice].open_questions, by_id[ice].parked_questions) == (3, 1)
    assert (by_id[py].charter_version, by_id[py].last_session_at) == (1, session.started_at)
    assert by_id[ice].last_session_at is None and by_id[ice].pinned
    assert [c.id for c in by_id[py].children] == [child.id]
    assert by_id[py].children[0].charter_version is None
