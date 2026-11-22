"""The knowledge update rule, the recap ladder, the `record` writer and `knowledge simulate`."""

from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from deepdive.cli import app
from deepdive.knowledge.recap import next_recap_at
from deepdive.knowledge.store import KnowledgeEvidence, SqliteKnowledgeStore
from deepdive.knowledge.update import base_weight, record, update
from deepdive.store.enums import KnowledgeEvidenceGrade as G
from deepdive.store.enums import KnowledgeEvidenceKind as K
from deepdive.store.ids import new_id
from deepdive.store.repos import Store

T0 = datetime(2026, 1, 1, tzinfo=UTC)
CONCEPT = new_id()


def ev(
    grade: G | None = None, day: int = 0, kind: K = K.ANSWERED_STUDENT_Q, **over: object
) -> KnowledgeEvidence:
    fields = dict(
        id=new_id(), concept_id=CONCEPT, session_id=None, question_id=None, kind=kind,
        grade=grade, level=None, grader=None, grader_confidence=None, weight=base_weight(kind),
        created_at=T0 + timedelta(days=day),
    )  # fmt: skip
    return KnowledgeEvidence.model_validate({**fields, **over})


def _states(history: list[KnowledgeEvidence]) -> list[tuple[float, float]]:
    """(level, confidence) after each prefix of the history, judged at the last row's time."""
    out = []
    for i in range(1, len(history) + 1):
        s = update(history[:i], history[i - 1].created_at)
        out.append((s.level, s.confidence))
    return out


SEQUENCES = {
    "one": [G.CORRECT],
    "mixed": [G.WRONG, G.PARTIAL, G.CORRECT, G.INSIGHTFUL, G.WRONG],
    "all_wrong": [G.WRONG] * 6,
    "all_insightful": [G.INSIGHTFUL] * 12,
}
KINDS = {  # (grade, kind, level) rows that point at a level without a grade
    "self_rating": [(None, K.SELF_RATING, 4), (G.WRONG, K.ANSWERED_STUDENT_Q, None),
                    (None, K.SELF_RATING, 1)],
    "repeat_question": [(G.CORRECT, K.ANSWERED_STUDENT_Q, None)]
    + [(None, K.REPEAT_QUESTION, None)] * 4,
}  # fmt: skip


@pytest.mark.parametrize(
    "rows",
    [[(g, K.ANSWERED_STUDENT_Q, None) for g in grades] for grades in SEQUENCES.values()]
    + list(KINDS.values()),
    ids=[*SEQUENCES, *KINDS],
)
def test_confidence_and_level_stay_in_range(rows: list[tuple[G | None, K, int | None]]) -> None:
    """Whatever the evidence, confidence is in [0, 1] and level in [0, 4]."""
    history = [ev(g, day=i * 10, kind=k, level=lv) for i, (g, k, lv) in enumerate(rows)]
    assert all(0 <= c <= 1 and 0 <= lv <= 4 for lv, c in _states(history))


@pytest.mark.parametrize(
    ("before", "gap"),
    [([G.WRONG], 0), ([G.WRONG, G.PARTIAL], 0), ([G.PARTIAL, G.WRONG, G.PARTIAL], 0),
     ([G.WRONG, G.PARTIAL], 20)],
    ids=["one", "two", "three", "spaced_in_time"],
)  # fmt: skip
def test_more_correct_evidence_never_lowers_the_level(before: list[G], gap: int) -> None:
    """Adding correct answers to a history below 'correct' only raises the level."""
    history = [ev(g) for g in before]
    levels = [
        lv for lv, _ in _states([*history, *[ev(G.CORRECT, day=gap * (i + 1)) for i in range(5)]])
    ][len(before) - 1 :]
    assert levels == sorted(levels)


def test_a_wrong_answer_after_many_correct_lowers_confidence_more_than_level() -> None:
    """One wrong after ten correct costs a larger share of confidence than of level."""
    history = [ev(G.CORRECT, day=i) for i in range(10)]
    (lv0, c0), (lv1, c1) = _states([*history, ev(G.WRONG, day=10)])[-2:]
    assert (c0 - c1) / c0 > (lv0 - lv1) / lv0


def test_old_evidence_decays_and_low_grader_confidence_counts_less() -> None:
    """A fresh wrong outweighs a month-old correct; a doubtful grader moves the level less."""
    assert update([ev(G.CORRECT, day=0), ev(G.WRONG, day=30)], T0 + timedelta(days=30)).level < 2
    sure = update([ev(G.CORRECT), ev(G.WRONG, grader_confidence=1.0)], T0).level
    unsure = update([ev(G.CORRECT), ev(G.WRONG, grader_confidence=0.2)], T0).level
    assert unsure > sure


def test_self_rating_gives_its_level_at_low_weight_and_repeat_pulls_to_one() -> None:
    """A self-rating of 4 moves a 'correct' level only a little; a repeat question pulls to 1."""
    rated = update([ev(G.CORRECT), ev(None, kind=K.SELF_RATING, level=4)], T0).level
    assert 3 < rated < 3.3
    assert update([ev(G.CORRECT), ev(None, kind=K.REPEAT_QUESTION)], T0).level == 2


def test_stability_grows_on_passed_recaps_and_resets_on_a_wrong_one() -> None:
    """recap_check correct/insightful adds one; wrong resets to zero; other kinds leave it."""
    up = [ev(G.CORRECT, kind=K.RECAP_CHECK), ev(G.INSIGHTFUL, kind=K.RECAP_CHECK), ev(G.WRONG)]
    assert update(up, T0).stability == 2
    assert update([*up, ev(G.WRONG, kind=K.RECAP_CHECK)], T0).stability == 0


@pytest.mark.parametrize(
    ("level", "confidence", "stability", "days"),
    [
        (0, 0.9, 0, 1), (1, 0.9, 0, 3), (2, 0.9, 0, 7), (3, 0.9, 0, 21), (4, 0.9, 0, 60),
        (2.4, 0.9, 0, 7), (2.6, 0.9, 0, 21),
        (1, 0.9, 2, 21), (3, 0.9, 5, 60),
        (3, 0.4, 0, 7), (0, 0.1, 0, 1), (4, 0.4, 3, 21),
    ],
    ids=[
        "level0", "level1", "level2", "level3", "level4", "rounds_down", "rounds_up",
        "stability_climbs", "capped", "low_confidence_drops", "floor", "capped_then_drops",
    ],
)  # fmt: skip
def test_recap_interval_follows_level_stability_and_confidence(
    level: float, confidence: float, stability: float, days: int
) -> None:
    """The recap ladder: rung from the rounded level, up per stability, down on low confidence."""
    assert next_recap_at(level, confidence, stability, T0) == T0 + timedelta(days=days)


def test_record_adds_evidence_and_updates_state(store: Store) -> None:
    """record() stores the row and sets the concept's state from the whole history."""
    knowledge = SqliteKnowledgeStore(store.db)
    (c,) = store.concepts.ensure(["gil"])
    with store.db.transaction():
        record(knowledge, c.id, K.ANSWERED_STUDENT_Q, T0, grade=G.CORRECT, grader_confidence=1)
        state = record(knowledge, c.id, K.REPEAT_QUESTION, T0)
        record(knowledge, c.id, K.SELF_RATING, T0, level=4)
    assert knowledge.get_state(c.id) is not None
    # level 2 is rung 7d, low confidence drops one
    assert (state.level, state.next_recap_at) == (2, T0 + timedelta(days=3))
    *_, rated = knowledge.list_evidence(c.id)
    assert (rated.weight, rated.level) == (0.3, 4)


def test_simulate_prints_the_state_after_each_event() -> None:
    """`knowledge simulate` replays the sample events file, one line per event."""
    out = CliRunner().invoke(
        app, ["knowledge", "simulate", "tests/fixtures/knowledge_events.jsonl"]
    )
    lines = out.output.splitlines()
    assert out.exit_code == 0 and len(lines) == 6
    assert "stability=0" in lines[-1] and "stability=1" in lines[3]
