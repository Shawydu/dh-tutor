from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from deepdive import clock
from deepdive.store.enums import QuestionAsker
from deepdive.store.errors import (
    AgendaItemNotFoundError,
    QuestionNotFoundError,
    SessionNotFoundError,
    TopicNotFoundError,
)
from deepdive.store.ids import new_id
from deepdive.store.models import Bookmark
from deepdive.store.repos import Store

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_start_bookmark_end(store: Store, frozen_clock: object) -> None:
    """A session starts, takes a bookmark and ends with a summary."""
    topic = store.topics.create("T")
    (item,) = store.agenda.replace_items(topic.id, ["facet"])
    question = store.questions.add(topic.id, QuestionAsker.USER, "raw", "clean")
    session = store.sessions.start(topic.id, at=clock.now())
    assert session.started_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert (session.ended_at, session.bookmark, session.summary) == (None, None, None)

    marked = store.sessions.bookmark(
        session.id, agenda_item_id=item.id, question_id=question.id, note="mid-GIL"
    )
    assert marked.bookmark == Bookmark(
        agenda_item_id=item.id, question_id=question.id, note="mid-GIL"
    )

    ended = store.sessions.end(session.id, "covered the GIL", at=T0 + timedelta(hours=13))
    assert (ended.ended_at, ended.summary) == (T0 + timedelta(hours=13), "covered the GIL")
    assert ended.bookmark == marked.bookmark


def test_bookmark_replaces_the_previous_one(store: Store) -> None:
    """A new bookmark replaces the previous one."""
    topic = store.topics.create("T")
    session = store.sessions.start(topic.id, at=T0)
    store.sessions.bookmark(session.id, note="first")
    assert store.sessions.bookmark(session.id).bookmark == Bookmark()


def test_latest_is_the_most_recent_start(store: Store, frozen_clock: object) -> None:
    """latest returns the most recently started session."""
    topic = store.topics.create("T")
    assert store.sessions.latest(topic.id) is None
    old = store.sessions.start(topic.id, at=clock.now())
    clock.set_now(clock.now() + timedelta(hours=1))
    new = store.sessions.start(topic.id, at=clock.now())
    latest = store.sessions.latest(topic.id)
    assert latest is not None
    assert (latest.id, old.id < new.id) == (new.id, True)


type Call = Callable[[Store, UUID], object]

CASES: list[tuple[type[Exception], Call]] = [
    (TopicNotFoundError, lambda s, sid: s.sessions.start(new_id(), at=T0)),
    (SessionNotFoundError, lambda s, sid: s.sessions.end(new_id(), "x", at=T0)),
    (SessionNotFoundError, lambda s, sid: s.sessions.bookmark(new_id(), note="x")),
    (AgendaItemNotFoundError, lambda s, sid: s.sessions.bookmark(sid, agenda_item_id=new_id())),
    (QuestionNotFoundError, lambda s, sid: s.sessions.bookmark(sid, question_id=new_id())),
]


@pytest.mark.parametrize(
    ("error", "call"),
    CASES,
    ids=["start-topic", "end-session", "bookmark-session", "bookmark-item", "bookmark-question"],
)
def test_unknown_ids_are_typed_errors(store: Store, error: type[Exception], call: Call) -> None:
    """Session calls naming a missing topic, session, item or question raise typed errors."""
    topic = store.topics.create("T")
    session = store.sessions.start(topic.id, at=T0)
    with pytest.raises(error):
        call(store, session.id)
    assert store.sessions.get(session.id) == session
