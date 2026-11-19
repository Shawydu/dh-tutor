from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Summary, Text
from deepdive.store.enums import QuestionAsker, QuestionStatus
from deepdive.store.errors import QuestionNotFoundError


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def question_get(question_id: Id) -> dict[str, Any]:
        """One question: asker, text, status and answer summary."""
        question = ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        return question.model_dump(mode="json")

    @server.tool()
    async def question_record(
        session_id: Id, topic_id: Id, text: Text, asker: QuestionAsker
    ) -> dict[str, Any]:
        """Store a question as asked (open). No matching: the clean text is the trimmed text."""
        if ctx.require_session(session_id).topic_id != topic_id:
            raise InvalidInputError("topic_id must be the session's topic")
        clean = " ".join(text.split())
        return ctx.store.questions.add(
            topic_id, asker, text, clean, session_id=session_id
        ).model_dump(mode="json")

    @server.tool()
    async def question_park(session_id: Id, question_id: Id) -> dict[str, Any]:
        """Park a question: it leaves the walkthrough and can be found again with parked_list."""
        session = ctx.require_session(session_id)
        question = ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        if question.status != QuestionStatus.OPEN or question.topic_id != session.topic_id:
            raise InvalidInputError("only an open question of the session's topic can be parked")
        return ctx.store.questions.park(question_id).model_dump(mode="json")

    @server.tool()
    async def question_answer(
        session_id: Id,
        question_id: Id,
        summary: Summary,
        status: QuestionStatus = QuestionStatus.ANSWERED,
    ) -> dict[str, Any]:
        """Store the answer summary for a question and set its status (default: answered)."""
        ctx.require_session(session_id)
        return ctx.store.questions.set_answer_summary(
            question_id, summary, status=status
        ).model_dump(mode="json")

    @server.tool()
    async def parked_list(topic_id: Id | None = None) -> dict[str, Any]:
        """Parked questions of one topic, or of every topic when topic_id is omitted."""
        if topic_id is not None:
            ctx.require_topic(topic_id)
        return {
            "questions": [
                q.model_dump(mode="json") for q in ctx.store.questions.list_parked(topic_id)
            ]
        }

    @server.tool()
    async def parked_search(text: Text) -> dict[str, Any]:
        """Parked questions, from all topics, that best match the words in text."""
        found = ctx.store.questions.fts_candidates(text, status=QuestionStatus.PARKED)
        return {"questions": [q.model_dump(mode="json") for q in found]}
