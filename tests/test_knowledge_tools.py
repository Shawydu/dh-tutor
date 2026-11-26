"""knowledge_view, self_rate and the recaps in resume_brief: in-process ledger on temp SQLite."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_ledger_server import Ledger

from deepdive.knowledge.store import KnowledgeState, SqliteKnowledgeStore
from deepdive.ledger.server import create_server
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.repos import Store


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    paths = Paths(tmp_path)
    return Ledger(create_server(paths), paths)


def _topic(ledger: Ledger, title: str, concepts: list[str]) -> str:
    tid: str = ledger.call("topic_create", title=title)["id"]
    sid = ledger.call("session_start", topic_id=tid)["id"]
    ledger.call(
        "question_record", session_id=sid, topic_id=tid, asker="user", text="why?",
        concepts=concepts,
    )  # fmt: skip
    return tid


def test_self_rate_creates_and_normalises_the_concept_and_shows_in_the_view(
    ledger: Ledger,
) -> None:
    """self_rate makes a "Data  Structures" concept, rates it, and knowledge_view lists it."""
    tid = _topic(ledger, "T", ["data structure"])
    assert ledger.call("knowledge_view", topic_id=tid) == {"concepts": []}
    got = ledger.call("self_rate", concept="Data  Structures", level=4)
    assert got == {"concept": "data structure", "level": 4}
    (row,) = ledger.call("knowledge_view", topic_id=tid)["concepts"]
    assert (row["concept"], row["level"]) == ("data structure", 4.0)
    assert row["confidence"] == round(row["confidence"], 2)  # rounded for display
    assert ledger.count("concept") == 1
    ledger.call("self_rate", concept="brand new", level=1)
    assert len(ledger.call("knowledge_view")["concepts"]) == 2  # no topic: every concept


@pytest.mark.parametrize("level", [-1, 5])
def test_self_rate_refuses_a_level_out_of_range(ledger: Ledger, level: int) -> None:
    """A level outside 0-4 is refused at the tool boundary and stores nothing."""
    got = ledger.call("self_rate", concept="gil", level=level)
    assert got["error"] == "invalid_input"
    assert ledger.count("knowledge_evidence") == 0


def test_resume_brief_asks_for_at_most_two_due_concepts_of_the_topic(ledger: Ledger) -> None:
    """recap_checks holds up to two due concepts, only from the resumed topic."""
    mine = _topic(ledger, "mine", ["a", "b", "c"])
    _topic(ledger, "other", ["d"])
    past = datetime.now(UTC) - timedelta(days=1)
    with Database(ledger.paths.db) as db:
        for c in Store(db).concepts.list_all():
            SqliteKnowledgeStore(db).set_state(
                KnowledgeState(
                    concept_id=c.id,
                    level=2,
                    confidence=0.5,
                    stability=0,
                    last_evidence_at=None,
                    next_recap_at=past,
                )  # fmt: skip
            )
    names = [r["concept"] for r in ledger.call("resume_brief", topic_id=mine)["recap_checks"]]
    assert len(names) == 2
    assert set(names) <= {"a", "b", "c"}


def test_self_rate_works_with_grading_off(ledger: Ledger) -> None:
    """A session with grading off does not stop self_rate from rating a concept."""
    tid = _topic(ledger, "py", ["gil"])
    sid = ledger.call("session_start", topic_id=tid)["id"]
    ledger.call("session_grading_set", session_id=sid, on=False)
    assert "error" not in ledger.call("self_rate", concept="gil", level=3)
