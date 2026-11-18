"""charter, agenda_item, source, claim and evidence remember the writing session."""

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

import pytest

from deepdive.store.enums import EvidenceStance
from deepdive.store.errors import SessionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import agenda, charters, claims, evidence, sessions, sources, topics

AT = datetime(2026, 1, 1, tzinfo=UTC)


def _topic_and_session(db: sqlite3.Connection) -> tuple[UUID, UUID]:
    topic = topics.create(db, "T")
    return topic.id, sessions.start(db, topic.id, at=AT).id


def test_every_writer_stores_the_session_id(db: sqlite3.Connection) -> None:
    topic_id, sid = _topic_and_session(db)
    charter = charters.write(
        db, topic_id, core_questions=["q"], in_scope=[], parked=[], done_when="d", session_id=sid
    )
    items = agenda.replace_items(db, topic_id, ["a", "b"], session_id=sid)
    source = sources.register(
        db, url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=sid
    )
    claim = claims.add(db, topic_id, "c", [source.id], session_id=sid)
    extra = evidence.add(db, claim.id, source.id, EvidenceStance.WEAKENS, session_id=sid)
    assert charter.session_id == sid
    assert [i.session_id for i in items] == [sid, sid]
    assert source.session_id == sid
    assert claim.session_id == sid
    assert [e.session_id for e in evidence.list_for_claim(db, claim.id)] == [sid, sid]
    assert extra.session_id == sid


def test_session_id_defaults_to_null(db: sqlite3.Connection) -> None:
    topic_id, _ = _topic_and_session(db)
    source = sources.register(db, url="https://e.com/a", kind="docs", tier=1, seen_at=AT)
    claim = claims.add(db, topic_id, "c", [source.id])
    assert (source.session_id, claim.session_id) == (None, None)
    assert [e.session_id for e in evidence.list_for_claim(db, claim.id)] == [None]


def test_mark_done_records_the_session_and_register_keeps_the_first(db: sqlite3.Connection) -> None:
    topic_id, first = _topic_and_session(db)
    second = sessions.start(db, topic_id, at=AT).id
    item = agenda.replace_items(db, topic_id, ["a"], session_id=first)[0]
    assert agenda.mark_done(db, item.id, session_id=second).session_id == second
    assert agenda.mark_done(db, item.id).session_id == second  # no session given: keeps the last
    one = sources.register(
        db, url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=first
    )
    again = sources.register(
        db, url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=second
    )
    assert (again.id, again.session_id) == (one.id, first)


def test_an_unknown_session_is_refused_and_writes_nothing(db: sqlite3.Connection) -> None:
    topic_id, _ = _topic_and_session(db)
    source = sources.register(db, url="https://e.com/a", kind="docs", tier=1, seen_at=AT)
    with pytest.raises(SessionNotFoundError):
        charters.write(
            db,
            topic_id,
            core_questions=[],
            in_scope=[],
            parked=[],
            done_when="d",
            session_id=new_id(),
        )
    with pytest.raises(SessionNotFoundError):
        agenda.replace_items(db, topic_id, ["a"], session_id=new_id())
    with pytest.raises(SessionNotFoundError):
        sources.register(
            db, url="https://e.com/b", kind="docs", tier=1, seen_at=AT, session_id=new_id()
        )
    with pytest.raises(SessionNotFoundError):
        claims.add(db, topic_id, "c", [source.id], session_id=new_id())
    counts = [
        db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("charter", "agenda_item", "claim", "evidence")
    ]
    assert counts == [0, 0, 0, 0]
    assert sources.find(db, url="https://e.com/b") is None
