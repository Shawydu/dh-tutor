"""charter, agenda_item, source, claim and evidence remember the writing session."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from deepdive.store.enums import EvidenceStance
from deepdive.store.errors import SessionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store

AT = datetime(2026, 1, 1, tzinfo=UTC)


def _topic_and_session(store: Store) -> tuple[UUID, UUID]:
    topic = store.topics.create("T")
    return topic.id, store.sessions.start(topic.id, at=AT).id


def test_every_writer_stores_the_session_id(store: Store) -> None:
    """Every writer stores the session id it is given."""
    topic_id, sid = _topic_and_session(store)
    charter = store.charters.write(
        topic_id, core_questions=["q"], in_scope=[], parked=[], done_when="d", session_id=sid
    )
    items = store.agenda.replace_items(topic_id, ["a", "b"], session_id=sid)
    source = store.sources.register(
        url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=sid
    )
    claim = store.claims.add(topic_id, "c", [source.id], session_id=sid)
    extra = store.evidence.add(claim.id, source.id, EvidenceStance.WEAKENS, session_id=sid)
    assert charter.session_id == sid
    assert [i.session_id for i in items] == [sid, sid]
    assert source.session_id == sid
    assert claim.session_id == sid
    assert [e.session_id for e in store.evidence.list_for_claim(claim.id)] == [sid, sid]
    assert extra.session_id == sid


def test_session_id_defaults_to_null(store: Store) -> None:
    """Without a session the stored session id is NULL."""
    topic_id, _ = _topic_and_session(store)
    source = store.sources.register(url="https://e.com/a", kind="docs", tier=1, seen_at=AT)
    claim = store.claims.add(topic_id, "c", [source.id])
    assert (source.session_id, claim.session_id) == (None, None)
    assert [e.session_id for e in store.evidence.list_for_claim(claim.id)] == [None]


def test_mark_done_records_the_session_and_register_keeps_the_first(store: Store) -> None:
    """mark_done records the session; a repeat register keeps the first session."""
    topic_id, first = _topic_and_session(store)
    second = store.sessions.start(topic_id, at=AT).id
    item = store.agenda.replace_items(topic_id, ["a"], session_id=first)[0]
    assert store.agenda.mark_done(item.id, session_id=second).session_id == second
    assert store.agenda.mark_done(item.id).session_id == second  # no session given: keeps the last
    one = store.sources.register(
        url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=first
    )
    again = store.sources.register(
        url="https://e.com/a", kind="docs", tier=1, seen_at=AT, session_id=second
    )
    assert (again.id, again.session_id) == (one.id, first)


type Call = Callable[[Store, UUID, UUID], object]

CASES: list[Call] = [
    lambda s, t, src: s.charters.write(
        t, core_questions=[], in_scope=[], parked=[], done_when="d", session_id=new_id()
    ),
    lambda s, t, src: s.agenda.replace_items(t, ["a"], session_id=new_id()),
    lambda s, t, src: s.sources.register(
        url="https://e.com/b", kind="docs", tier=1, seen_at=AT, session_id=new_id()
    ),
    lambda s, t, src: s.claims.add(t, "c", [src], session_id=new_id()),
]


@pytest.mark.parametrize(
    "write",
    CASES,
    ids=["charter", "agenda", "source", "claim"],
)
def test_an_unknown_session_is_refused_and_writes_nothing(store: Store, write: Call) -> None:
    """A write naming a missing session raises and leaves every table untouched."""
    topic_id, _ = _topic_and_session(store)
    source = store.sources.register(url="https://e.com/a", kind="docs", tier=1, seen_at=AT)
    with pytest.raises(SessionNotFoundError):
        write(store, topic_id, source.id)
    assert store.charters.list_versions(topic_id) == []
    assert store.agenda.list_items(topic_id) == []
    assert store.claims.list_for_topic(topic_id) == []
    assert store.evidence.list_for_topic(topic_id) == []
    assert store.sources.find(url="https://e.com/b") is None
