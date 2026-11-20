"""Pydantic row models for the tables the v0 repos read and write.

Ids are `uuid.UUID`, instants are aware UTC datetimes, closed value sets are the StrEnums in
`store.enums`; `store.db` hands the database's UUID and TIMESTAMP columns over as those types.
Imports nothing from deepdive outside the store.
"""

import json
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from deepdive.store.enums import (
    AgendaItemStatus,
    ClaimStatus,
    EvidenceStance,
    QuestionAsker,
    QuestionEdgeRelation,
    QuestionStatus,
    TopicStatus,
)


def _from_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class Topic(BaseModel):
    id: UUID
    title: str
    parent_topic_id: UUID | None
    status: TopicStatus
    pinned: bool


class TopicNode(Topic):
    """A topic with its one level of children, as `topics.list_all` returns it."""

    children: list[Topic] = Field(default_factory=list)


class TopicStats(Topic):
    """A topic with the counts `/topics` shows."""

    charter_version: int | None
    agenda_done: int
    agenda_total: int
    open_questions: int
    parked_questions: int
    last_session_at: AwareDatetime | None


class TopicOverview(TopicStats):
    children: list[TopicStats] = Field(default_factory=list)


class Charter(BaseModel):
    topic_id: UUID
    version: int
    core_questions: list[str]
    in_scope: list[str]
    parked: list[str]
    done_when: str
    session_id: UUID | None

    _decode = field_validator("core_questions", "in_scope", "parked", mode="before")(_from_json)


class Bookmark(BaseModel):
    """Where a session left off; stored as JSON in `session.bookmark`."""

    agenda_item_id: UUID | None = None
    question_id: UUID | None = None
    note: str | None = None


class Session(BaseModel):
    id: UUID
    topic_id: UUID
    started_at: AwareDatetime
    ended_at: AwareDatetime | None
    bookmark: Bookmark | None
    summary: str | None

    _decode = field_validator("bookmark", mode="before")(_from_json)


class AgentSession(BaseModel):
    agent_session_id: UUID
    session_id: UUID
    attached_at: AwareDatetime


class AgendaItem(BaseModel):
    id: UUID
    topic_id: UUID
    facet: str
    status: AgendaItemStatus
    order: int
    session_id: UUID | None


class Question(BaseModel):
    id: UUID
    topic_id: UUID
    session_id: UUID | None
    asker: QuestionAsker
    raw_text: str
    clean_text: str
    status: QuestionStatus
    answer_summary: str | None


class QuestionEdge(BaseModel):
    from_id: UUID
    to_id: UUID
    relation: QuestionEdgeRelation
    confidence: float | None
    classifier: str | None
    repeat: bool


class Source(BaseModel):
    id: UUID
    url: str | None
    doi: str | None
    kind: str  # the domain pack's source kinds, so not an enum here
    tier: int
    first_seen_at: AwareDatetime
    session_id: UUID | None


class Claim(BaseModel):
    id: UUID
    topic_id: UUID
    text: str
    status: ClaimStatus
    session_id: UUID | None


class Evidence(BaseModel):
    id: UUID
    claim_id: UUID
    source_id: UUID
    stance: EvidenceStance
    excerpt_summary: str | None
    session_id: UUID | None
