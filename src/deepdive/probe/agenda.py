import re
from dataclasses import dataclass
from uuid import UUID

from deepdive.config import ProbeConfig
from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation, QuestionStatus
from deepdive.store.models import Question
from deepdive.store.repos import Store

# Lower ranks first. Within a rank, oldest first (ids are time-ordered).
KINDS = ("clash", "agenda", "frontier", "challenge", "open")
_WORD = re.compile(r"[^\W_]{4,}")


@dataclass(frozen=True)
class AgendaEntry:
    question_id: UUID
    kind: str
    question: str
    queries: list[str]


class AgendaBuilder:
    """Ranks a topic's unresolved questions into at most `searches_per_topic` search targets.

    The cap is on agenda items; V1-02 enforces the actual search budget."""

    def __init__(self, store: Store, config: ProbeConfig) -> None:
        self.store = store
        self.limit = config.searches_per_topic

    def build(self, topic_id: UUID) -> list[AgendaEntry]:
        unresolved = (QuestionStatus.OPEN, QuestionStatus.PARTIAL)
        questions = [
            q for s in unresolved for q in self.store.questions.list_by_status(topic_id, s)
        ]
        have = {q.id for q in questions}
        frontier = [
            q for q in self.store.frontier.list_for_topic(topic_id) if q.status in unresolved
        ]
        questions += [q for q in frontier if q.id not in have]
        frontier_ids = {q.id for q in frontier}
        item = self.store.agenda.next_open(topic_id)
        facet_words = set(_WORD.findall(item.facet.casefold())) if item else set()
        charter = self.store.charters.get_latest(topic_id)
        keywords = charter.in_scope if charter else []

        def kind(q: Question) -> str:
            if self._clashes(q):
                return "clash"
            # no question-to-agenda-item link in the schema, so "on the item" = shares a word
            # with the facet (shortcut: crude, upgrade when questions get an agenda_item_id)
            if facet_words & set(_WORD.findall(q.clean_text.casefold())):
                return "agenda"
            if q.id in frontier_ids:
                return "frontier"
            return "challenge" if q.asker == QuestionAsker.SKEPTIC else "open"

        ranked = sorted((KINDS.index(kind(q)), q.id, q) for q in questions)
        return [
            AgendaEntry(q.id, KINDS[rank], q.clean_text, self._queries(q.clean_text, keywords))
            for rank, _, q in ranked[: self.limit]
        ]

    def _clashes(self, question: Question) -> bool:
        edges = self.store.edges.list_for_question(question.id)
        return any(e.relation == QuestionEdgeRelation.CLASHES for e in edges)

    @staticmethod
    def _queries(text: str, keywords: list[str]) -> list[str]:
        """The question as asked, then with one and two charter scope terms the text lacks added:
        terms narrow the search to the topic's map, and the plain form keeps recall."""
        extra = [k for k in keywords if k.casefold() not in text.casefold()]
        return [text] + [f"{text} {' '.join(extra[:n])}" for n in (1, 2) if len(extra) >= n]
