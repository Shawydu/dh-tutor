"""The matching step: a new question in, related past questions and guidance out (design.md
"Question registry and relation classification")."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from deepdive import clock
from deepdive.classify import Answer, Choice, Classifier, ClassifyResult, YesNo
from deepdive.config import Config
from deepdive.matcher.candidates import CandidateFinder
from deepdive.matcher.embed import Embedder, NullEmbedder
from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation, QuestionStatus
from deepdive.store.models import Charter, Question
from deepdive.store.repos import Store

Rel = QuestionEdgeRelation
SCOPES = ["in", "adjacent", "outside"]
STUDENTS = {QuestionAsker.CURIOUS, QuestionAsker.SKEPTIC}

# The design's relation table: the action for each relation. `unrelated` is treated as new.
ACTIONS = {
    Rel.SAME: "Recall the earlier answer; offer a recap or a deeper version.",
    Rel.NARROWER: "Add it as a sub-question and answer from there.",
    Rel.BROADER: "Run the scope check before answering.",
    Rel.ASPECT: "Link it as related; point back to the shared groundwork.",
    Rel.BUILDS_ON: "Load the earlier answer as context.",
    Rel.CLASHES: "Reopen the earlier claim and reconcile the two answers.",
}
REPEAT_ACTION = "The user repeated a question: re-explain it differently (analogy, code, diagram)."
ADJACENT_ACTION = "Adjacent to the charter: offer to park it or jump into a child topic."
ADJACENT_IN_CHILD = "Adjacent to the charter: park it or add it to the parent's frontier."
UNSURE_GATE = (
    "Could not tell if this is a question. If it is a real question, call question_record."
)
UNSURE_SCOPE = "Scope unclear: also judge whether it is in, adjacent to or outside the charter."
REL_PROMPT = (
    "Relation of the NEW question to earlier question {id}. same: asks the same thing; "
    "narrower: NEW is more specific than the earlier one; broader: NEW is more general; "
    "aspect: NEW is another angle on the same subject; builds_on: NEW follows from the earlier "
    "answer; clashes: NEW contradicts the earlier answer; unrelated: none of these."
)
OUTSIDE_ACTION = "Outside the charter: it was parked automatically; say so."

CONTEXT_MAX = 1500
_LINE_TEXT = 60


class Related(BaseModel):
    id: UUID
    text: str
    answer_summary: str | None
    relation: QuestionEdgeRelation | None = None  # None: not classified (needs_judgement)
    confidence: float | None = None


class MatchResult(BaseModel):
    kind: Literal["matched", "duplicate", "not_a_question", "unsure"]
    question_id: UUID | None = None  # None unless the question was stored
    scope: str | None = None  # "in", "adjacent" or "outside"; None without a charter
    parked: bool = False
    needs_judgement: bool = (
        False  # live session, low confidence: the guide classifies, question_link
    )
    guidance: list[str] = []
    related: list[Related] = []

    def render_context(self) -> str:
        """A compact text block for the hook to inject; always under CONTEXT_MAX characters."""
        lines = [f"Question matcher: {self.kind}"]
        if self.question_id:
            lines.append(f"Stored as question_id {self.question_id}: tag it with concept_tag.")
        if self.needs_judgement and self.related:  # nothing to link otherwise
            lines.append("Low confidence: judge how these relate, then call question_link.")
        lines += [f"- {g}" for g in self.guidance]
        for r in self.related:
            line = f"* [{r.relation or '?'}] {r.text[:_LINE_TEXT]}"
            if r.answer_summary:
                line += f" -> {r.answer_summary[:_LINE_TEXT]}"
            lines.append(line)
        return "\n".join(lines)[: CONTEXT_MAX - 1]


def clean_text(text: str) -> str:
    return " ".join(text.split())


class Matcher:
    def __init__(
        self,
        store: Store,
        classifier: Classifier,
        config: Config,
        embedder: Embedder | None = None,
    ) -> None:
        self.store = store
        self.classifier = classifier
        self.threshold = config.classifier.auto_threshold
        self.finder = CandidateFinder(store, embedder or NullEmbedder(), config.matcher.candidates)

    def _sure(self, answer: Answer | None) -> str | None:
        """The answer's top option if it reaches the threshold, else None."""
        if answer is None:
            return None
        option, p = answer.top
        return option if p >= self.threshold else None

    def match(
        self,
        text: str,
        topic_id: UUID,
        asker: QuestionAsker,
        session_id: UUID | None = None,
    ) -> MatchResult:
        topic = self.store.topics.require(topic_id)
        clean = clean_text(text)
        gate = self.classifier.classify(
            clean, {"is_question": YesNo(prompt="Is this a question that asks for an answer?")}
        )
        is_question = None if gate.needs_judgement else self._sure(gate.answers.get("is_question"))
        if is_question is None:  # unsure: store nothing, no second classifier call
            return MatchResult(kind="unsure", needs_judgement=True, guidance=[UNSURE_GATE])
        if is_question == "no":
            return MatchResult(kind="not_a_question")

        candidates = self.finder.find(clean)
        charter = self.store.charters.get_latest(topic_id)
        questions: dict[str, Choice | YesNo] = {
            f"rel_{c.id}": Choice(prompt=REL_PROMPT.format(id=c.id), options=[r.value for r in Rel])
            for c in candidates
        }
        if charter:
            questions["scope"] = Choice(
                prompt="Is the new question in, adjacent to, or outside the charter's scope?",
                options=SCOPES,
            )
        result = (
            self.classifier.classify(self._state(clean, charter, candidates), questions)
            if questions
            else ClassifyResult(answers={}, provider="none")
        )

        # Each answer is acted on only if it reaches the threshold on its own.
        edges: list[tuple[Question, Rel, float]] = []
        unsure: list[Question] = []
        for c in candidates:
            answer = result.answers.get(f"rel_{c.id}")
            relation = self._sure(answer)
            if relation is None:
                unsure.append(c)
            elif relation != Rel.UNRELATED:
                assert answer is not None
                edges.append((c, Rel(relation), answer.top[1]))
        same = any(rel == Rel.SAME for _, rel, _ in edges)
        if asker in STUDENTS and any(
            rel == Rel.SAME and c.topic_id == topic_id for c, rel, _ in edges
        ):
            return MatchResult(kind="duplicate", related=self._related(edges, []))

        scope = self._sure(result.answers.get("scope")) if charter else None
        repeat = same and asker == QuestionAsker.USER
        guidance = [ACTIONS[rel] for rel in dict.fromkeys(r for _, r, _ in edges)]
        if repeat:
            guidance.append(REPEAT_ACTION)
        if scope == "adjacent":
            guidance.append(ADJACENT_IN_CHILD if topic.parent_topic_id else ADJACENT_ACTION)
        elif scope == "outside":
            guidance.append(OUTSIDE_ACTION)
        elif charter and scope is None:
            guidance.append(UNSURE_SCOPE)
        with self.store.db.transaction():
            q = self.store.questions.add(
                topic_id,
                asker,
                text,
                clean,
                session_id=session_id,
                status=QuestionStatus.PARKED if scope == "outside" else QuestionStatus.OPEN,
            )
            for c, rel, confidence in edges:
                self.store.edges.add(
                    q.id,
                    c.id,
                    rel,
                    confidence=confidence,
                    classifier=result.provider,
                    repeat=repeat and rel == Rel.SAME,
                    at=clock.now(),
                )
        return MatchResult(
            kind="matched",
            question_id=q.id,
            scope=scope,
            parked=scope == "outside",
            needs_judgement=bool(unsure) or (bool(charter) and scope is None),
            guidance=guidance,
            related=self._related(edges, unsure),
        )

    @staticmethod
    def _state(clean: str, charter: Charter | None, candidates: list[Question]) -> str:
        parts = [f"New question: {clean}"]
        if charter:
            parts.append(f"Charter: {charter.model_dump_json(exclude={'session_id'})}")
        parts += [
            f"Earlier question {c.id}: {c.clean_text} | answer: {c.answer_summary}"
            for c in candidates
        ]
        return "\n".join(parts)

    @staticmethod
    def _related(edges: list[tuple[Question, Rel, float]], unsure: list[Question]) -> list[Related]:
        """Classified candidates, then the unclassified ones (relation None)."""
        return [
            Related(
                id=c.id,
                text=c.clean_text,
                answer_summary=c.answer_summary,
                relation=rel,
                confidence=conf,
            )
            for c, rel, conf in edges
        ] + [Related(id=c.id, text=c.clean_text, answer_summary=c.answer_summary) for c in unsure]
