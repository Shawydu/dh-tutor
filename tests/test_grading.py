"""Rubric and grading tests: in-process ledger on a real temp SQLite, fake classifier."""

from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClassifier
from test_ledger_server import Ledger, _session

from deepdive.classify import Answer, ClassifierUnavailable
from deepdive.knowledge.store import KnowledgeEvidence, SqliteKnowledgeStore
from deepdive.ledger.server import create_server
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.repos import Store

KEY_POINTS = ["one thread runs bytecode at a time"]


class _Down:
    def classify(self, *_: Any) -> Any:
        raise ClassifierUnavailable("down")


def _ledger(tmp_path: Path, grade: str = "correct", p: float = 0.95, down: bool = False) -> Ledger:
    clf = _Down() if down else FakeClassifier({"grade": Answer(probs={grade: p, "wrong": 1 - p})})
    paths = Paths(tmp_path)
    return Ledger(create_server(paths, classifier=clf), paths)


def _question(
    ledger: Ledger, asker: str = "curious", concepts: list[str] | None = None
) -> tuple[str, str, str]:
    tid, sid = _session(ledger)
    q = ledger.call(
        "question_record", session_id=sid, topic_id=tid, asker=asker, text="why a GIL?",
        concepts=["GIL", "lock"] if concepts is None else concepts,
    )  # fmt: skip
    return tid, sid, q["id"]


def _evidence(ledger: Ledger) -> dict[str, list[KnowledgeEvidence]]:
    """Evidence per concept name."""
    with Database(ledger.paths.db) as db:
        knowledge = SqliteKnowledgeStore(db)
        return {c.name: knowledge.list_evidence(c.id) for c in Store(db).concepts.list_all()}


def test_confident_grade_is_stored_for_every_concept(tmp_path: Path) -> None:
    """A confident grade becomes one answered_student_q row per concept, graded by the provider."""
    ledger = _ledger(tmp_path)
    _, sid, qid = _question(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    got = ledger.call("answer_grade", question_id=qid, answer_text="one at a time", session_id=sid)
    assert (got["grade"], got["grader"], got["evidence"]) == ("correct", "fake", 2)
    rows = _evidence(ledger)
    assert set(rows) == {"gil", "lock"}
    for (row,) in rows.values():
        assert (row.kind, row.grade, row.grader, row.grader_confidence, row.weight) == (
            "answered_student_q", "correct", "fake", 0.95, 1.0,
        )  # fmt: skip
        assert (str(row.question_id), str(row.session_id)) == (qid, sid)


@pytest.mark.parametrize("down", [False, True], ids=["low-confidence", "classifier-down"])
def test_unsure_grade_returns_needs_judgement_and_stores_nothing(
    tmp_path: Path, down: bool
) -> None:
    """Below the threshold or with the classifier down: the rubric comes back, nothing stored."""
    ledger = _ledger(tmp_path, "partial", 0.5, down)
    _, sid, qid = _question(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=["x"])
    got = ledger.call("answer_grade", question_id=qid, answer_text="dunno", session_id=sid)
    assert got["needs_judgement"] is True
    assert got["rubric"]["key_points"] == KEY_POINTS
    assert got["guess"] == (None if down else {"grade": "partial", "confidence": 0.5})
    assert ledger.count("knowledge_evidence") == 0


def test_guide_grade_is_stored_with_grader_claude(tmp_path: Path) -> None:
    """answer_grade_set stores the guide's grade and confidence on every concept."""
    ledger = _ledger(tmp_path, "partial", 0.5)
    _, sid, qid = _question(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    got = ledger.call(
        "answer_grade_set", question_id=qid, grade="insightful", confidence=0.8, session_id=sid
    )
    assert (got["grader"], got["evidence"]) == ("claude", 2)
    for (row,) in _evidence(ledger).values():
        assert (row.grade, row.grader, row.grader_confidence) == ("insightful", "claude", 0.8)


def _no_rubric(ledger: Ledger) -> tuple[str, str]:
    _, sid, qid = _question(ledger)
    return qid, sid


def _no_concepts(ledger: Ledger) -> tuple[str, str]:
    _, sid, qid = _question(ledger, concepts=[])
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    return qid, sid


def _other_topic(ledger: Ledger) -> tuple[str, str]:
    qid, _ = _no_rubric(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    other = ledger.call("topic_create", title="other")["id"]
    return qid, ledger.call("session_start", topic_id=other)["id"]


def _already_graded(ledger: Ledger) -> tuple[str, str]:
    qid, sid = _no_rubric(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    ledger.call("answer_grade_set", question_id=qid, grade="correct", confidence=1, session_id=sid)
    return qid, sid


@pytest.mark.parametrize("tool", ["answer_grade", "answer_grade_set"])
@pytest.mark.parametrize("setup", [_no_rubric, _no_concepts, _other_topic, _already_graded])
def test_grading_guards(tmp_path: Path, tool: str, setup: Any) -> None:
    """Grading refuses a missing rubric or concepts, a foreign session, or a regrade."""
    ledger = _ledger(tmp_path)
    qid, sid = setup(ledger)
    before = ledger.count("knowledge_evidence")
    args = {"answer_text": "a"} if tool == "answer_grade" else {"grade": "correct", "confidence": 1}
    got = ledger.call(tool, question_id=qid, session_id=sid, **args)
    assert got["error"] == "invalid_input"
    assert ledger.count("knowledge_evidence") == before


def test_rubric_is_for_student_and_guide_questions_only(tmp_path: Path) -> None:
    """rubric_write refuses a question the user asked."""
    ledger = _ledger(tmp_path)
    _, _, qid = _question(ledger, "user")
    got = ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    assert got["error"] == "invalid_input"


def test_a_grade_updates_each_concepts_state(tmp_path: Path) -> None:
    """Grading writes the evidence and a knowledge state (level from the grade) per concept."""
    ledger = _ledger(tmp_path, "partial", 0.5)
    _, sid, qid = _question(ledger)
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    ledger.call("answer_grade_set", question_id=qid, grade="correct", confidence=1, session_id=sid)
    assert ledger.count("knowledge_state") == 2
    with Database(ledger.paths.db) as db:
        states = [SqliteKnowledgeStore(db).get_state(c.id) for c in Store(db).concepts.list_all()]
    assert all(s and s.level == pytest.approx(3) and s.next_recap_at for s in states)


def test_a_guide_question_is_graded_as_a_recap_check(tmp_path: Path) -> None:
    """A guide-asked (recap) question gets a rubric and its grade is stored as recap_check."""
    ledger = _ledger(tmp_path)
    _, sid, qid = _question(ledger, "guide")
    ledger.call("rubric_write", question_id=qid, key_points=KEY_POINTS, misconceptions=[])
    got = ledger.call("answer_grade", question_id=qid, answer_text="one at a time", session_id=sid)
    assert got["grade"] == "correct"
    assert {r.kind for (r,) in _evidence(ledger).values()} == {"recap_check"}
    again = ledger.call(
        "answer_grade_set", question_id=qid, grade="wrong", confidence=1, session_id=sid
    )
    assert again["error"] == "invalid_input"
