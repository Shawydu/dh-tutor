from typing import Any
from uuid import UUID

from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import PAGE_SIZE, TITLE_MAX, Id, Page, Title
from deepdive.ledger.tools._common import Tools
from deepdive.store.enums import (
    AgendaItemStatus,
    QuestionStatus,
    TopicStatus,
)
from deepdive.store.errors import (
    CharterNotFoundError,
    ChildDepthError,
    QuestionNotFoundError,
    TopicNotFoundError,
)
from deepdive.store.models import Question


def _brief(items: list[Question]) -> list[dict[str, str]]:
    return [{"id": str(q.id), "text": q.clean_text, "asker": q.asker} for q in items]


class TopicTools(Tools):
    async def topic_create(self, title: Title, parent_topic_id: Id | None = None) -> dict[str, Any]:
        """Create a topic. A child topic names a top-level parent; children are one level deep."""
        return self.ctx.store.topics.create(title, parent_topic_id=parent_topic_id).model_dump(
            mode="json"
        )

    async def topic_get(self, topic_id: Id) -> dict[str, Any]:
        """One topic: id, title, parent_topic_id, status, pinned."""
        return self.ctx.store.topics.require(topic_id).model_dump(mode="json")

    async def topic_list(self) -> dict[str, Any]:
        """Top-level topics (pinned first), each with its child topics."""
        return {"topics": [t.model_dump(mode="json") for t in self.ctx.store.topics.list_all()]}

    async def topic_overview(self, page: Page = 1, query: Title | None = None) -> dict[str, Any]:
        """For /topics: one page of top-level topics (pinned, then most recently active, a
        child's activity counting for its parent) with status, charter_version, agenda
        done/total, open and parked question counts, last_session_at and children. `query`
        keeps topics whose title, or a child's title, contains it (any case). Each topic has a
        position `n` ("3", child "3.1") in this list only; `pages` is the page count and a page
        past it returns the last page."""
        # shortcut: pages in Python over every topic, fine for hundreds; move LIMIT into SQL then
        rows = self.ctx.store.topics.overview()
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

    async def resume_brief(self, topic_id: Id, item: Id | None = None) -> dict[str, Any]:
        """To resume a topic, in the order to present it: where_we_left_off, recap_checks (up to
        two concepts of the topic due for a recap: ask each, see the guide's Resuming), new_findings
        (the topic's best 3 unread discoveries), weakened_claims (every weakened claim with the
        discovery that weakened it, until cleared), next_agenda_item. Pass
        `item`, a discovery id from the digest, to open it (as discovery_open) and list it
        first. Call before session_start."""
        self.ctx.store.topics.require(topic_id)
        found = self.ctx.store.discoveries
        unread = found.list_unread(topic_id)
        if item:
            opened = found.get(item)
            if opened is None or opened.topic_id != topic_id:
                raise InvalidInputError("item is not a discovery of this topic")
            await self.discovery_open(item)
            unread = [opened, *(d for d in unread if d.id != item)]
        last = self.ctx.store.sessions.latest(topic_id, recorded=True)
        mark = last.bookmark if last else None
        items = self.ctx.store.agenda.list_items(topic_id)
        agenda = next((i for i in items if mark and i.id == mark.agenda_item_id), None)
        if agenda is None or agenda.status != AgendaItemStatus.OPEN:
            agenda = self.ctx.store.agenda.next_open(topic_id)
        return {
            "where_we_left_off": {
                "last_session_at": last.started_at.isoformat() if last else None,
                "summary": last.summary if last else None,
                "bookmark_note": mark.note if mark else None,
            },
            "recap_checks": self._due_recaps(topic_id),
            "new_findings": [found.finding(d).model_dump(mode="json") for d in unread[:3]],
            "weakened_claims": [
                {"claim_id": str(d.target_id), "discovery_id": str(f.id)}
                | f.model_dump(mode="json", include={"target_text", "summary", "source_url"})
                for d in found.weakening(topic_id)
                for f in [found.finding(d)]
            ],
            "next_agenda_item": agenda.model_dump(mode="json") if agenda else None,
        }

    def _due_recaps(self, topic_id: UUID) -> list[dict[str, Any]]:
        """Up to two of the topic's concepts that are due, most overdue first."""
        names = {c.id: c.name for c in self.ctx.store.concepts.list_all(topic_id)}
        due = [s for s in self.ctx.knowledge.list_due(self.ctx.now()) if s.concept_id in names]
        return [
            {"concept": names[s.concept_id], "level": round(s.level, 1)}
            | {"confidence": round(s.confidence, 2)}
            for s in due[:2]
        ]

    async def discovery_open(self, discovery_id: Id) -> dict[str, Any]:
        """The user digs into a finding now: mark it read. A weakened claim stays weakened until
        the guide clears it (claim_set_status)."""
        store = self.ctx.store
        found = store.discoveries.get(discovery_id)
        if found is None:
            raise InvalidInputError("no such discovery")
        with store.db.transaction():
            store.discoveries.mark_read(discovery_id, self.ctx.now())
        return {"finding": store.discoveries.finding(found).model_dump(mode="json")}

    async def topic_pin(self, topic_id: Id, pinned: bool) -> dict[str, Any]:
        """Pin a topic to the top of the list, or unpin it."""
        pin = self.ctx.store.topics.pin if pinned else self.ctx.store.topics.unpin
        return pin(topic_id).model_dump(mode="json")

    async def child_topic_create(
        self, session_id: Id, parent_id: Id, question_id: Id
    ) -> dict[str, Any]:
        """Dig into a parent's question as a child topic (one level deep).

        session_id is the parent's open session: it is bookmarked at its agenda item. The child
        starts with the question as its one core question and the parent's done_when.
        """
        parent_session = self.ctx.store.sessions.require(session_id)
        parent = self.ctx.store.topics.require(parent_id)
        question = self.ctx.store.questions.get(question_id)
        if parent.parent_topic_id is not None:
            raise ChildDepthError(f"topic {parent_id} is itself a child; children are one deep")
        if question is None:
            raise QuestionNotFoundError(question_id)
        if parent_session.topic_id != parent_id or question.topic_id != parent_id:
            raise InvalidInputError("session_id and question_id must belong to the parent topic")
        if question.status != QuestionStatus.OPEN:
            raise InvalidInputError("only an open question can be dug into")
        node = next(n for n in self.ctx.store.topics.list_all() if n.id == parent_id)
        if any(c.status != TopicStatus.FINISHED for c in node.children):
            raise InvalidInputError("the parent already has an unfinished child topic")
        parent_charter = self.ctx.store.charters.get_latest(parent_id)
        if parent_charter is None:
            raise CharterNotFoundError(
                f"topic {parent_id} has no charter to inherit done_when from"
            )
        # shortcut: not one transaction (charters.write opens its own), so a crash midway can
        # leave a child without a session; upgrade if that ever shows up
        child = self.ctx.store.topics.create(
            question.clean_text[:TITLE_MAX],
            parent_topic_id=parent_id,
            status=TopicStatus.ACTIVE,
        )
        charter = self.ctx.store.charters.write(
            child.id,
            core_questions=[question.clean_text],
            in_scope=[],
            parked=[],
            done_when=parent_charter.done_when,
            search_terms=parent_charter.search_terms,
        )
        nxt = self.ctx.store.agenda.next_open(parent_id)
        old = parent_session.bookmark
        item_id = old.agenda_item_id if old and old.agenda_item_id else (nxt.id if nxt else None)
        self.ctx.store.sessions.bookmark(
            session_id,
            agenda_item_id=item_id,
            question_id=question_id,
            note=old.note if old else None,
        )
        # PARTIAL = being explored elsewhere; it leaves map_get's open list
        self.ctx.store.questions.set_answer_summary(
            question_id,
            f"explored in child topic: {child.title}"[:500],
            status=QuestionStatus.PARTIAL,
        )
        child_session = self.ctx.store.sessions.start(child.id, at=self.ctx.now())
        return {
            "child": child.model_dump(mode="json"),
            "session": child_session.model_dump(mode="json"),
            "charter": charter.model_dump(mode="json"),
        }

    async def child_topic_finish(self, child_id: Id, session_id: Id) -> dict[str, Any]:
        """Finish a child topic and return where the parent's session (the one that
        child_topic_create bookmarked) left off."""
        child = self.ctx.store.topics.get(child_id)
        if child is None:
            raise TopicNotFoundError(child_id)
        if child.parent_topic_id is None or child.status == TopicStatus.FINISHED:
            raise InvalidInputError("not an unfinished child topic")
        parent_session = self.ctx.store.sessions.require(session_id)
        if parent_session.topic_id != child.parent_topic_id:
            raise InvalidInputError("session_id must be a session of the child's parent topic")
        child_session = self.ctx.store.sessions.latest(child_id)
        if child_session is not None and child_session.ended_at is None:
            self.ctx.store.sessions.end(
                child_session.id, "Child topic finished.", at=self.ctx.now()
            )
        self.ctx.store.topics.set_status(child_id, TopicStatus.FINISHED)
        mark = parent_session.bookmark
        facet = None
        if mark and mark.agenda_item_id:
            items = self.ctx.store.agenda.list_items(child.parent_topic_id)
            facet = next((i.facet for i in items if i.id == mark.agenda_item_id), None)
        return {
            "parent_topic_id": str(child.parent_topic_id),
            "session_id": str(parent_session.id),
            "bookmark": mark.model_dump(mode="json") if mark else None,
            "agenda_facet": facet,
        }

    async def frontier_add(self, session_id: Id, topic_id: Id, question_id: Id) -> dict[str, Any]:
        """Add an adjacent question to a topic's frontier (from a child: its parent's)."""
        self.ctx.store.sessions.require(session_id)
        question = self.ctx.store.questions.get(question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)
        owner = self.ctx.store.topics.require(question.topic_id)
        if topic_id not in (owner.id, owner.parent_topic_id):
            raise InvalidInputError("the question must belong to topic_id or one of its children")
        self.ctx.store.frontier.add(topic_id, question_id)
        return {"frontier": _brief(self.ctx.store.frontier.list_for_topic(topic_id))}

    async def map_get(self, topic_id: Id) -> dict[str, Any]:
        """Compact map: latest charter (or null), agenda with status, claims with cited sources,
        open questions and the frontier."""
        self.ctx.store.topics.require(topic_id)
        charter = self.ctx.store.charters.get_latest(topic_id)
        return {
            "charter": charter.model_dump(mode="json") if charter else None,
            "agenda": [
                {"id": str(i.id), "facet": i.facet, "status": i.status}
                for i in self.ctx.store.agenda.list_items(topic_id)
            ],
            "claims": self._claims_with_sources(topic_id),
            "open_questions": _brief(
                self.ctx.store.questions.list_by_status(topic_id, QuestionStatus.OPEN)
            ),
            "frontier": _brief(self.ctx.store.frontier.list_for_topic(topic_id)),
        }
