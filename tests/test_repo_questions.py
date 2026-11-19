import sqlite3
from datetime import UTC, datetime

import pytest
from conftest import Seed

from deepdive.store.enums import QuestionAsker, QuestionStatus
from deepdive.store.errors import QuestionNotFoundError, SessionNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import questions, sessions, topics

ACCEPTANCE_QUERY = "why can't python threads use all cores"


def test_add_get_and_status_changes(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    session = sessions.start(db, topic.id, at=datetime(2026, 1, 1, tzinfo=UTC))
    q = questions.add(
        db, topic.id, QuestionAsker.USER, "raw text", "Clean text?", session_id=session.id
    )
    assert (q.status, q.asker, q.session_id, q.answer_summary) == (
        QuestionStatus.OPEN,
        QuestionAsker.USER,
        session.id,
        None,
    )
    assert questions.get(db, q.id) == q
    assert questions.get(db, new_id()) is None
    assert questions.set_status(db, q.id, QuestionStatus.PARTIAL).status == "partial"
    answered = questions.set_answer_summary(
        db, q.id, "short answer", status=QuestionStatus.ANSWERED
    )
    assert (answered.answer_summary, answered.status) == ("short answer", "answered")
    kept = questions.set_answer_summary(db, q.id, "better answer")
    assert (kept.answer_summary, kept.status) == ("better answer", "answered")


def test_park_and_list_parked_by_topic_and_for_all(db: sqlite3.Connection) -> None:
    one = topics.create(db, "One")
    two = topics.create(db, "Two")
    a = questions.add(db, one.id, QuestionAsker.USER, "a", "a")
    b = questions.add(db, two.id, QuestionAsker.USER, "b", "b")
    questions.add(db, two.id, QuestionAsker.USER, "c", "c")
    assert questions.list_parked(db) == []
    assert questions.park(db, a.id).status == "parked"
    questions.park(db, b.id)
    assert [q.id for q in questions.list_parked(db, one.id)] == [a.id]
    assert [q.id for q in questions.list_parked(db, two.id)] == [b.id]
    assert [q.id for q in questions.list_parked(db)] == [a.id, b.id]


def test_unknown_ids_and_bad_status_fail(db: sqlite3.Connection) -> None:
    topic = topics.create(db, "T")
    q = questions.add(db, topic.id, QuestionAsker.USER, "a", "a")
    with pytest.raises(TopicNotFoundError):
        questions.add(db, new_id(), QuestionAsker.USER, "a", "a")
    with pytest.raises(SessionNotFoundError):
        questions.add(db, topic.id, QuestionAsker.USER, "a", "a", session_id=new_id())
    with pytest.raises(QuestionNotFoundError):
        questions.park(db, new_id())
    with pytest.raises(QuestionNotFoundError):
        questions.set_answer_summary(db, new_id(), "x")
    with pytest.raises(sqlite3.IntegrityError):  # the enum table is the last line of defence
        questions.set_status(db, q.id, "bogus")  # type: ignore[arg-type]


def test_fts_finds_the_gil_question_in_the_top_five_across_topics(
    db: sqlite3.Connection, seed_topics: Seed
) -> None:
    found = questions.fts_candidates(db, ACCEPTANCE_QUERY, 5)
    assert seed_topics.questions["gil"] in [q.id for q in found]
    assert len(found) <= 5
    # the noise question from the Iceberg topic is reachable too, so the search spans topics
    spans = questions.fts_candidates(db, "writer threads cores commits conflict")
    assert seed_topics.questions["threads_cores"] in [q.id for q in spans]


def test_fts_ranks_the_closest_wording_first(db: sqlite3.Connection, seed_topics: Seed) -> None:
    best = questions.fts_candidates(db, "does asyncio speed up CPU-bound number crunching?")[0]
    assert best.id == seed_topics.questions["asyncio_cpu"]


def test_fts_stems_words(db: sqlite3.Connection, seed_topics: Seed) -> None:
    ids = [q.id for q in questions.fts_candidates(db, "compacting file")]
    assert seed_topics.questions["compaction"] in ids


@pytest.mark.parametrize(
    "text",
    ["", "   \n\t", "?!", "*", "-", '"', "'", "''", '"unbalanced', "NOT AND OR", "()", "a b c"],
)
def test_fts_odd_input_without_usable_words_returns_nothing(
    db: sqlite3.Connection, seed_topics: Seed, text: str
) -> None:
    assert questions.fts_candidates(db, text) == []


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
def test_fts_odd_input_never_raises(db: sqlite3.Connection, seed_topics: Seed, text: str) -> None:
    assert isinstance(questions.fts_candidates(db, text), list)


def test_fts_limit_and_empty_database(db: sqlite3.Connection, seed_topics: Seed) -> None:
    assert len(questions.fts_candidates(db, "python threads cores gil", 2)) == 2
    assert questions.fts_candidates(db, "python", 0) == []


def test_fts_on_an_empty_registry(db: sqlite3.Connection) -> None:
    assert questions.fts_candidates(db, ACCEPTANCE_QUERY) == []


def test_fts_status_filter_and_list_by_status(db: sqlite3.Connection, seed_topics: Seed) -> None:
    gil = seed_topics.questions["locks_needed"]
    questions.park(db, gil)
    hits = questions.fts_candidates(db, "locks", status=QuestionStatus.PARKED)
    assert [q.id for q in hits] == [gil]
    assert questions.fts_candidates(db, "locks", status=QuestionStatus.PARTIAL) == []
    topic = seed_topics.topics[next(iter(seed_topics.topics))]
    assert all(
        q.status == QuestionStatus.OPEN
        for q in questions.list_by_status(db, topic, QuestionStatus.OPEN)
    )
