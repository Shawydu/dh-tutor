import re
from typing import Any

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Markdown
from deepdive.ledger.tools.topics import claims_with_sources
from deepdive.store.enums import QuestionStatus

CUT = 600  # chars kept of any one free-text field in a recap


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def topic_recap(topic_id: Id) -> dict[str, Any]:
        """Everything a retrospective needs, read-only: topic, latest charter, agenda, sessions
        (oldest first), claims with sources, questions by status and child topics. Long text is
        cut and `truncated` is true; lists are not capped (shortcut: very large topics)."""
        ctx.require_topic(topic_id)
        cuts: list[str] = []

        def cut(text: str | None) -> str | None:
            if text is not None and len(text) > CUT:
                cuts.append(text)
                return text[:CUT] + "..."
            return text

        topic = ctx.store.topics.get(topic_id)
        charter = ctx.store.charters.get_latest(topic_id)
        node = next((n for n in ctx.store.topics.list_all() if n.id == topic_id), None)
        result = {
            "topic": topic.model_dump(mode="json") if topic else None,
            "charter": charter.model_dump(mode="json") if charter else None,
            "agenda": [
                {"facet": i.facet, "status": i.status}
                for i in ctx.store.agenda.list_items(topic_id)
            ],
            "sessions": [
                {
                    "started_at": s.started_at.isoformat(),
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                    "summary": cut(s.summary),
                    "bookmark_note": cut(s.bookmark.note if s.bookmark else None),
                }
                for s in ctx.store.sessions.list_for_topic(topic_id)
            ],
            "claims": [{**c, "text": cut(c["text"])} for c in claims_with_sources(ctx, topic_id)],
            "questions": {
                status.value: [
                    {"text": cut(q.clean_text), "answer_summary": cut(q.answer_summary)}
                    for q in ctx.store.questions.list_by_status(topic_id, status)
                ]
                for status in QuestionStatus
            },
            "children": [
                {"title": c.title, "status": c.status} for c in (node.children if node else [])
            ],
        }
        return {**result, "truncated": bool(cuts)}

    @server.tool()
    async def recap_save(session_id: Id, topic_id: Id, markdown: Markdown) -> dict[str, Any]:
        """Save the retrospective as recaps/<topic-slug>-<topic-id-tail>-<YYYY-MM-DD>.md (the
        same topic on the same day overwrites). The engine picks the file name. Returns the path
        under DEEPDIVE_HOME and the byte count."""
        ctx.require_session(session_id)
        topic = ctx.require_topic(topic_id)
        slug = re.sub(r"[^a-z0-9]+", "-", topic.title.lower()).strip("-")[:40].strip("-")
        slug = slug or "recap"  # e.g. a title with no ascii letters
        folder = ctx.paths.recaps.resolve()
        tail = str(topic_id)[-8:]  # a UUIDv7 head is a timestamp; the tail is random
        name = f"{slug}-{tail}-{ctx.now().date().isoformat()}.md"
        path = (folder / name).resolve()
        if path.parent != folder:
            raise InvalidInputError("recap path escapes the recaps folder")
        folder.mkdir(parents=True, exist_ok=True)
        data = markdown.encode("utf-8")
        path.write_bytes(data)
        return {"path": str(path.relative_to(ctx.paths.root.resolve())), "bytes": len(data)}
