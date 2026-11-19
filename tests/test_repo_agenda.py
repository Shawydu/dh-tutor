import sqlite3
from collections.abc import Callable

import pytest

from deepdive.store.errors import AgendaItemNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store


def test_replace_items_orders_them_and_next_open_follows_done(store: Store) -> None:
    """replace_items numbers facets in order and next_open skips done items."""
    topic = store.topics.create("T")
    items = store.agenda.replace_items(topic.id, ["gil", "io", "cpu"])
    assert [(i.facet, i.order, i.status) for i in items] == [
        ("gil", 1, "open"),
        ("io", 2, "open"),
        ("cpu", 3, "open"),
    ]
    first = store.agenda.next_open(topic.id)
    assert first is not None
    assert first.facet == "gil"
    assert store.agenda.mark_done(first.id).status == "done"
    second = store.agenda.next_open(topic.id)
    assert second is not None
    assert second.facet == "io"
    for item in items:
        store.agenda.mark_done(item.id)
    assert store.agenda.next_open(topic.id) is None


def test_replace_items_swaps_the_whole_agenda_for_one_topic_only(store: Store) -> None:
    """replace_items swaps one topic's agenda and leaves other topics alone."""
    one = store.topics.create("One")
    two = store.topics.create("Two")
    store.agenda.replace_items(one.id, ["a", "b"])
    store.agenda.replace_items(two.id, ["x"])
    new = store.agenda.replace_items(one.id, ["c"])
    assert [i.facet for i in new] == ["c"]
    assert [i.facet for i in store.agenda.list_items(two.id)] == ["x"]
    assert store.agenda.replace_items(one.id, []) == []


def test_failed_replace_leaves_the_old_agenda(store: Store) -> None:
    """A replace that fails midway keeps the previous agenda."""
    topic = store.topics.create("T")
    store.agenda.replace_items(topic.id, ["keep"])
    with pytest.raises(sqlite3.IntegrityError):
        store.agenda.replace_items(topic.id, ["new", None])  # type: ignore[list-item]  # NOT NULL fails after the delete
    assert [i.facet for i in store.agenda.list_items(topic.id)] == ["keep"]


type Call = Callable[[Store], object]

CASES: list[tuple[type[Exception], Call]] = [
    (TopicNotFoundError, lambda s: s.agenda.replace_items(new_id(), ["x"])),
    (AgendaItemNotFoundError, lambda s: s.agenda.mark_done(new_id())),
]


@pytest.mark.parametrize(
    ("error", "call"),
    CASES,
    ids=["unknown-topic", "unknown-item"],
)
def test_unknown_ids_are_typed_errors(store: Store, error: type[Exception], call: Call) -> None:
    """Writing against a missing topic or agenda item raises its typed error."""
    with pytest.raises(error):
        call(store)
