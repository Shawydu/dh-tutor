from typing import Any

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Concepts, Id, Summary, Text
from deepdive.ledger.tools._common import Tools
from deepdive.matcher.matcher import Matcher, clean_text
from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation, QuestionStatus
from deepdive.store.errors import QuestionNotFoundError


class QuestionTools(Tools):
    def __init__(self, ctx: LedgerContext, matcher: Matcher) -> None:
        super().__init__(ctx)
        self.matcher = matcher

    async def question_get(self, question_id: Id) -> dict[str, Any]:
        """One question: asker, text, status and answer summary."""
        question = self.ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        return question.model_dump(mode="json")

    async def question_record(
        self,
        session_id: Id,
        topic_id: Id,
        text: Text,
        asker: QuestionAsker,
        concepts: Concepts | None = None,
    ) -> dict[str, Any]:
        """Store a question as asked (open), tagged with 1-4 concept names. No matching: the clean
        text is the trimmed text."""
        if self.ctx.store.sessions.require(session_id).topic_id != topic_id:
            raise InvalidInputError("topic_id must be the session's topic")
        clean = clean_text(text)
        question = self.ctx.store.questions.add(topic_id, asker, text, clean, session_id=session_id)
        self._tag(question.id, concepts)
        return question.model_dump(mode="json")

    async def question_submit(
        self,
        session_id: Id,
        topic_id: Id,
        text: Text,
        asker: QuestionAsker,
        concepts: Concepts | None = None,
    ) -> dict[str, Any]:
        """Match a new question against past ones and store it, tagged with 1-4 concept names;
        returns guidance for the guide.

        kind is matched, duplicate (a student repeat: drop it, nothing stored) or not_a_question
        (nothing stored). With needs_judgement, classify the related candidates yourself and
        record each with question_link.
        """
        if self.ctx.store.sessions.require(session_id).topic_id != topic_id:
            raise InvalidInputError("topic_id must be the session's topic")
        if not text.strip():
            raise InvalidInputError("text must not be blank")
        result = self.matcher.match(text, topic_id, asker, session_id)
        if result.question_id:
            self._tag(result.question_id, concepts)
        return {**result.model_dump(mode="json"), "context": result.render_context()}

    async def question_link(
        self, session_id: Id, from_id: Id, to_id: Id, relation: QuestionEdgeRelation
    ) -> dict[str, Any]:
        """Record your own judgement of how question from_id relates to the earlier to_id."""
        topic_id = self.ctx.store.sessions.require(session_id).topic_id
        if from_id == to_id:
            raise InvalidInputError("a question cannot relate to itself")
        found = [self.ctx.store.questions.get(i) for i in (from_id, to_id)]
        for question_id, question in zip((from_id, to_id), found, strict=True):
            if question is None:
                raise QuestionNotFoundError(question_id)
        origin, target = found
        assert origin is not None and target is not None
        if {origin.topic_id, target.topic_id} != {topic_id}:
            raise InvalidInputError("both questions must belong to the session's topic")
        repeat = relation == QuestionEdgeRelation.SAME and origin.asker == QuestionAsker.USER
        store = self.ctx.store
        with store.db.transaction():
            was_repeat = any(
                e.repeat for e in store.edges.list_for_question(from_id) if e.to_id == to_id
            )
            edge = store.edges.add(
                from_id, to_id, relation, classifier="guide", repeat=repeat, at=self.ctx.now()
            )
            if repeat and not was_repeat:
                self.matcher.record_repeat(from_id, to_id, session_id)
        return edge.model_dump(mode="json")

    async def question_park(self, session_id: Id, question_id: Id) -> dict[str, Any]:
        """Park a question: it leaves the walkthrough and can be found again with parked_list."""
        session = self.ctx.store.sessions.require(session_id)
        question = self.ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        if question.status != QuestionStatus.OPEN or question.topic_id != session.topic_id:
            raise InvalidInputError("only an open question of the session's topic can be parked")
        return self.ctx.store.questions.park(question_id).model_dump(mode="json")

    async def question_answer(
        self,
        session_id: Id,
        question_id: Id,
        summary: Summary,
        status: QuestionStatus = QuestionStatus.ANSWERED,
    ) -> dict[str, Any]:
        """Store the answer summary for a question and set its status (default: answered)."""
        self.ctx.store.sessions.require(session_id)
        return self.ctx.store.questions.set_answer_summary(
            question_id, summary, status=status
        ).model_dump(mode="json")

    async def parked_list(self, topic_id: Id | None = None) -> dict[str, Any]:
        """Parked questions of one topic, or of every topic when topic_id is omitted."""
        if topic_id is not None:
            self.ctx.store.topics.require(topic_id)
        return {
            "questions": [
                q.model_dump(mode="json") for q in self.ctx.store.questions.list_parked(topic_id)
            ]
        }

    async def parked_search(self, text: Text) -> dict[str, Any]:
        """Parked questions, from all topics, that best match the words in text."""
        found = self.ctx.store.questions.fts_candidates(text, status=QuestionStatus.PARKED)
        return {"questions": [q.model_dump(mode="json") for q in found]}
