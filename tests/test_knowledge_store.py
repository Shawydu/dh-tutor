"""KnowledgeStore conformance: every backend in BACKENDS must pass these."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from deepdive.knowledge.store import KnowledgeState, KnowledgeStore, SqliteKnowledgeStore
from deepdive.store.db import Database
from deepdive.store.enums import KnowledgeEvidenceGrade, KnowledgeEvidenceKind
from deepdive.store.repos import Store

AT = datetime(2026, 1, 1, tzinfo=UTC)
BACKENDS: list[Callable[[Database], KnowledgeStore]] = [SqliteKnowledgeStore]


@pytest.fixture(params=BACKENDS, ids=lambda b: b.__name__)
def knowledge(request: pytest.FixtureRequest, db: Database) -> KnowledgeStore:
    backend: Callable[[Database], KnowledgeStore] = request.param
    return backend(db)


def _concepts(store: Store, *names: str) -> list[UUID]:
    return [c.id for c in store.concepts.ensure(names)]


def _state(concept_id: UUID, due: datetime | None, level: int = 1) -> KnowledgeState:
    return KnowledgeState(
        concept_id=concept_id, level=level, confidence=0.5, stability=1.0,
        last_evidence_at=AT, next_recap_at=due,
    )  # fmt: skip


def test_state_round_trips_and_replaces(knowledge: KnowledgeStore, store: Store) -> None:
    """A set state reads back as set; setting again replaces it; no state reads as None."""
    a, b = _concepts(store, "a", "b")
    knowledge.set_state(_state(a, AT))
    knowledge.set_state(_state(a, AT, level=3))
    assert knowledge.get_state(a) == _state(a, AT, level=3)
    assert knowledge.get_state(b) is None


def test_list_due_is_overdue_first_and_skips_unscheduled(
    knowledge: KnowledgeStore, store: Store
) -> None:
    """Due states come most overdue first; later or unscheduled ones are left out."""
    a, b, c, d = _concepts(store, "a", "b", "c", "d")
    day = timedelta(days=1)
    for concept, due in ((a, AT), (b, AT - day), (c, AT + day), (d, None)):
        knowledge.set_state(_state(concept, due))
    assert [s.concept_id for s in knowledge.list_due(AT)] == [b, a]


def test_add_evidence_returns_the_stored_row(knowledge: KnowledgeStore, store: Store) -> None:
    """Evidence comes back with a fresh id and the values given."""
    (a,) = _concepts(store, "a")
    got = knowledge.add_evidence(
        a, KnowledgeEvidenceKind.RECAP_CHECK, 1.0, AT,
        grade=KnowledgeEvidenceGrade.CORRECT, grader="fake", grader_confidence=0.9,
    )  # fmt: skip
    assert (got.concept_id, got.grade, got.created_at) == (a, KnowledgeEvidenceGrade.CORRECT, AT)
    assert (
        got.id != knowledge.add_evidence(a, KnowledgeEvidenceKind.SELF_RATING, 0.3, AT, level=2).id
    )


@pytest.mark.parametrize("keep_has_state", [True, False], ids=["keep-wins", "drop-moves"])
def test_merge_concepts_moves_evidence_and_state(
    knowledge: KnowledgeStore, store: Store, keep_has_state: bool
) -> None:
    """Merging moves drop's rows off it; keep's state wins, else drop's state moves over."""
    keep, drop = _concepts(store, "keep", "drop")
    knowledge.add_evidence(drop, KnowledgeEvidenceKind.SELF_RATING, 0.3, AT, level=2)
    knowledge.set_state(_state(drop, AT, level=4))
    if keep_has_state:
        knowledge.set_state(_state(keep, AT, level=1))
    knowledge.merge_concepts(drop, keep)
    level = knowledge.get_state(keep)
    assert level is not None and level.level == (1 if keep_has_state else 4)
    assert knowledge.get_state(drop) is None
    store.concepts.merge(keep, drop)  # deleting drop fails while knowledge rows still point at it


def test_only_the_knowledge_package_names_the_knowledge_tables() -> None:
    """No module outside deepdive/knowledge/ touches knowledge_state or knowledge_evidence."""
    src = Path(__file__).parents[1] / "src" / "deepdive"
    offenders = [
        str(f.relative_to(src))
        for f in src.rglob("*.py")
        if "knowledge" not in f.relative_to(src).parts[:1]
        and ("knowledge_state" in f.read_text() or "knowledge_evidence" in f.read_text())
    ]
    assert offenders == []
