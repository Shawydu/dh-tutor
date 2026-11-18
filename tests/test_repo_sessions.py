import sqlite3
from datetime import UTC, datetime, timedelta

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
from deepdive.store.repos import agenda, questions, sessions, topics

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_start_bookmark_end(db: sqlite3.Connection, frozen_clock: object) -> None:
    topic = topics.create(db, "T")
    (item,) = agenda.replace_items(db, topic.id, ["facet"])
    question = questions.add(db, topic.id, QuestionAsker.USER, "raw", "clean")
    session = sessions.start(db, topic.id, at=clock.now())
    assert session.started_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert (session.ended_at, session.bookmark, session.summary) == (None, None, None)

    marked = sessions.bookmark(
        db, session.id, agenda_item_id=item.id, question_id=question.id, note="mid-GIL"
    )
    assert marked.bookmark == Bookmark(
        agenda_item_id=item.id, question_id=question.id, note="mid-GIL"
    )

    ended = sessions.end(db, session.id, "covered the GIL", at=T0 + timedelta(hours=13))
    assert (ended.ended_at, ended.summary) == (T0 + timedelta(hours=13), "covered the GIL")
    assert ended.bookmark == marked.bookmark


def test_bookmark_replaces_the_previous_one(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    session = sessions.start(db, topic.id, at=T0)
    sessions.bookmark(db, session.id, note="first")
    assert sessions.bookmark(db, session.id).bookmark == Bookmark()


def test_latest_is_the_most_recent_start(db: sqlite3.Connection, frozen_clock: object) -> None:
    topic = topics.create(db, "T")
    assert sessions.latest(db, topic.id) is None
    old = sessions.start(db, topic.id, at=clock.now())
    clock.set_now(clock.now() + timedelta(hours=1))
    new = sessions.start(db, topic.id, at=clock.now())
    latest = sessions.latest(db, topic.id)
    assert latest is not None
    assert (latest.id, old.id < new.id) == (new.id, True)


def test_unknown_ids_are_typed_errors(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    session = sessions.start(db, topic.id, at=T0)
    with pytest.raises(TopicNotFoundError):
        sessions.start(db, new_id(), at=T0)
    with pytest.raises(SessionNotFoundError):
        sessions.end(db, new_id(), "x", at=T0)
    with pytest.raises(SessionNotFoundError):
        sessions.bookmark(db, new_id(), note="x")
    with pytest.raises(AgendaItemNotFoundError):
        sessions.bookmark(db, session.id, agenda_item_id=new_id())
    with pytest.raises(QuestionNotFoundError):
        sessions.bookmark(db, session.id, question_id=new_id())
    assert sessions.get(db, session.id) == session
