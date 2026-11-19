import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from conftest import Seed

from deepdive.store.enums import QuestionAsker, QuestionStatus
from deepdive.store.errors import QuestionNotFoundError, SessionNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store

ACCEPTANCE_QUERY = "why can't python threads use all cores"


def test_add_get_and_status_changes(store: Store) -> None:
    """Questions can be added, fetched, re-statused and given an answer summary."""
    topic = store.topics.create("T")
    session = store.sessions.start(topic.id, at=datetime(2026, 1, 1, tzinfo=UTC))
    q = store.questions.add(
        topic.id, QuestionAsker.USER, "raw text", "Clean text?", session_id=session.id
    )
    assert (q.status, q.asker, q.session_id, q.answer_summary) == (
        QuestionStatus.OPEN,
        QuestionAsker.USER,
        session.id,
        None,
    )
    assert store.questions.get(q.id) == q
    assert store.questions.get(new_id()) is None
    assert store.questions.set_status(q.id, QuestionStatus.PARTIAL).status == "partial"
    answered = store.questions.set_answer_summary(
        q.id, "short answer", status=QuestionStatus.ANSWERED
    )
    assert (answered.answer_summary, answered.status) == ("short answer", "answered")
    kept = store.questions.set_answer_summary(q.id, "better answer")
    assert (kept.answer_summary, kept.status) == ("better answer", "answered")


def test_park_and_list_parked_by_topic_and_for_all(store: Store) -> None:
    """park marks a question parked and list_parked filters by topic or lists all."""
    one = store.topics.create("One")
    two = store.topics.create("Two")
    a = store.questions.add(one.id, QuestionAsker.USER, "a", "a")
    b = store.questions.add(two.id, QuestionAsker.USER, "b", "b")
    store.questions.add(two.id, QuestionAsker.USER, "c", "c")
    assert store.questions.list_parked() == []
    assert store.questions.park(a.id).status == "parked"
    store.questions.park(b.id)
    assert [q.id for q in store.questions.list_parked(one.id)] == [a.id]
    assert [q.id for q in store.questions.list_parked(two.id)] == [b.id]
    assert [q.id for q in store.questions.list_parked()] == [a.id, b.id]


type Call = Callable[[Store, UUID, UUID], object]

CASES: list[tuple[type[Exception], Call]] = [
    (
        TopicNotFoundError,
        lambda s, t, q: s.questions.add(new_id(), QuestionAsker.USER, "a", "a"),
    ),
    (
        SessionNotFoundError,
        lambda s, t, q: s.questions.add(t, QuestionAsker.USER, "a", "a", session_id=new_id()),
    ),
    (QuestionNotFoundError, lambda s, t, q: s.questions.park(new_id())),
    (QuestionNotFoundError, lambda s, t, q: s.questions.set_answer_summary(new_id(), "x")),
    (sqlite3.IntegrityError, lambda s, t, q: s.questions.set_status(q, "bogus")),  # type: ignore[arg-type]  # str past the enum to hit the CHECK
]


@pytest.mark.parametrize(
    ("error", "call"),
    CASES,
    ids=["unknown-topic", "unknown-session", "park-unknown", "answer-unknown", "bad-status"],
)
def test_unknown_ids_and_bad_status_fail(store: Store, error: type[Exception], call: Call) -> None:
    """Writes with missing ids or an invalid status are refused."""
    topic = store.topics.create("T")
    q = store.questions.add(topic.id, QuestionAsker.USER, "a", "a")
    with pytest.raises(error):
        call(store, topic.id, q.id)


def test_fts_finds_the_gil_question_in_the_top_five_across_topics(
    store: Store, seed_topics: Seed
) -> None:
    """FTS finds the expected question in the top five across topics."""
    found = store.questions.fts_candidates(ACCEPTANCE_QUERY, 5)
    assert seed_topics.questions["gil"] in [q.id for q in found]
    assert len(found) <= 5
    # the noise question from the Iceberg topic is reachable too, so the search spans topics
    spans = store.questions.fts_candidates("writer threads cores commits conflict")
    assert seed_topics.questions["threads_cores"] in [q.id for q in spans]


def test_fts_ranks_the_closest_wording_first(store: Store, seed_topics: Seed) -> None:
    """FTS ranks the closest wording first."""
    best = store.questions.fts_candidates("does asyncio speed up CPU-bound number crunching?")[0]
    assert best.id == seed_topics.questions["asyncio_cpu"]


def test_fts_stems_words(store: Store, seed_topics: Seed) -> None:
    """FTS matches word stems."""
    ids = [q.id for q in store.questions.fts_candidates("compacting file")]
    assert seed_topics.questions["compaction"] in ids


@pytest.mark.parametrize(
    "text",
    ["", "   \n\t", "?!", "*", "-", '"', "'", "''", '"unbalanced', "NOT AND OR", "()", "a b c"],
)
def test_fts_odd_input_without_usable_words_returns_nothing(
    store: Store, seed_topics: Seed, text: str
) -> None:
    """FTS input with no usable words returns no candidates."""
    assert store.questions.fts_candidates(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "what's the GIL's deal?",
        'the "GIL" thread*',
        "thread-safe -gil",
        "GIL AND threads OR NOT cores NEAR(x)",
        "column:gil {threads}",
        "naïve Python 线程 — GIL",
        "python\x00threads",
    ],
)
def test_fts_odd_input_never_raises(store: Store, seed_topics: Seed, text: str) -> None:
    """FTS operators and odd characters in the query never raise."""
    assert isinstance(store.questions.fts_candidates(text), list)


def test_fts_limit_and_empty_database(store: Store, seed_topics: Seed) -> None:
    """FTS honours the limit, including zero."""
    assert len(store.questions.fts_candidates("python threads cores gil", 2)) == 2
    assert store.questions.fts_candidates("python", 0) == []


def test_fts_on_an_empty_registry(store: Store) -> None:
    """FTS on an empty registry returns nothing."""
    assert store.questions.fts_candidates(ACCEPTANCE_QUERY) == []


def test_fts_status_filter_and_list_by_status(store: Store, seed_topics: Seed) -> None:
    """FTS and list_by_status filter by question status."""
    gil = seed_topics.questions["locks_needed"]
    store.questions.park(gil)
    hits = store.questions.fts_candidates("locks", status=QuestionStatus.PARKED)
    assert [q.id for q in hits] == [gil]
    assert store.questions.fts_candidates("locks", status=QuestionStatus.PARTIAL) == []
    topic = seed_topics.topics[next(iter(seed_topics.topics))]
    assert all(
        q.status == QuestionStatus.OPEN
        for q in store.questions.list_by_status(topic, QuestionStatus.OPEN)
    )
