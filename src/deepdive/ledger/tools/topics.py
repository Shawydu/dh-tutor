from typing import Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer

from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import PAGE_SIZE, TITLE_MAX, Id, Page, Title
from deepdive.store.enums import AgendaItemStatus, QuestionStatus, TopicStatus
from deepdive.store.errors import (
    CharterNotFoundError,
    ChildDepthError,
    QuestionNotFoundError,
    TopicNotFoundError,
)
from deepdive.store.models import Question


def _brief(items: list[Question]) -> list[dict[str, str]]:
    return [{"id": str(q.id), "text": q.clean_text, "asker": q.asker} for q in items]


def claims_with_sources(ctx: LedgerContext, topic_id: UUID) -> list[dict[str, Any]]:
    """The topic's claims, each with its cited sources as `{id, url}`."""
    cited: dict[str, dict[str, dict[str, str | None]]] = {}
    for e in ctx.store.evidence.list_for_topic(topic_id):
        s = ctx.store.sources.get(e.source_id)
        sid = str(e.source_id)
        cited.setdefault(str(e.claim_id), {})[sid] = {"id": sid, "url": s.url if s else None}
    return [
        {
            "id": str(c.id),
            "text": c.text,
            "status": c.status,
            "sources": list(cited.get(str(c.id), {}).values()),
        }
        for c in ctx.store.claims.list_for_topic(topic_id)
    ]


def register(server: MCPServer[None], ctx: LedgerContext) -> None:
    @server.tool()
    async def topic_create(title: Title, parent_topic_id: Id | None = None) -> dict[str, Any]:
        """Create a topic. A child topic names a top-level parent; children are one level deep."""
        return ctx.store.topics.create(title, parent_topic_id=parent_topic_id).model_dump(
            mode="json"
        )

    @server.tool()
    async def topic_get(topic_id: Id) -> dict[str, Any]:
        """One topic: id, title, parent_topic_id, status, pinned."""
        ctx.require_topic(topic_id)
        topic = ctx.store.topics.get(topic_id)
        assert topic is not None
        return topic.model_dump(mode="json")

    @server.tool()
    async def topic_list() -> dict[str, Any]:
        """Top-level topics (pinned first), each with its child topics."""
        return {"topics": [t.model_dump(mode="json") for t in ctx.store.topics.list_all()]}

    @server.tool()
    async def topic_overview(page: Page = 1, query: Title | None = None) -> dict[str, Any]:
        """For /topics: one page of top-level topics (pinned, then most recently active, a
        child's activity counting for its parent) with status, charter_version, agenda
        done/total, open and parked question counts, last_session_at and children. `query`
        keeps topics whose title, or a child's title, contains it (any case). Each topic has a
        position `n` ("3", child "3.1") in this list only; `pages` is the page count and a page
        past it returns the last page."""
        # shortcut: pages in Python over every topic, fine for hundreds; move LIMIT into SQL then
        rows = ctx.store.topics.overview()
        if query:
            q = query.casefold()
            rows = [t for t in rows if any(q in x.title.casefold() for x in [t, *t.children])]
        pages = max(1, -(-len(rows) // PAGE_SIZE))
        page = min(page, pages)
        start = (page - 1) * PAGE_SIZE
        shown = []
        for n, t in enumerate(rows[start : start + PAGE_SIZE], start + 1):
            kids = [
                {"n": f"{n}.{k}", **c.model_dump(mode="json")} for k, c in enumerate(t.children, 1)
            ]
            shown.append({"n": str(n), **t.model_dump(mode="json"), "children": kids})
        return {"topics": shown, "page": page, "pages": pages, "total": len(rows)}

    @server.tool()
    async def resume_brief(topic_id: Id) -> dict[str, Any]:
        """To resume a topic, in the order to present it: where_we_left_off, recap_checks (empty
        until v2), new_findings (empty until v1), next_agenda_item. Call before session_start."""
        ctx.require_topic(topic_id)
        last = ctx.store.sessions.latest(topic_id, recorded=True)
        mark = last.bookmark if last else None
        items = ctx.store.agenda.list_items(topic_id)
        item = next((i for i in items if mark and i.id == mark.agenda_item_id), None)
        if item is None or item.status != AgendaItemStatus.OPEN:
            item = ctx.store.agenda.next_open(topic_id)
        return {
            "where_we_left_off": {
                "last_session_at": last.started_at.isoformat() if last else None,
                "summary": last.summary if last else None,
                "bookmark_note": mark.note if mark else None,
            },
            "recap_checks": [],
            "new_findings": [],
            "next_agenda_item": item.model_dump(mode="json") if item else None,
        }

    @server.tool()
    async def topic_pin(topic_id: Id, pinned: bool) -> dict[str, Any]:
        """Pin a topic to the top of the list, or unpin it."""
        pin = ctx.store.topics.pin if pinned else ctx.store.topics.unpin
        return pin(topic_id).model_dump(mode="json")

    @server.tool()
    async def child_topic_create(session_id: Id, parent_id: Id, question_id: Id) -> dict[str, Any]:
        """Dig into a parent's question as a child topic (one level deep).

        session_id is the parent's open session: it is bookmarked at its agenda item. The child
        starts with the question as its one core question and the parent's done_when.
        """
        parent_session = ctx.require_session(session_id)
        parent = ctx.require_topic(parent_id)
        question = ctx.store.questions.get(question_id)
        if parent.parent_topic_id is not None:
            raise ChildDepthError(f"topic {parent_id} is itself a child; children are one deep")
        if question is None:
            raise QuestionNotFoundError(question_id)
        if parent_session.topic_id != parent_id or question.topic_id != parent_id:
            raise InvalidInputError("session_id and question_id must belong to the parent topic")
        if question.status != QuestionStatus.OPEN:
            raise InvalidInputError("only an open question can be dug into")
        node = next(n for n in ctx.store.topics.list_all() if n.id == parent_id)
        if any(c.status != TopicStatus.FINISHED for c in node.children):
            raise InvalidInputError("the parent already has an unfinished child topic")
        parent_charter = ctx.store.charters.get_latest(parent_id)
        if parent_charter is None:
            raise CharterNotFoundError(
                f"topic {parent_id} has no charter to inherit done_when from"
            )
        # shortcut: not one transaction (charters.write opens its own), so a crash midway can
        # leave a child without a session; upgrade if that ever shows up
        child = ctx.store.topics.create(
            question.clean_text[:TITLE_MAX],
            parent_topic_id=parent_id,
            status=TopicStatus.ACTIVE,
        )
        charter = ctx.store.charters.write(
            child.id,
            core_questions=[question.clean_text],
            in_scope=[],
            parked=[],
            done_when=parent_charter.done_when,
        )
        nxt = ctx.store.agenda.next_open(parent_id)
        old = parent_session.bookmark
        item_id = old.agenda_item_id if old and old.agenda_item_id else (nxt.id if nxt else None)
        ctx.store.sessions.bookmark(
            session_id,
            agenda_item_id=item_id,
            question_id=question_id,
            note=old.note if old else None,
        )
        # PARTIAL = being explored elsewhere; it leaves map_get's open list
        ctx.store.questions.set_answer_summary(
            question_id,
            f"explored in child topic: {child.title}"[:500],
            status=QuestionStatus.PARTIAL,
        )
        child_session = ctx.store.sessions.start(child.id, at=ctx.now())
        return {
            "child": child.model_dump(mode="json"),
            "session": child_session.model_dump(mode="json"),
            "charter": charter.model_dump(mode="json"),
        }

    @server.tool()
    async def child_topic_finish(child_id: Id, session_id: Id) -> dict[str, Any]:
        """Finish a child topic and return where the parent's session (the one that
        child_topic_create bookmarked) left off."""
        child = ctx.store.topics.get(child_id)
        if child is None:
            raise TopicNotFoundError(child_id)
        if child.parent_topic_id is None or child.status == TopicStatus.FINISHED:
            raise InvalidInputError("not an unfinished child topic")
        parent_session = ctx.require_session(session_id)
        if parent_session.topic_id != child.parent_topic_id:
            raise InvalidInputError("session_id must be a session of the child's parent topic")
        child_session = ctx.store.sessions.latest(child_id)
        if child_session is not None and child_session.ended_at is None:
            ctx.store.sessions.end(child_session.id, "Child topic finished.", at=ctx.now())
        ctx.store.topics.set_status(child_id, TopicStatus.FINISHED)
        mark = parent_session.bookmark
        facet = None
        if mark and mark.agenda_item_id:
            items = ctx.store.agenda.list_items(child.parent_topic_id)
            facet = next((i.facet for i in items if i.id == mark.agenda_item_id), None)
        return {
            "parent_topic_id": str(child.parent_topic_id),
            "session_id": str(parent_session.id),
            "bookmark": mark.model_dump(mode="json") if mark else None,
            "agenda_facet": facet,
        }

    @server.tool()
    async def frontier_add(session_id: Id, topic_id: Id, question_id: Id) -> dict[str, Any]:
        """Add an adjacent question to a topic's frontier (from a child: its parent's)."""
        ctx.require_session(session_id)
        question = ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        owner = ctx.require_topic(question.topic_id)
        if topic_id not in (owner.id, owner.parent_topic_id):
            raise InvalidInputError("the question must belong to topic_id or one of its children")
        ctx.store.frontier.add(topic_id, question_id)
        return {"frontier": _brief(ctx.store.frontier.list_for_topic(topic_id))}

    @server.tool()
    async def map_get(topic_id: Id) -> dict[str, Any]:
        """Compact map: latest charter (or null), agenda with status, claims with cited sources,
        open questions and the frontier."""
        ctx.require_topic(topic_id)
        charter = ctx.store.charters.get_latest(topic_id)
        return {
            "charter": charter.model_dump(mode="json") if charter else None,
            "agenda": [
                {"id": str(i.id), "facet": i.facet, "status": i.status}
                for i in ctx.store.agenda.list_items(topic_id)
            ],
            "claims": claims_with_sources(ctx, topic_id),
            "open_questions": _brief(
                ctx.store.questions.list_by_status(topic_id, QuestionStatus.OPEN)
            ),
            "frontier": _brief(ctx.store.frontier.list_for_topic(topic_id)),
        }
