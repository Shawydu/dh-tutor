"""Typed store errors. `code` is the stable snake_case name the MCP layer returns to agents."""

from typing import ClassVar
from uuid import UUID


class StoreError(Exception):
    code: ClassVar[str] = "store_error"


class ChildDepthError(StoreError):
    """A child topic cannot itself have children (invariant 4)."""

    code = "child_depth_exceeded"


class InvalidSourceError(StoreError):
    """A source needs a URL or a DOI to be deduplicated by."""

    code = "invalid_source"


class SourceRequiredError(StoreError):
    """A claim must cite at least one source (invariant 2)."""

    code = "source_required"


class NotFoundError(StoreError):
    entity: ClassVar[str]

    def __init__(self, id_: UUID) -> None:
        super().__init__(f"{self.entity} {id_} not found")
        self.id = id_


class TopicNotFoundError(NotFoundError):
    entity = "topic"
    code = "topic_not_found"


class SessionNotFoundError(NotFoundError):
    entity = "session"
    code = "session_not_found"


class AgendaItemNotFoundError(NotFoundError):
    entity = "agenda item"
    code = "agenda_item_not_found"


class QuestionNotFoundError(NotFoundError):
    entity = "question"
    code = "question_not_found"


class SourceNotFoundError(NotFoundError):
    entity = "source"
    code = "source_not_found"


class ClaimNotFoundError(NotFoundError):
    entity = "claim"
    code = "claim_not_found"


class EvidenceNotFoundError(NotFoundError):
    entity = "evidence"
    code = "evidence_not_found"


class CharterNotFoundError(StoreError):
    """The topic has no charter yet, or not that version."""

    code = "charter_not_found"


class ProbeRunNotFoundError(NotFoundError):
    entity = "probe run"
    code = "probe_run_not_found"


class DuplicateSourceError(StoreError):
    """The topic already has a discovery or evidence citing this source."""

    code = "duplicate_source"


class InvalidTargetError(StoreError):
    """A discovery's target must be an existing question or claim of the same topic."""

    code = "invalid_target"


class DigestNotFoundError(StoreError):
    """No digest file was built for the day."""

    code = "not_found"
