"""What you know per concept. Only this package touches the knowledge tables (invariant 8)."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel

from deepdive.store.db import Database
from deepdive.store.enums import KnowledgeEvidenceGrade, KnowledgeEvidenceKind
from deepdive.store.ids import new_id


class KnowledgeState(BaseModel):
    concept_id: UUID
    level: int  # 0 to 4
    confidence: float  # 0 to 1
    stability: float
    last_evidence_at: AwareDatetime | None
    next_recap_at: AwareDatetime | None


class KnowledgeEvidence(BaseModel):
    id: UUID
    concept_id: UUID
    session_id: UUID | None
    question_id: UUID | None
    kind: KnowledgeEvidenceKind
    grade: KnowledgeEvidenceGrade | None
    level: int | None  # a self-rating's claimed level
    grader: str | None
    grader_confidence: float | None
    weight: float
    created_at: AwareDatetime


class KnowledgeStore(Protocol):
    def get_state(self, concept_id: UUID) -> KnowledgeState | None: ...

    def set_state(self, state: KnowledgeState) -> None:
        """Insert or replace the concept's state."""
        ...

    def add_evidence(
        self,
        concept_id: UUID,
        kind: KnowledgeEvidenceKind,
        weight: float,
        at: datetime,
        *,
        grade: KnowledgeEvidenceGrade | None = None,
        level: int | None = None,
        grader: str | None = None,
        grader_confidence: float | None = None,
        session_id: UUID | None = None,
        question_id: UUID | None = None,
    ) -> KnowledgeEvidence: ...

    def list_due(self, now: datetime) -> list[KnowledgeState]:
        """States whose next recap is at or before `now`, most overdue first."""
        ...

    def merge_concepts(self, drop: UUID, keep: UUID) -> None:
        """Move `drop`'s evidence to `keep`; `keep`'s state wins, else `drop`'s moves over."""
        ...


_STATE = ", ".join(KnowledgeState.model_fields)
_EVIDENCE = ", ".join(KnowledgeEvidence.model_fields)


class SqliteKnowledgeStore:
    """KnowledgeStore on the deepdive database; writes run in the caller's transaction."""

    def __init__(self, db: Database) -> None:
        self.conn = db.conn

    def get_state(self, concept_id: UUID) -> KnowledgeState | None:
        found = self._states("WHERE concept_id = ?", (concept_id,))
        return found[0] if found else None

    def set_state(self, state: KnowledgeState) -> None:
        self.conn.execute(
            f"INSERT OR REPLACE INTO knowledge_state ({_STATE}) VALUES (?, ?, ?, ?, ?, ?)",
            tuple(state.model_dump().values()),
        )

    def add_evidence(
        self,
        concept_id: UUID,
        kind: KnowledgeEvidenceKind,
        weight: float,
        at: datetime,
        *,
        grade: KnowledgeEvidenceGrade | None = None,
        level: int | None = None,
        grader: str | None = None,
        grader_confidence: float | None = None,
        session_id: UUID | None = None,
        question_id: UUID | None = None,
    ) -> KnowledgeEvidence:
        row = KnowledgeEvidence(
            id=new_id(), concept_id=concept_id, session_id=session_id, question_id=question_id,
            kind=kind, grade=grade, level=level, grader=grader,
            grader_confidence=grader_confidence, weight=weight, created_at=at,
        )  # fmt: skip
        values = tuple(row.model_dump().values())
        marks = ", ".join("?" * len(values))
        self.conn.execute(f"INSERT INTO knowledge_evidence ({_EVIDENCE}) VALUES ({marks})", values)
        return row

    def list_due(self, now: datetime) -> list[KnowledgeState]:
        return self._states("WHERE next_recap_at <= ? ORDER BY next_recap_at, concept_id", (now,))

    def merge_concepts(self, drop: UUID, keep: UUID) -> None:
        self.conn.execute(
            "UPDATE knowledge_evidence SET concept_id = ? WHERE concept_id = ?", (keep, drop)
        )
        # shortcut: keep's state wins as is; recompute from the merged evidence once V2-03's
        # update rule exists
        self.conn.execute(
            "UPDATE OR IGNORE knowledge_state SET concept_id = ? WHERE concept_id = ?", (keep, drop)
        )
        self.conn.execute("DELETE FROM knowledge_state WHERE concept_id = ?", (drop,))

    def _states(self, tail: str, params: tuple[object, ...]) -> list[KnowledgeState]:
        rows = self.conn.execute(f"SELECT {_STATE} FROM knowledge_state {tail}", params)
        fields = KnowledgeState.model_fields
        return [KnowledgeState.model_validate(dict(zip(fields, r, strict=True))) for r in rows]
