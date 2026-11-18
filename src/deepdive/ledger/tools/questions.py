from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import Id, Summary
from deepdive.store.enums import QuestionStatus
from deepdive.store.errors import QuestionNotFoundError
from deepdive.store.repos import questions


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def question_get(question_id: Id) -> dict[str, Any]:
        """One question: asker, text, status and answer summary."""
        question = questions.get(ctx.conn, question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        return question.model_dump(mode="json")

    @server.tool()
    async def question_answer(
        session_id: Id,
        question_id: Id,
        summary: Summary,
        status: QuestionStatus = QuestionStatus.ANSWERED,
    ) -> dict[str, Any]:
        """Store the answer summary for a question and set its status (default: answered)."""
        ctx.require_session(session_id)
        return questions.set_answer_summary(
            ctx.conn, question_id, summary, status=status
        ).model_dump(mode="json")

    @server.tool()
    async def parked_list(topic_id: Id | None = None) -> dict[str, Any]:
        """Parked questions of one topic, or of every topic when topic_id is omitted."""
        if topic_id is not None:
            ctx.require_topic(topic_id)
        return {
            "questions": [
                q.model_dump(mode="json") for q in questions.list_parked(ctx.conn, topic_id)
            ]
        }
