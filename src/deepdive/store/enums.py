"""One StrEnum per enum lookup table in 0001_init.sql (table `<name>` seeds the same values).

A new value is a new member here plus an INSERT in a later migration (0006 adds
DiscoveryTargetType, 0008 its AGENDA_ITEM). Imports nothing from deepdive.
"""

from enum import StrEnum


class TopicStatus(StrEnum):
    SCOPING = "scoping"
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"


class AgendaItemStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


class QuestionAsker(StrEnum):
    USER = "user"
    GUIDE = "guide"
    CURIOUS = "curious"
    SKEPTIC = "skeptic"
    PROBE = "probe"


class CharterDriver(StrEnum):
    DECISION = "decision"
    CURIOSITY = "curiosity"
    INTERVIEW = "interview"
    OTHER = "other"


class SessionStudentMode(StrEnum):
    OFF = "off"
    CURIOUS = "curious"
    SKEPTIC = "skeptic"
    BOTH = "both"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    PARTIAL = "partial"
    PARKED = "parked"


class QuestionEdgeRelation(StrEnum):
    SAME = "same"
    NARROWER = "narrower"
    BROADER = "broader"
    ASPECT = "aspect"
    BUILDS_ON = "builds_on"
    CLASHES = "clashes"
    UNRELATED = "unrelated"


class ClaimStatus(StrEnum):
    OPEN = "open"
    ESTABLISHED = "established"
    WEAKENED = "weakened"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"


class ProbeRunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class DiscoveryEffect(StrEnum):
    ANSWERS = "answers"
    SUPPORTS = "supports"
    WEAKENS = "weakens"
    NEW_THREAD = "new_thread"


class DiscoveryTargetType(StrEnum):
    QUESTION = "question"
    CLAIM = "claim"
    AGENDA_ITEM = "agenda_item"


class KnowledgeEvidenceKind(StrEnum):
    ANSWERED_STUDENT_Q = "answered_student_q"
    REPEAT_QUESTION = "repeat_question"
    EXPLAINED_BACK = "explained_back"
    POC_COMPLETED = "poc_completed"
    RECAP_CHECK = "recap_check"
    SELF_RATING = "self_rating"


class KnowledgeEvidenceGrade(StrEnum):
    WRONG = "wrong"
    PARTIAL = "partial"
    CORRECT = "correct"
    INSIGHTFUL = "insightful"
