import re
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

# Lower ranks first. Within a rank, oldest first (ids are time-ordered).
KINDS = ("clash", "agenda", "frontier", "challenge", "open")
_WORD = re.compile(r"[^\W_]{4,}")
MAX_QUERY = 120
_TERM_SPLIT = re.compile(r"[:,;]")
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
    queries: list[str]
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

        ranked = sorted(((KINDS.index(kind(q)), q.id, q) for q in questions), key=lambda r: r[:2])
        entries = [
            AgendaEntry(q.id, KINDS[rank], q.clean_text, self._queries(q.clean_text, keywords))
            for rank, _, q in ranked
        ]
        if item:  # one facet per run, after every question: the nightly probe walks them in order
            entries.append(
                AgendaEntry(
                    None, "agenda", item.facet, self._queries(item.facet, keywords), item.id
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

    @staticmethod
    def _queries(text: str, keywords: list[str]) -> list[str]:
        """The text as asked (capped), then one variant with up to 3 charter terms it lacks:
        the plain form keeps recall, the terms narrow the search to the topic's map."""
        if len(text) > MAX_QUERY:
            cut = text[: MAX_QUERY + 1]
            text = (
                cut[:-1] if cut[-1] == " " else (cut.rsplit(" ", 1)[0] if " " in cut else cut[:-1])
            )
        extra: list[str] = []
        for term in (t.strip() for k in keywords for t in _TERM_SPLIT.split(k)):
            if (
                len(term) >= 3
                and term.casefold() not in text.casefold()
                and term not in extra
                and len(f"{text} {' '.join([*extra, term])}") <= MAX_QUERY
            ):
                extra.append(term)
        return [text] + ([f"{text} {' '.join(extra[:3])}"] if extra else [])
