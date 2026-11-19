from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from conftest import Seed

from deepdive.store.enums import TopicStatus
from deepdive.store.errors import ChildDepthError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store
from deepdive.store.repos.topics import TopicRepo


def test_create_get_and_default_status(store: Store) -> None:
    """create stores a topic with default scoping status and get returns it."""
    created = store.topics.create("Threads")
    assert (created.title, created.status, created.pinned) == (
        "Threads",
        TopicStatus.SCOPING,
        False,
    )
    assert created.parent_topic_id is None
    assert store.topics.get(created.id) == created
    assert store.topics.get(new_id()) is None


def test_list_all_nests_children_and_puts_pinned_first(store: Store) -> None:
    """list_all nests children under parents and lists pinned topics first."""
    first = store.topics.create("First")
    second = store.topics.create("Second")
    child = store.topics.create("Child of second", parent_topic_id=second.id)
    assert [t.id for t in store.topics.list_all()] == [first.id, second.id]
    store.topics.pin(second.id)
    listed = store.topics.list_all()
    assert [t.id for t in listed] == [second.id, first.id]
    assert [c.id for c in listed[0].children] == [child.id]
    assert listed[1].children == []
    assert store.topics.unpin(second.id).pinned is False


def test_set_status(store: Store) -> None:
    """set_status changes a topic's status."""
    topic = store.topics.create("Threads")
    assert store.topics.set_status(topic.id, TopicStatus.ACTIVE).status == "active"


type Call = Callable[[Store], object]

CASES: list[Call] = [
    lambda s: s.topics.set_status(new_id(), TopicStatus.ACTIVE),
    lambda s: s.topics.pin(new_id()),
    lambda s: s.topics.create("Orphan", parent_topic_id=new_id()),
]


@pytest.mark.parametrize(
    "call",
    CASES,
    ids=["set-status", "pin", "create-under-unknown-parent"],
)
def test_unknown_topic_is_a_typed_error(store: Store, call: Call) -> None:
    """Changing or parenting under a missing topic raises TopicNotFoundError."""
    with pytest.raises(TopicNotFoundError):
        call(store)


def test_child_of_a_child_is_refused(store: Store) -> None:
    """A grandchild topic is refused and nothing is stored."""
    parent = store.topics.create("Parent")
    child = store.topics.create("Child", parent_topic_id=parent.id)
    with pytest.raises(ChildDepthError):
        store.topics.create("Grandchild", parent_topic_id=child.id)
    assert [t.title for t in store.topics.list_all()] == ["Parent"]
    assert len(store.topics.list_all()[0].children) == 1


def test_db_trigger_error_becomes_child_depth_error_too(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DB trigger's error also surfaces as ChildDepthError."""
    parent = store.topics.create("Parent")
    child = store.topics.create("Child", parent_topic_id=parent.id)
    monkeypatch.setattr(TopicRepo, "_check_parent", lambda self, parent_id: None)
    with pytest.raises(ChildDepthError):
        store.topics.create("Grandchild", parent_topic_id=child.id)


def test_overview_counts_on_seeded_topics(store: Store, seed_topics: Seed) -> None:
    """overview reports agenda, question, charter and session counts for top-level topics."""
    py, ice = seed_topics.topics["python-concurrency"], seed_topics.topics["iceberg"]
    first = store.agenda.list_items(py)[0]
    store.agenda.mark_done(first.id)
    session = store.sessions.start(py, at=datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC))
    child = store.topics.create("GIL deep dive", parent_topic_id=py)
    store.topics.pin(ice)
    got = store.topics.overview()
    assert [t.id for t in got] == [ice, py]  # pinned first; the child is not top level
    by_id = {t.id: t for t in got}
    assert (by_id[py].agenda_done, by_id[py].agenda_total) == (1, 4)
    assert (by_id[py].open_questions, by_id[py].parked_questions) == (3, 1)
    assert (by_id[ice].open_questions, by_id[ice].parked_questions) == (3, 1)
    assert (by_id[py].charter_version, by_id[py].last_session_at) == (1, session.started_at)
    assert by_id[ice].last_session_at is None and by_id[ice].pinned
    assert [c.id for c in by_id[py].children] == [child.id]
    assert by_id[py].children[0].charter_version is None
