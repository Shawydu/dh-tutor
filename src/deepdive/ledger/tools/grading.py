from typing import Any

from deepdive.classify import Choice, Classifier, ClassifierUnavailable
from deepdive.config import Config
from deepdive.knowledge.store import EVIDENCE_WEIGHT
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Confidence, Facets, Id, Items, Summary
from deepdive.ledger.tools._common import Tools
from deepdive.matcher.matcher import STUDENTS
from deepdive.store.enums import KnowledgeEvidenceGrade, KnowledgeEvidenceKind
from deepdive.store.models import Concept, Question, Rubric


class GradingTools(Tools):
    """A student question's rubric, and the user's answer to it graded into knowledge evidence."""

    def __init__(self, ctx: LedgerContext, config: Config, classifier: Classifier) -> None:
        super().__init__(ctx)
        self.threshold = config.classifier.auto_threshold
        self.classifier = classifier

    async def rubric_write(
        self, question_id: Id, key_points: Facets, misconceptions: Items
    ) -> dict[str, Any]:
        """Write the rubric of an accepted student question (asker curious or skeptic): the key
        points a good answer covers and the misconceptions to watch for. Do it before putting the
        question to the user. A later call replaces it."""
        question = self.ctx.store.questions.require(question_id)
        if question.asker not in STUDENTS:
            raise InvalidInputError("only a student question (curious or skeptic) has a rubric")
        rubric = self.ctx.store.rubrics.write(question_id, key_points, misconceptions)
        return rubric.model_dump(mode="json")

    async def answer_grade(
        self, question_id: Id, answer_text: Summary, session_id: Id
    ) -> dict[str, Any]:
        """Grade the user's answer to a student question against its rubric and store the grade as
        evidence on each of the question's concepts. Needs a rubric and concept_tag first.

        Below the confidence threshold (or with the classifier down) nothing is stored: you get
        {"needs_judgement": true, rubric, guess}; grade it yourself with answer_grade_set.
        """
        question, rubric, concepts = self._check(question_id, session_id)
        state = (
            f"Question: {question.clean_text}\nKey points: {rubric.key_points}\n"
            f"Misconceptions: {rubric.misconceptions}\nUser's answer: {answer_text}"
        )
        grade = Choice(
            prompt="How well does the answer cover the key points?",
            options=[g.value for g in KnowledgeEvidenceGrade],
        )
        guess = None
        try:
            result = self.classifier.classify(state, {"grade": grade})
            guess = result.answers.get("grade")
        except ClassifierUnavailable:
            result = None
        if (
            result is None
            or result.needs_judgement
            or guess is None
            or guess.top[1] < self.threshold
        ):
            return {
                "needs_judgement": True,
                "rubric": rubric.model_dump(mode="json"),
                "guess": {"grade": guess.top[0], "confidence": guess.top[1]} if guess else None,
            }
        option, confidence = guess.top
        return self._store(
            question, concepts, session_id, KnowledgeEvidenceGrade(option), confidence,
            result.provider,
        )  # fmt: skip

    async def answer_grade_set(
        self, question_id: Id, grade: KnowledgeEvidenceGrade, confidence: Confidence, session_id: Id
    ) -> dict[str, Any]:
        """Store your own grade for the user's answer (after answer_grade said needs_judgement)."""
        question, _, concepts = self._check(question_id, session_id)
        return self._store(question, concepts, session_id, grade, confidence, "claude")

    def _check(self, question_id: Id, session_id: Id) -> tuple[Question, Rubric, list[Concept]]:
        store = self.ctx.store
        question = store.questions.require(question_id)
        if store.sessions.require(session_id).topic_id != question.topic_id:
            raise InvalidInputError("session_id must be a session of the question's topic")
        rubric = store.rubrics.get(question_id)
        if rubric is None:
            raise InvalidInputError("the question has no rubric: call rubric_write first")
        concepts = store.concepts.for_question(question_id)
        if not concepts:
            raise InvalidInputError("the question has no concepts: call concept_tag first")
        self._refuse_regrade(question_id, concepts)
        return question, rubric, concepts

    def _refuse_regrade(self, question_id: Id, concepts: list[Concept]) -> None:
        # all concepts, not the first: tags added after a grade would hide it
        if any(
            e.question_id == question_id and e.kind == KnowledgeEvidenceKind.ANSWERED_STUDENT_Q
            for c in concepts
            for e in self.ctx.knowledge.list_evidence(c.id)
        ):
            raise InvalidInputError("the answer to this question is already graded")

    def _store(
        self,
        question: Question,
        concepts: list[Concept],
        session_id: Id,
        grade: KnowledgeEvidenceGrade,
        confidence: float,
        grader: str,
    ) -> dict[str, Any]:
        at = self.ctx.now()
        with self.ctx.store.db.transaction():
            self._refuse_regrade(question.id, concepts)
            for concept in concepts:
                self.ctx.knowledge.add_evidence(
                    concept.id, KnowledgeEvidenceKind.ANSWERED_STUDENT_Q, EVIDENCE_WEIGHT, at,
                    grade=grade, grader=grader, grader_confidence=confidence,
                    session_id=session_id, question_id=question.id,
                )  # fmt: skip
        return {
            "grade": grade,
            "confidence": confidence,
            "grader": grader,
            "evidence": len(concepts),
        }
