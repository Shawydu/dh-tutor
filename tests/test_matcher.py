"""Question matcher tests: real temp SQLite, FakeClassifier, no network."""

import time

import pytest
from conftest import Seed

from deepdive.classify import Answer, Classifier, ClassifyResult, FakeClassifier, Question
from deepdive.config import Config
from deepdive.matcher.matcher import (
    ACTIONS,
    ADJACENT_ACTION,
    ADJACENT_IN_CHILD,
    CONTEXT_MAX,
    OUTSIDE_ACTION,
    REPEAT_ACTION,
    UNSURE_SCOPE,
    Matcher,
)
from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation, QuestionStatus
from deepdive.store.repos import Store

Rel = QuestionEdgeRelation
TEXT = "does the GIL affect numpy?"


def answer(option: str, p: float = 0.95) -> Answer:
    return Answer(probs={option: p, "other": 1 - p})


def canned(
    store: Store,
    relation: Rel,
    *,
    scope: str | None = "in",
    p: float = 0.95,
    is_question: str = "yes",
    text: str = TEXT,
) -> FakeClassifier:
    """Every FTS candidate of `text` gets `relation`; the scope and is_question answers as given."""
    answers = {f"rel_{c.id}": answer(relation, p) for c in store.questions.fts_candidates(text)}
    answers["is_question"] = answer(is_question)
    if scope:
        answers["scope"] = answer(scope)
    return FakeClassifier(answers)


def matcher(store: Store, classifier: Classifier) -> Matcher:
    return Matcher(store, classifier, Config())


def test_unrelated_is_new_with_no_edge(store: Store, seed_topics: Seed) -> None:
    """unrelated: treated as new, no edge."""
    topic = seed_topics.topics["python-concurrency"]
    got = matcher(store, canned(store, Rel.UNRELATED)).match(TEXT, topic, QuestionAsker.USER)
    assert got.kind == "matched" and got.question_id and got.related == []
    assert store.edges.list_for_question(got.question_id) == []


@pytest.mark.parametrize("relation", list(ACTIONS), ids=[r.value for r in ACTIONS])
def test_relation_maps_to_its_action(store: Store, seed_topics: Seed, relation: Rel) -> None:
    """Each design-table relation stores an edge and hands the guide that relation's action."""
    topic = seed_topics.topics["python-concurrency"]
    got = matcher(store, canned(store, relation)).match(TEXT, topic, QuestionAsker.USER)
    assert got.question_id and ACTIONS[relation] in got.guidance
    edges = store.edges.list_for_question(got.question_id)
    assert edges and {e.relation for e in edges} == {relation}
    assert {e.classifier for e in edges} == {"fake"}
    assert {r.relation for r in got.related} == {relation}


def test_student_duplicate_stores_nothing(store: Store, seed_topics: Seed) -> None:
    """A student's `same` question is a duplicate: no question row, no edge."""
    topic = seed_topics.topics["python-concurrency"]
    edges = store.db.conn.execute("SELECT COUNT(*) FROM question_edge").fetchone()[0]
    before = store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
    got = matcher(store, canned(store, Rel.SAME)).match(TEXT, topic, QuestionAsker.CURIOUS)
    assert (got.kind, got.question_id) == ("duplicate", None)
    assert store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0] == before
    assert store.db.conn.execute("SELECT COUNT(*) FROM question_edge").fetchone()[0] == edges


def test_user_repeat_marks_the_edge_and_asks_for_a_new_explanation(
    store: Store, seed_topics: Seed
) -> None:
    """A user's `same` question is stored, its edge carries repeat=True, and guidance says so."""
    topic = seed_topics.topics["python-concurrency"]
    got = matcher(store, canned(store, Rel.SAME)).match(TEXT, topic, QuestionAsker.USER)
    assert got.question_id and REPEAT_ACTION in got.guidance
    assert all(e.repeat for e in store.edges.list_for_question(got.question_id))


def test_not_a_question_stores_nothing(store: Store, seed_topics: Seed) -> None:
    """ "ok, continue" is not a question: nothing is stored."""
    topic = seed_topics.topics["python-concurrency"]
    clf = canned(store, Rel.SAME, is_question="no", text="ok, continue")
    before = store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
    got = matcher(store, clf).match("ok, continue", topic, QuestionAsker.USER)
    assert (got.kind, got.question_id) == ("not_a_question", None)
    assert store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0] == before


@pytest.mark.parametrize(
    ("scope", "status", "parked", "guidance"),
    [
        ("in", QuestionStatus.OPEN, False, None),
        ("adjacent", QuestionStatus.OPEN, False, ADJACENT_ACTION),
        ("outside", QuestionStatus.PARKED, True, OUTSIDE_ACTION),
    ],
    ids=["in", "adjacent", "outside"],
)
def test_scope_decides_status_and_guidance(
    store: Store,
    seed_topics: Seed,
    scope: str,
    status: QuestionStatus,
    parked: bool,
    guidance: str | None,
) -> None:
    """In scope is plain, adjacent offers park-or-jump, outside parks the question."""
    topic = seed_topics.topics["python-concurrency"]
    got = matcher(store, canned(store, Rel.UNRELATED, scope=scope)).match(
        TEXT, topic, QuestionAsker.USER
    )
    assert got.question_id and (got.scope, got.parked) == (scope, parked)
    assert store.questions.require(got.question_id).status == status
    assert (guidance in got.guidance) if guidance else got.guidance == []


def test_adjacent_in_a_child_topic_cannot_jump(store: Store, seed_topics: Seed) -> None:
    """Inside a child topic, adjacent offers park or the parent's frontier."""
    parent = seed_topics.topics["python-concurrency"]
    child = store.topics.create("GIL internals", parent_topic_id=parent)
    store.charters.write(child.id, core_questions=["a"], in_scope=["b"], parked=[], done_when="c")
    got = matcher(store, canned(store, Rel.UNRELATED, scope="adjacent")).match(
        TEXT, child.id, QuestionAsker.USER
    )
    assert ADJACENT_IN_CHILD in got.guidance


class Flagged:
    """FallbackClassifier-shaped: answers present, but needs_judgement set on the main call."""

    def __init__(self, answers: dict[str, Answer]) -> None:
        self.inner = FakeClassifier(answers)

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        result = self.inner.classify(state, questions)
        return result.model_copy(update={"needs_judgement": "is_question" not in questions})


@pytest.mark.parametrize(
    "answers",
    [{"is_question": answer("yes", 0.5)}, {}],
    ids=["low-confidence", "classifier-down"],
)
def test_unsure_gate_stores_nothing(
    store: Store, seed_topics: Seed, answers: dict[str, Answer]
) -> None:
    """An is_question that is not confidently yes stores nothing and skips the second call."""
    topic = seed_topics.topics["python-concurrency"]

    class Gate:  # only the gate call is answered; a second call would raise
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            assert list(questions) == ["is_question"]
            return ClassifyResult(answers=answers, provider="jev", needs_judgement=not answers)

    before = store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
    got = Matcher(store, Gate(), Config()).match(TEXT, topic, QuestionAsker.USER)
    assert (got.kind, got.question_id, got.needs_judgement) == ("unsure", None, True)
    assert "question_record" in got.guidance[0]
    assert store.db.conn.execute("SELECT COUNT(*) FROM question").fetchone()[0] == before


def test_each_answer_is_acted_on_by_its_own_confidence(store: Store, seed_topics: Seed) -> None:
    """Confident scope and relation are applied; unsure relations come back unclassified."""
    topic = seed_topics.topics["python-concurrency"]
    cands = store.questions.fts_candidates(TEXT)
    answers = {f"rel_{c.id}": answer("same", 0.5) for c in cands}
    answers[f"rel_{cands[0].id}"] = answer("narrower", 0.95)
    answers["is_question"] = answer("yes")
    answers["scope"] = answer("outside")
    got = matcher(store, Flagged(answers)).match(TEXT, topic, QuestionAsker.USER)
    assert got.question_id and got.parked and got.needs_judgement
    assert store.questions.require(got.question_id).status == QuestionStatus.PARKED
    assert [e.to_id for e in store.edges.list_for_question(got.question_id)] == [cands[0].id]
    assert [r.relation for r in got.related].count(None) == len(cands) - 1
    assert OUTSIDE_ACTION in got.guidance


def test_unsure_scope_asks_the_guide_to_judge_it(store: Store, seed_topics: Seed) -> None:
    """A scope answer under the threshold is not applied; the guidance says to judge it."""
    topic = seed_topics.topics["python-concurrency"]
    clf = canned(store, Rel.UNRELATED, scope="outside", p=0.95)
    clf._answers["scope"] = answer("outside", 0.5)
    got = matcher(store, clf).match(TEXT, topic, QuestionAsker.USER)
    assert got.question_id and not got.parked and got.scope is None and got.needs_judgement
    assert UNSURE_SCOPE in got.guidance


def test_cross_topic_same_is_a_link_not_a_duplicate(store: Store, seed_topics: Seed) -> None:
    """A student's `same` against another topic's question is stored with a plain edge."""
    topic = seed_topics.topics["iceberg"]
    text = "what does the GIL protect?"
    got = matcher(store, canned(store, Rel.SAME, text=text)).match(
        text, topic, QuestionAsker.CURIOUS
    )
    assert got.kind == "matched" and got.question_id
    assert store.edges.list_for_question(got.question_id)


def test_render_context_stays_short_with_ten_candidates(store: Store, seed_topics: Seed) -> None:
    """render_context() is under 1500 characters for 10 candidates with long answers."""
    topic = seed_topics.topics["python-concurrency"]
    for i in range(10):
        q = store.questions.add(topic, QuestionAsker.USER, f"gil {i}", f"gil question {i} " * 20)
        store.questions.set_answer_summary(q.id, "a long answer " * 100)
    got = matcher(store, canned(store, Rel.BUILDS_ON, text="gil")).match(
        "gil", topic, QuestionAsker.USER
    )
    assert len(got.related) == 10
    assert 0 < len(got.render_context()) < CONTEXT_MAX


def test_matching_1000_questions_is_fast(store: Store, seed_topics: Seed) -> None:
    """Candidate search plus recording over 1,000 stored questions: median of 5 under 200 ms."""
    topic = seed_topics.topics["python-concurrency"]
    with store.db.transaction():
        for i in range(1000):
            store.questions.add(topic, QuestionAsker.USER, f"q{i} gil w{i % 50}", f"q{i} gil w{i}")

    class Any:  # answers whatever candidates come up, since each run adds a question
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            top = {"is_question": "yes", "scope": "in"}
            return ClassifyResult(
                answers={k: answer(top.get(k, Rel.ASPECT)) for k in questions}, provider="fake"
            )

    m = matcher(store, Any())
    times = []
    for _ in range(5):
        start = time.perf_counter()
        got = m.match("gil w7 numpy", topic, QuestionAsker.USER)
        times.append(time.perf_counter() - start)
        assert got.kind == "matched"
    assert sorted(times)[2] < 0.2
