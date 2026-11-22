"""The knowledge update rule: a concept's evidence history in, its state out."""

import math
from datetime import datetime
from uuid import UUID

from deepdive.knowledge.recap import next_recap_at
from deepdive.knowledge.store import (
    KnowledgeEvidence,
    KnowledgeState,
    KnowledgeStore,
)
from deepdive.store.enums import KnowledgeEvidenceGrade, KnowledgeEvidenceKind

# shortcut: all constants are a first guess, tune with `deepdive knowledge simulate`
GRADE_TARGET = {
    KnowledgeEvidenceGrade.WRONG: 1,
    KnowledgeEvidenceGrade.PARTIAL: 2,
    KnowledgeEvidenceGrade.CORRECT: 3,
    KnowledgeEvidenceGrade.INSIGHTFUL: 4,
}
HALF_LIFE_DAYS = 30
RECAP_MIN_LEVEL = 3  # a discovery on a concept known this well sets it due
RECENT = 5  # how many latest targets the agreement looks at


def base_weight(kind: KnowledgeEvidenceKind) -> float:
    """The weight a row of this kind is stored with: a self-rating counts less."""
    return 0.3 if kind == KnowledgeEvidenceKind.SELF_RATING else 1.0


def _target(e: KnowledgeEvidence) -> int | None:
    """The level the evidence points to; None when it points nowhere (an ungraded kind)."""
    if e.kind == KnowledgeEvidenceKind.SELF_RATING:
        return e.level
    if e.grade is not None:
        return GRADE_TARGET[e.grade]
    return 1 if e.kind == KnowledgeEvidenceKind.REPEAT_QUESTION else None


def update(evidence: list[KnowledgeEvidence], now: datetime) -> KnowledgeState:
    """The state after `evidence` (one concept, oldest first, the new row included).

    Level is the time-decayed weighted mean of the targets. Confidence is
    (1 - exp(-total weight / 3)) x agreement, where agreement is 1 - (max - min) / 3 over the last
    five targets. Stability counts recap_checks passed since the last failed one.
    """
    # shortcut: recomputed from the full history on every write, fine until a concept has
    # thousands of rows; then fold the new row into the stored state instead
    scored = [(e, t) for e in evidence if (t := _target(e)) is not None]
    weights = [
        e.weight
        * (1.0 if e.grader_confidence is None else e.grader_confidence)
        * 0.5 ** (max((now - e.created_at).total_seconds(), 0) / 86400 / HALF_LIFE_DAYS)
        for e, _ in scored
    ]
    total = sum(weights)
    level = sum(w * t for w, (_, t) in zip(weights, scored, strict=True)) / total if total else 0.0
    recent = [t for _, t in scored[-RECENT:]]
    agreement = 1 - (max(recent) - min(recent)) / 3 if recent else 0.0
    confidence = min(max((1 - math.exp(-total / 3)) * agreement, 0.0), 1.0)

    stability = 0.0
    for e in evidence:
        if e.kind == KnowledgeEvidenceKind.RECAP_CHECK:
            if e.grade in (KnowledgeEvidenceGrade.CORRECT, KnowledgeEvidenceGrade.INSIGHTFUL):
                stability += 1
            elif e.grade == KnowledgeEvidenceGrade.WRONG:
                stability = 0.0

    last = max(e.created_at for e in evidence)
    level = min(max(level, 0.0), 4.0)
    return KnowledgeState(
        concept_id=evidence[0].concept_id, level=level, confidence=confidence,
        stability=stability, last_evidence_at=last,
        next_recap_at=next_recap_at(level, confidence, stability, last),
    )  # fmt: skip


def record(
    store: KnowledgeStore,
    concept_id: UUID,
    kind: KnowledgeEvidenceKind,
    at: datetime,
    *,
    grade: KnowledgeEvidenceGrade | None = None,
    level: int | None = None,
    grader: str | None = None,
    grader_confidence: float | None = None,
    session_id: UUID | None = None,
    question_id: UUID | None = None,
) -> KnowledgeState:
    """Add evidence and bring the concept's state up to date; the caller's transaction."""
    store.add_evidence(
        concept_id, kind, base_weight(kind), at, grade=grade, level=level, grader=grader,
        grader_confidence=grader_confidence, session_id=session_id, question_id=question_id,
    )  # fmt: skip
    state = update(store.list_evidence(concept_id), at)
    store.set_state(state)
    return state
