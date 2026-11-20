import re
from typing import Any

from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Markdown
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import QuestionStatus

CUT = 600  # chars kept of any one free-text field in a recap


class RecapTools(Tools):
    async def topic_recap(self, topic_id: Id) -> dict[str, Any]:
        """Everything a retrospective needs, read-only: topic, latest charter, agenda, sessions
        (oldest first), claims with sources, questions by status and child topics. Long text is
        cut and `truncated` is true; lists are not capped (shortcut: very large topics)."""
        self.ctx.store.topics.require(topic_id)
        cuts: list[str] = []

        def cut(text: str | None) -> str | None:
            if text is not None and len(text) > CUT:
                cuts.append(text)
                return text[:CUT] + "..."
            return text

        topic = self.ctx.store.topics.get(topic_id)
        charter = self.ctx.store.charters.get_latest(topic_id)
        node = next((n for n in self.ctx.store.topics.list_all() if n.id == topic_id), None)
        result = {
            "topic": topic.model_dump(mode="json") if topic else None,
            "charter": charter.model_dump(mode="json") if charter else None,
            "agenda": [
                {"facet": i.facet, "status": i.status}
                for i in self.ctx.store.agenda.list_items(topic_id)
            ],
            "sessions": [
                {
                    "started_at": s.started_at.isoformat(),
                    "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                    "summary": cut(s.summary),
                    "bookmark_note": cut(s.bookmark.note if s.bookmark else None),
                }
                for s in self.ctx.store.sessions.list_for_topic(topic_id)
            ],
            "claims": [{**c, "text": cut(c["text"])} for c in self._claims_with_sources(topic_id)],
            "questions": {
                status.value: [
                    {"text": cut(q.clean_text), "answer_summary": cut(q.answer_summary)}
                    for q in self.ctx.store.questions.list_by_status(topic_id, status)
                ]
                for status in QuestionStatus
            },
            "children": [
                {"title": c.title, "status": c.status} for c in (node.children if node else [])
            ],
        }
        return {**result, "truncated": bool(cuts)}

    async def recap_save(self, session_id: Id, topic_id: Id, markdown: Markdown) -> dict[str, Any]:
        """Save the retrospective as recaps/<topic-slug>-<topic-id-tail>-<YYYY-MM-DD>.md (the
        same topic on the same day overwrites). The engine picks the file name. Returns the path
        under DEEPDIVE_HOME and the byte count."""
        self.ctx.store.sessions.require(session_id)
        topic = self.ctx.store.topics.require(topic_id)
        slug = re.sub(r"[^a-z0-9]+", "-", topic.title.lower()).strip("-")[:40].strip("-")
        slug = slug or "recap"  # e.g. a title with no ascii letters
        folder = self.ctx.paths.recaps.resolve()
        tail = str(topic_id)[-8:]  # a UUIDv7 head is a timestamp; the tail is random
        name = f"{slug}-{tail}-{self.ctx.now().date().isoformat()}.md"
        path = (folder / name).resolve()
        if path.parent != folder:
            raise InvalidInputError("recap path escapes the recaps folder")
        folder.mkdir(parents=True, exist_ok=True)
        data = markdown.encode("utf-8")
        path.write_bytes(data)
        return {"path": str(path.relative_to(self.ctx.paths.root.resolve())), "bytes": len(data)}
