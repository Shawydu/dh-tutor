import re
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from uuid import UUID

from deepdive.config import ProbeConfig
from deepdive.store.enums import (
    AgendaItemStatus,
    QuestionAsker,
    QuestionEdgeRelation,
    QuestionStatus,
)
from deepdive.store.models import Question
from deepdive.store.repos import Store
from deepdive.store.repos.questions import STOP_WORDS

# Lower ranks first. Within a rank, oldest first (ids are time-ordered).
KINDS = ("clash", "agenda", "frontier", "challenge", "open")
_WORD = re.compile(r"[^\W_]{4,}")
_TOKEN = re.compile(r"[^\W_]+")
QUERY_WORDS = 2  # providers AND these, so only the charter terms or the head of the title
MAX_KEYWORDS = 6
# a facet the user does by hand, which a web search cannot research
# shortcut: keyword guess, upgrade when agenda items get a kind column
_HANDS_ON = re.compile(
    r"\b(hands-on|experiment|exercise|try|build|implement|lab|poc|practice)\b", re.I
)


@dataclass(frozen=True)
class AgendaEntry:
    """One search target: an unresolved question (question_id) or an open agenda facet
    (question_id None, agenda_item_id set; `question` then holds the facet text)."""

    question_id: UUID | None
    kind: str
    question: str
    query: str
    keywords: list[str]
    agenda_item_id: UUID | None = None


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
        # a re-asked question is stored again with a `same` edge; research only the earliest
        questions = [q for q in questions if not self._repeat_of_earlier(q)]
        frontier_ids = {q.id for q in frontier}
        item = next(
            (
                i
                for i in self.store.agenda.list_items(topic_id)
                if i.status == AgendaItemStatus.OPEN and not _HANDS_ON.search(i.facet)
            ),
            None,
        )
        facet_words = set(_WORD.findall(item.facet.casefold())) if item else set()
        title = self.store.topics.require(topic_id).title
        charter = self.store.charters.get_latest(topic_id)
        terms = (charter.search_terms if charter else []) or search_words(title) or title.split()
        query = " ".join(terms[:QUERY_WORDS])
        skip = {w.casefold() for w in query.split()}

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

        ranked = sorted(((KINDS.index(kind(q)), q.id, q) for q in questions), key=lambda r: r[:2])
        entries = [
            AgendaEntry(
                q.id,
                KINDS[rank],
                q.clean_text,
                query,
                search_words(f"{q.clean_text} {title}", skip),
            )
            for rank, _, q in ranked
        ]
        if item:  # one facet per run, after every question: the nightly probe walks them in order
            entries.append(
                AgendaEntry(
                    None,
                    "agenda",
                    item.facet,
                    query,
                    search_words(f"{item.facet} {title}", skip),
                    item.id,
                )
            )
        return entries[: self.limit]

    def _repeat_of_earlier(self, question: Question) -> bool:
        """A `same` edge to any earlier question, whatever its status (ids are time-ordered)."""
        return any(
            e.relation == QuestionEdgeRelation.SAME
            and min(e.from_id, e.to_id) < question.id
            and question.id in (e.from_id, e.to_id)
            for e in self.store.edges.list_for_question(question.id)
        )

    def _clashes(self, question: Question) -> bool:
        edges = self.store.edges.list_for_question(question.id)
        return any(e.relation == QuestionEdgeRelation.CLASHES for e in edges)


def search_words(text: str, skip: AbstractSet[str] = frozenset()) -> list[str]:
    """Search keywords from free text: no stop words, no repeats, nothing in `skip`
    (casefolded), at most MAX_KEYWORDS. Two-letter words survive only in capitals (IO, GC)."""
    seen = {*STOP_WORDS, *skip}
    out: list[str] = []
    for w in _TOKEN.findall(text):
        if (len(w) > 2 or w.isupper()) and w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return out[:MAX_KEYWORDS]
