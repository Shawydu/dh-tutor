import sqlite3

import pytest

from deepdive.store.errors import AgendaItemNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import agenda, topics


def test_replace_items_orders_them_and_next_open_follows_done(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    items = agenda.replace_items(db, topic.id, ["gil", "io", "cpu"])
    assert [(i.facet, i.order, i.status) for i in items] == [
        ("gil", 1, "open"),
        ("io", 2, "open"),
        ("cpu", 3, "open"),
    ]
    first = agenda.next_open(db, topic.id)
    assert first is not None
    assert first.facet == "gil"
    assert agenda.mark_done(db, first.id).status == "done"
    second = agenda.next_open(db, topic.id)
    assert second is not None
    assert second.facet == "io"
    for item in items:
        agenda.mark_done(db, item.id)
    assert agenda.next_open(db, topic.id) is None


def test_replace_items_swaps_the_whole_agenda_for_one_topic_only(db: sqlite3.Connection) -> None:
    one = topics.create(db, "One")
    two = topics.create(db, "Two")
    agenda.replace_items(db, one.id, ["a", "b"])
    agenda.replace_items(db, two.id, ["x"])
    new = agenda.replace_items(db, one.id, ["c"])
    assert [i.facet for i in new] == ["c"]
    assert [i.facet for i in agenda.list_items(db, two.id)] == ["x"]
    assert agenda.replace_items(db, one.id, []) == []


def test_failed_replace_leaves_the_old_agenda(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    agenda.replace_items(db, topic.id, ["keep"])
    with pytest.raises(sqlite3.IntegrityError):
        agenda.replace_items(db, topic.id, ["new", None])  # type: ignore[list-item]  # NOT NULL fails after the delete
    assert [i.facet for i in agenda.list_items(db, topic.id)] == ["keep"]


def test_unknown_topic_and_item(db: sqlite3.Connection) -> None:
    with pytest.raises(TopicNotFoundError):
        agenda.replace_items(db, new_id(), ["x"])
    with pytest.raises(AgendaItemNotFoundError):
        agenda.mark_done(db, new_id())
