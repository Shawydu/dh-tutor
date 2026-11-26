"""Ledger MCP contract tests: the server runs in-process on a real temp SQLite file; no network."""

import asyncio
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from deepdive import clock
from deepdive.classify import Answer, ClassifyResult, Question
from deepdive.knowledge.store import SqliteKnowledgeStore
from deepdive.ledger.server import LedgerServer, create_server
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.ids import new_id
from deepdive.store.repos import Store

TOOLS = {
    "topic_create", "topic_get", "topic_list", "topic_pin", "discovery_open", "map_get",
    "topic_overview", "resume_brief", "topic_recap", "recap_save", "digest_get",
    "charter_write", "charter_get",
    "session_start", "session_bookmark", "session_end", "session_attach",
    "session_student_mode_set",
    "agenda_set", "agenda_next", "agenda_done",
    "source_register", "claim_add", "claim_list", "claim_set_status", "evidence_add",
    "evidence_list",
    "concept_tag", "concept_list", "concept_merge", "knowledge_view", "self_rate",
    "question_get", "question_answer", "parked_list",
    "rubric_write", "answer_grade", "answer_grade_set",
    "question_record", "question_park", "parked_search", "question_submit", "question_link",
    "child_topic_create", "child_topic_finish", "frontier_add",
    "search", "fetch",
}  # fmt: skip

MISSING = "00000000-0000-7000-8000-000000000999"  # well-formed, never created


class Ledger:
    """Sync handle on the in-process server: `call` returns the tool's structured result."""

    def __init__(self, server: LedgerServer, paths: Paths) -> None:
        self.server = server
        self.paths = paths

    def call(self, name: str, **args: Any) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            async with Client(self.server) as client:
                result = await client.call_tool(name, args)
            assert result.is_error is False, result.content
            structured: dict[str, Any] | None = result.structured_content
            assert structured is not None
            return structured

        return asyncio.run(run())

    def count(self, table: str) -> int:
        conn = sqlite3.connect(self.paths.db)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    paths = Paths(tmp_path)
    return Ledger(create_server(paths), paths)


def _session(ledger: Ledger) -> tuple[str, str]:
    topic = ledger.call("topic_create", title="GIL")
    return topic["id"], ledger.call("session_start", topic_id=topic["id"])["id"]


def test_lists_every_tool(ledger: Ledger) -> None:
    async def names() -> set[str]:
        async with Client(ledger.server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(names()) == TOOLS


def test_round_trip(ledger: Ledger) -> None:
    topic = ledger.call("topic_create", title="GIL")
    tid = topic["id"]
    session = ledger.call("session_start", topic_id=tid)
    sid = session["id"]
    assert (session["topic_id"], session["ended_at"]) == (tid, None)

    charter = ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["why a GIL?"],
        in_scope=["CPython"], parked=[], done_when="can explain it",
    )  # fmt: skip
    assert (charter["version"], charter["session_id"]) == (1, sid)
    assert ledger.call("charter_get", topic_id=tid)["done_when"] == "can explain it"

    items = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["what", "why"])["items"]
    assert [i["facet"] for i in items] == ["what", "why"]
    assert ledger.call("agenda_next", topic_id=tid)["item"]["facet"] == "what"
    ledger.call("agenda_done", session_id=sid, item_id=items[0]["id"])
    assert ledger.call("agenda_next", topic_id=tid)["item"]["facet"] == "why"

    source = ledger.call(
        "source_register",
        session_id=sid,
        url="https://peps.python.org/pep-0703/",
        kind="docs",
        tier=1,
    )
    again = ledger.call(
        "source_register",
        session_id=sid,
        url="https://peps.python.org/pep-0703/",
        kind="docs",
        tier=1,
    )
    assert again["id"] == source["id"]
    added = ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="the GIL serialises bytecode",
        source_ids=[source["id"]], excerpt_summary="PEP 703 background",
    )  # fmt: skip
    assert added["claim"]["session_id"] == sid
    listed = ledger.call("claim_list", topic_id=tid)["claims"]
    assert [c["text"] for c in listed] == ["the GIL serialises bytecode"]
    (row,) = listed[0]["evidence"]
    assert (row["stance"], row["source"]["url"]) == ("supports", source["url"])

    extra = ledger.call(
        "evidence_add", session_id=sid, claim_id=listed[0]["id"], source_id=source["id"],
        stance="weakens",
    )  # fmt: skip
    assert extra["stance"] == "weakens"
    by_claim = ledger.call("evidence_list", claim_id=listed[0]["id"])["evidence"]
    assert len(by_claim) == 2
    assert len(ledger.call("evidence_list", topic_id=tid)["evidence"]) == 2

    ledger.call("session_bookmark", session_id=sid, agenda_item_id=items[1]["id"], note="here")
    ended = ledger.call("session_end", session_id=sid, summary="covered what")
    assert (ended["summary"], ended["bookmark"]["note"]) == ("covered what", "here")


def test_claim_with_unknown_source_writes_nothing(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    known = ledger.call(
        "source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1
    )
    result = ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="x", source_ids=[known["id"], MISSING]
    )
    assert result["error"] == "source_not_found"
    assert MISSING in result["detail"]
    assert (ledger.count("claim"), ledger.count("evidence")) == (0, 0)


@pytest.mark.parametrize(
    ("start", "status", "error"),
    [
        ("weakened", "established", None),
        ("weakened", "open", None),
        ("weakened", "weakened", "invalid_input"),
        ("open", "established", "invalid_input"),
    ],
    ids=["to-established", "to-open", "refuses-weakened", "refuses-not-weakened"],
)
def test_claim_set_status_clears_only_weakened_claims(
    ledger: Ledger, start: str, status: str, error: str | None
) -> None:
    """claim_set_status moves a weakened claim to open or established and refuses anything else."""
    tid, sid = _session(ledger)
    src = ledger.call("source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1)
    claim = ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="x", source_ids=[src["id"]], status=start
    )
    cid = claim["claim"]["id"]
    got = ledger.call("claim_set_status", claim_id=cid, status=status)
    assert got.get("error") == error
    if error is None:
        assert got["status"] == status


def test_evidence_with_unknown_source_writes_nothing(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    known = ledger.call(
        "source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1
    )
    claim = ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="x", source_ids=[known["id"]]
    )["claim"]
    result = ledger.call(
        "evidence_add", session_id=sid, claim_id=claim["id"], source_id=MISSING, stance="supports"
    )
    assert result["error"] == "source_not_found"
    assert ledger.count("evidence") == 1


def test_store_errors_are_ordinary_results(ledger: Ledger) -> None:
    parent = ledger.call("topic_create", title="parent")
    child = ledger.call("topic_create", title="child", parent_topic_id=parent["id"])
    assert child["parent_topic_id"] == parent["id"]
    grandchild = ledger.call("topic_create", title="grandchild", parent_topic_id=child["id"])
    assert grandchild["error"] == "child_depth_exceeded"
    assert ledger.count("topic") == 2
    assert ledger.call("topic_get", topic_id=MISSING)["error"] == "topic_not_found"
    assert ledger.call("charter_get", topic_id=parent["id"])["error"] == "charter_not_found"
    assert ledger.call("question_get", question_id=MISSING)["error"] == "question_not_found"


def test_bad_input_is_invalid_input_not_a_protocol_error(ledger: Ledger) -> None:
    long_title = ledger.call("topic_create", title="x" * 5000)
    assert long_title["error"] == "invalid_input"
    assert "title" in long_title["detail"]
    assert "xxxxx" not in long_title["detail"]  # never echo the rejected value
    tid, sid = _session(ledger)
    bad_enum = ledger.call(
        "evidence_add", session_id=sid, claim_id=MISSING, source_id=MISSING, stance="sideways"
    )
    assert bad_enum["error"] == "invalid_input"
    no_sources = ledger.call("claim_add", session_id=sid, topic_id=tid, text="x", source_ids=[])
    assert no_sources["error"] == "invalid_input"
    both = ledger.call("evidence_list", claim_id=MISSING, topic_id=tid)
    assert both["error"] == "invalid_input"
    assert ledger.count("topic") == 1


def test_malformed_id_and_unknown_enum_are_invalid_input_and_write_nothing(
    ledger: Ledger,
) -> None:
    tid, sid = _session(ledger)
    source = ledger.call(
        "source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1
    )
    before = {t: ledger.count(t) for t in ("topic", "session", "claim", "evidence")}
    bad_calls: list[tuple[str, dict[str, Any]]] = [
        ("topic_get", {"topic_id": "not-a-uuid"}),
        ("session_start", {"topic_id": "not-a-uuid"}),
        ("claim_add", {"session_id": sid, "topic_id": tid, "text": "x", "source_ids": ["1"]}),
        (
            "claim_add",
            {
                "session_id": sid,
                "topic_id": tid,
                "text": "x",
                "source_ids": [source["id"]],
                "status": "bogus",
            },
        ),
    ]
    for name, args in bad_calls:
        result = ledger.call(name, **args)
        assert result["error"] == "invalid_input", name
        assert "not-a-uuid" not in result["detail"] and "bogus" not in result["detail"], name
    assert {t: ledger.count(t) for t in before} == before


def test_every_write_tool_checks_session_id_and_writes_nothing(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    source = ledger.call(
        "source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1
    )
    claim = ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="x", source_ids=[source["id"]]
    )["claim"]
    item = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["a"])["items"][0]
    before = {t: ledger.count(t) for t in ("charter", "agenda_item", "source", "claim", "evidence")}
    bad = MISSING
    calls: dict[str, dict[str, Any]] = {
        "charter_write": {"topic_id": tid, "core_questions": [], "in_scope": [], "parked": [],
                          "done_when": "d"},
        "agenda_set": {"topic_id": tid, "facets": ["b"]},
        "agenda_done": {"item_id": item["id"]},
        "source_register": {"url": "https://e.com/new", "kind": "docs", "tier": 1},
        "claim_add": {"topic_id": tid, "text": "y", "source_ids": [source["id"]]},
        "evidence_add": {"claim_id": claim["id"], "source_id": source["id"], "stance": "supports"},
        "question_answer": {"question_id": MISSING, "summary": "s"},
        "session_bookmark": {"note": "n"},
        "session_end": {"summary": "s"},
    }  # fmt: skip
    for name, args in calls.items():
        assert ledger.call(name, session_id=bad, **args)["error"] == "session_not_found", name
    after = {t: ledger.count(t) for t in before}
    assert after == before
    assert ledger.call("agenda_next", topic_id=tid)["item"]["status"] == "open"


def test_question_answer_sets_summary_and_status(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    conn = sqlite3.connect(ledger.paths.db)
    conn.execute(
        "INSERT INTO question (id, topic_id, session_id, asker, raw_text, clean_text, status)"
        " VALUES (?, ?, ?, 'curious', 'raw', 'clean', 'parked')",
        (qid := str(new_id()), tid, sid),
    )
    conn.commit()
    conn.close()
    assert [q["status"] for q in ledger.call("parked_list")["questions"]] == ["parked"]
    assert [q["id"] for q in ledger.call("parked_list", topic_id=tid)["questions"]] == [qid]
    answered = ledger.call("question_answer", session_id=sid, question_id=qid, summary="because")
    assert (answered["status"], answered["answer_summary"]) == ("answered", "because")
    assert ledger.call("question_get", question_id=qid)["answer_summary"] == "because"
    assert ledger.call("parked_list")["questions"] == []


def test_the_log_has_tool_names_and_no_arguments(ledger: Ledger) -> None:
    topic = ledger.call("topic_create", title="SENTINEL-ARG-123")
    ledger.call("topic_create", title="y" * 5000)  # rejected, still logged
    sentinels = [str(uuid4()) for _ in range(3)]
    ledger.call("topic_get", topic_id=sentinels[0])
    ledger.call(
        "claim_add",
        session_id=sentinels[1],
        topic_id=topic["id"],
        text="SENTINEL-TEXT",
        source_ids=[sentinels[2]],
    )
    log = (ledger.paths.logs / "mcp.log").read_text("utf-8")
    lines = log.splitlines()
    assert [ln.split()[1] for ln in lines] == [
        "topic_create",
        "topic_create",
        "topic_get",
        "claim_add",
    ]
    assert [ln.split()[3] for ln in lines] == [
        "ok",
        "invalid_input",
        "topic_not_found",
        "session_not_found",
    ]
    for ln in lines:
        stamp, _tool, millis, _code = ln.split()
        assert stamp.endswith("Z")
        assert millis.endswith("ms")
    for secret in ("SENTINEL", *sentinels, topic["id"], "yyyy", "GIL"):
        assert secret not in log


def test_serve_answers_initialize_over_real_stdio(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from deepdive.cli import app; app()", "mcp", "serve"],
        env={"DEEPDIVE_HOME": str(tmp_path)},
    )

    async def run() -> tuple[str, set[str], dict[str, Any]]:
        with anyio.fail_after(30):
            # legacy mode performs the initialize handshake instead of probing for discovery
            async with Client(params, mode="legacy") as client:
                names = {t.name for t in (await client.list_tools()).tools}
                created = await client.call_tool("topic_create", {"title": "over stdio"})
                assert created.structured_content is not None
                assert client.server_info is not None
                return client.server_info.name, names, created.structured_content

    name, names, created = asyncio.run(run())
    assert name == "deepdive"
    assert names == TOOLS
    assert created["title"] == "over stdio"
    assert Paths(tmp_path).db.exists()
    assert "topic_create" in (tmp_path / "logs" / "mcp.log").read_text("utf-8")


def test_map_get_returns_charter_agenda_progress_and_claims(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    empty = ledger.call("map_get", topic_id=tid)
    assert empty == {
        "charter": None, "agenda": [], "claims": [], "open_questions": [], "frontier": [],
    }  # fmt: skip
    ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["Why GIL?"],
        in_scope=["GIL", "asyncio"], parked=[], done_when="explain asyncio vs CPU-bound",
    )  # fmt: skip
    items = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["GIL", "asyncio"])
    ledger.call("agenda_done", session_id=sid, item_id=items["items"][0]["id"])
    src = ledger.call("source_register", session_id=sid, url="https://e.com/a", kind="docs", tier=1)
    ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="GIL serialises", source_ids=[src["id"]]
    )
    got = ledger.call("map_get", topic_id=tid)
    assert got["charter"]["in_scope"] == ["GIL", "asyncio"]
    assert [(i["facet"], i["status"]) for i in got["agenda"]] == [
        ("GIL", "done"),
        ("asyncio", "open"),
    ]
    assert [(c["text"], c["sources"]) for c in got["claims"]] == [
        ("GIL serialises", [{"id": src["id"], "url": "https://e.com/a"}])
    ]


def test_topic_overview_numbers_and_pages_recent_topics_first(ledger: Ledger) -> None:
    ids = [ledger.call("topic_create", title=f"T{i}")["id"] for i in range(12)]
    ledger.call("topic_create", title="kid", parent_topic_id=ids[0])
    ledger.call("session_start", topic_id=ids[0])
    first, second = (ledger.call("topic_overview", page=p) for p in (1, 2))
    assert (first["pages"], first["total"], len(first["topics"])) == (2, 12, 10)
    top = first["topics"][0]
    assert (top["n"], top["id"], top["children"][0]["n"]) == ("1", ids[0], "1.1")  # active first
    assert [t["title"] for t in first["topics"][1:3]] == ["T11", "T10"]  # then newest
    assert [(t["n"], t["title"]) for t in second["topics"]] == [("11", "T2"), ("12", "T1")]
    assert ledger.call("topic_overview", page=0)["error"] == "invalid_input"
    assert ledger.call("topic_overview", page=9)["topics"] == second["topics"]  # clamped
    found = ledger.call("topic_overview", query="KID")["topics"]  # a child's title finds its parent
    assert [t["id"] for t in found] == [ids[0]]
    clock.set_now(datetime(2030, 1, 1, tzinfo=UTC))  # sessions are second-precise; order them
    ledger.call("session_start", topic_id=ledger.call("topic_create", title="x")["id"])
    child = ledger.call("topic_create", title="kid2", parent_topic_id=ids[5])
    clock.set_now(datetime(2030, 1, 2, tzinfo=UTC))
    ledger.call("session_start", topic_id=child["id"])
    clock.set_now(None)
    assert ledger.call("topic_overview")["topics"][0]["id"] == ids[5]  # child activity lifts parent


def test_first_charter_activates_a_scoping_topic(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    write = {"session_id": sid, "topic_id": tid, "core_questions": ["Why?"], "in_scope": ["a"]}
    assert ledger.call("topic_get", topic_id=tid)["status"] == "scoping"
    ledger.call("charter_write", **write, parked=[], done_when="done")
    assert ledger.call("topic_get", topic_id=tid)["status"] == "active"
    ledger.call("charter_write", **write, parked=[], done_when="done v2")
    assert ledger.call("topic_get", topic_id=tid)["status"] == "active"


def test_resume_brief_orders_sections_and_resumes_at_the_bookmarked_item(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    fresh = ledger.call("resume_brief", topic_id=tid)
    assert list(fresh) == [
        "where_we_left_off",
        "recap_checks",
        "new_findings",
        "weakened_claims",
        "next_agenda_item",
    ]
    assert fresh["next_agenda_item"] is None
    assert fresh["where_we_left_off"]["summary"] is None
    items = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["A", "B", "C"])["items"]
    ledger.call("agenda_done", session_id=sid, item_id=items[0]["id"])
    ledger.call("session_bookmark", session_id=sid, agenda_item_id=items[2]["id"], note="at C")
    ledger.call("session_end", session_id=sid, summary="Covered A.")
    ledger.call("session_start", topic_id=tid)  # a later, empty session must not hide the bookmark
    got = ledger.call("resume_brief", topic_id=tid)
    assert (got["recap_checks"], got["new_findings"]) == ([], [])
    assert got["where_we_left_off"]["summary"] == "Covered A."
    assert got["where_we_left_off"]["bookmark_note"] == "at C"
    assert got["next_agenda_item"]["facet"] == "C"  # the bookmark wins over the first open item


def test_park_search_and_resume_a_question(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    q = ledger.call(
        "question_record", session_id=sid, topic_id=tid, asker="user",
        text="  does the   GIL affect numpy? ",
    )  # fmt: skip
    assert (q["status"], q["clean_text"], q["session_id"]) == (
        "open",
        "does the GIL affect numpy?",
        sid,
    )
    assert [o["id"] for o in ledger.call("map_get", topic_id=tid)["open_questions"]] == [q["id"]]
    assert ledger.call("parked_search", text="numpy GIL")["questions"] == []  # still open
    assert ledger.call("question_park", session_id=sid, question_id=q["id"])["status"] == "parked"
    assert ledger.call("map_get", topic_id=tid)["open_questions"] == []
    found = ledger.call("parked_search", text="numpy and the GIL")["questions"]
    assert [f["id"] for f in found] == [q["id"]]
    assert [p["id"] for p in ledger.call("parked_list", topic_id=tid)["questions"]] == [q["id"]]


def test_child_topic_round_trip_bookmarks_parent_and_returns_to_it(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["why"], in_scope=["a", "b"],
        parked=[], done_when="explain asyncio",
    )  # fmt: skip
    items = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["a", "b"])["items"]
    q = ledger.call(
        "question_record",
        session_id=sid,
        topic_id=tid,
        asker="user",
        text="how does CPython free memory?",
    )
    made = ledger.call("child_topic_create", session_id=sid, parent_id=tid, question_id=q["id"])
    child = made["child"]
    assert (child["parent_topic_id"], child["status"]) == (tid, "active")
    assert made["charter"]["done_when"] == "explain asyncio"
    assert made["charter"]["core_questions"] == ["how does CPython free memory?"]
    assert made["session"]["topic_id"] == child["id"]
    back = ledger.call("child_topic_finish", child_id=child["id"], session_id=sid)
    assert (back["parent_topic_id"], back["session_id"], back["agenda_facet"]) == (tid, sid, "a")
    assert back["bookmark"]["question_id"] == q["id"]
    assert back["bookmark"]["agenda_item_id"] == items[0]["id"]
    assert ledger.call("topic_get", topic_id=child["id"])["status"] == "finished"
    assert (
        ledger.call("child_topic_finish", child_id=child["id"], session_id=sid)["error"]
        == "invalid_input"
    )
    assert (
        ledger.call("child_topic_finish", child_id=tid, session_id=sid)["error"] == "invalid_input"
    )


def test_inside_a_child_questions_go_to_the_parents_frontier_and_children_stop(
    ledger: Ledger,
) -> None:
    tid, sid = _session(ledger)
    ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["why"], in_scope=["a"],
        parked=[], done_when="d",
    )  # fmt: skip
    q = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text="side q")
    child = ledger.call("child_topic_create", session_id=sid, parent_id=tid, question_id=q["id"])
    cid, csid = child["child"]["id"], child["session"]["id"]
    deeper = ledger.call(
        "question_record", session_id=csid, topic_id=cid, asker="user", text="deep"
    )
    refused = ledger.call(
        "child_topic_create", session_id=csid, parent_id=cid, question_id=deeper["id"]
    )
    assert refused["error"] == "child_depth_exceeded"
    assert ledger.count("topic") == 2
    frontier = ledger.call("frontier_add", session_id=csid, topic_id=tid, question_id=deeper["id"])
    assert [f["id"] for f in frontier["frontier"]] == [deeper["id"]]
    ledger.call(
        "frontier_add", session_id=csid, topic_id=tid, question_id=deeper["id"]
    )  # idempotent
    assert [f["id"] for f in ledger.call("map_get", topic_id=tid)["frontier"]] == [deeper["id"]]


def test_topic_recap_returns_every_section_in_order(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["why?"],
        in_scope=["a"], parked=["b"], done_when="can explain",
    )  # fmt: skip
    ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=["what"])
    src = ledger.call("source_register", session_id=sid, url="https://e.org/a", kind="docs", tier=1)
    ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="c1", source_ids=[src["id"]],
        excerpt_summary="x",
    )  # fmt: skip
    ledger.call("session_bookmark", session_id=sid, note="at what")
    ledger.call("session_end", session_id=sid, summary="first" + "x" * 700)
    ledger.call("session_start", topic_id=tid)
    child = ledger.call("topic_create", title="Child", parent_topic_id=tid)
    for text in ("open one", "answered one"):
        q = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text=text)
    ledger.call("question_answer", session_id=sid, question_id=q["id"], summary="42")
    got = ledger.call("topic_recap", topic_id=tid)
    assert got["topic"]["id"] == tid and got["charter"]["done_when"] == "can explain"
    assert [a["facet"] for a in got["agenda"]] == ["what"]
    first, second = got["sessions"]
    assert second["summary"] is None and first["bookmark_note"] == "at what"
    assert first["summary"].endswith("...") and got["truncated"] is True
    assert got["claims"][0]["sources"] == [{"id": src["id"], "url": "https://e.org/a"}]
    assert [x["text"] for x in got["questions"]["open"]] == ["open one"]
    assert got["questions"]["answered"][0]["answer_summary"] == "42"
    assert got["children"] == [{"title": child["title"], "status": child["status"]}]


@pytest.mark.parametrize(
    "title", ["../../etc/passwd", "/abs/x", "日本語", "A" * 200, "..", "a/b\\c"]
)
def test_recap_save_stays_inside_recaps(ledger: Ledger, title: str) -> None:
    topic = ledger.call("topic_create", title=title)
    sid = ledger.call("session_start", topic_id=topic["id"])["id"]
    args = {"session_id": sid, "topic_id": topic["id"]}
    saved = ledger.call("recap_save", **args, markdown="# one")
    path = (ledger.paths.root / saved["path"]).resolve()
    assert path.parent == ledger.paths.recaps.resolve() and path.read_text() == "# one"
    assert saved["bytes"] == 5 and len(path.name) < 70
    ledger.call("recap_save", **args, markdown="# two")  # same topic, same day overwrites
    assert path.read_text() == "# two" and len(list(ledger.paths.recaps.iterdir())) == 1


def test_recap_save_keeps_same_titled_topics_apart(ledger: Ledger) -> None:
    sid = _session(ledger)[1]
    for title in ("Same", "Same"):
        tid = ledger.call("topic_create", title=title)["id"]
        ledger.call("recap_save", session_id=sid, topic_id=tid, markdown=f"# {tid}")
    assert len(list(ledger.paths.recaps.iterdir())) == 2


def _chartered(ledger: Ledger, facets: list[str]) -> tuple[str, str, list[dict[str, Any]]]:
    tid, sid = _session(ledger)
    ledger.call(
        "charter_write", session_id=sid, topic_id=tid, core_questions=["why"], in_scope=facets,
        parked=[], done_when="d",
    )  # fmt: skip
    items = ledger.call("agenda_set", session_id=sid, topic_id=tid, facets=facets)["items"]
    return tid, sid, items


def _ask(ledger: Ledger, sid: str, tid: str, text: str) -> str:
    q = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text=text)
    return str(q["id"])


def test_resume_brief_falls_back_when_the_bookmarked_item_is_done(ledger: Ledger) -> None:
    tid, sid, items = _chartered(ledger, ["A", "B"])
    ledger.call("session_bookmark", session_id=sid, agenda_item_id=items[1]["id"], note="at B")
    ledger.call("agenda_done", session_id=sid, item_id=items[1]["id"])
    got = ledger.call("resume_brief", topic_id=tid)
    assert got["next_agenda_item"]["facet"] == "A"


def test_child_topic_create_refusals_and_note_survive(ledger: Ledger) -> None:
    tid, sid, _ = _chartered(ledger, ["a"])
    other, osid = _session(ledger)
    ledger.call("charter_write", session_id=osid, topic_id=other, core_questions=["w"],
                in_scope=[], parked=[], done_when="d")  # fmt: skip
    bare, bsid = _session(ledger)  # no charter
    q1, q2 = _ask(ledger, sid, tid, "one"), _ask(ledger, sid, tid, "two")
    foreign, bare_q = _ask(ledger, osid, other, "far"), _ask(ledger, bsid, bare, "bare")
    ledger.call("session_bookmark", session_id=sid, note="mine")
    parked = _ask(ledger, sid, tid, "parked")
    ledger.call("question_park", session_id=sid, question_id=parked)
    refused = [
        (osid, tid, q1), (sid, tid, foreign), (sid, tid, parked), (bsid, bare, bare_q),
    ]  # fmt: skip
    for session_id, parent_id, question_id in refused:
        got = ledger.call(
            "child_topic_create", session_id=session_id, parent_id=parent_id,
            question_id=question_id,
        )  # fmt: skip
        assert got["error"] in {"invalid_input", "charter_not_found"}, got
    assert ledger.count("topic") == 3
    made = ledger.call("child_topic_create", session_id=sid, parent_id=tid, question_id=q1)
    cid, csid = made["child"]["id"], made["session"]["id"]
    assert ledger.call("question_get", question_id=q1)["status"] == "partial"
    assert [o["id"] for o in ledger.call("map_get", topic_id=tid)["open_questions"]] == [q2]
    again = ledger.call("child_topic_create", session_id=sid, parent_id=tid, question_id=q2)
    assert again["error"] == "invalid_input"  # unfinished child
    wrong = ledger.call("child_topic_finish", child_id=cid, session_id=csid)
    assert wrong["error"] == "invalid_input"
    back = ledger.call("child_topic_finish", child_id=cid, session_id=sid)
    assert back["bookmark"]["note"] == "mine"


def test_frontier_add_and_question_park_refuse_foreign_questions(ledger: Ledger) -> None:
    tid, sid = _session(ledger)
    other, osid = _session(ledger)
    foreign, mine = _ask(ledger, osid, other, "far"), _ask(ledger, sid, tid, "near")
    assert (
        ledger.call("frontier_add", session_id=sid, topic_id=tid, question_id=foreign)["error"]
        == "invalid_input"
    )
    assert ledger.call("question_park", session_id=sid, question_id=foreign)["error"] == (
        "invalid_input"
    )
    assert ledger.call("question_park", session_id=sid, question_id=MISSING)["error"] == (
        "question_not_found"
    )
    ledger.call("question_park", session_id=sid, question_id=mine)
    assert ledger.call("question_park", session_id=sid, question_id=mine)["error"] == (
        "invalid_input"
    )  # no longer open
    bad = ledger.call("question_record", session_id=sid, topic_id=other, asker="user", text="x")
    assert bad["error"] == "invalid_input"


def _submit_ledger(tmp_path: Path, relation: str = "same") -> Ledger:
    """A ledger whose classifier calls every candidate `relation`, in scope."""

    class Fixed:
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            def pick(key: str, q: Question) -> Answer:
                top = "yes" if key == "is_question" else "in" if key == "scope" else relation
                return Answer(probs={top: 0.99, "x": 0.01})

            return ClassifyResult(
                answers={k: pick(k, q) for k, q in questions.items()}, provider="fake"
            )

    paths = Paths(tmp_path)
    return Ledger(create_server(paths, classifier=Fixed()), paths)


def test_question_submit_matches_and_links(tmp_path: Path) -> None:
    """question_submit stores a matched question with an edge; question_link records the guide's."""
    ledger = _submit_ledger(tmp_path)
    tid, sid = _session(ledger)
    first = ledger.call("question_submit", session_id=sid, topic_id=tid, asker="user", text="GIL?")
    assert (first["kind"], first["related"]) == ("matched", [])  # no past questions
    again = ledger.call(
        "question_submit", session_id=sid, topic_id=tid, asker="user", text="what is the GIL again?"
    )
    assert again["related"][0]["id"] == first["question_id"]
    assert "repeat" in again["context"] or "repeated" in again["context"]
    assert ledger.count("question_edge") == 1
    assert ledger.count("question_edge WHERE created_at IS NOT NULL") == 1  # the matcher timed it
    dup = ledger.call(
        "question_submit", session_id=sid, topic_id=tid, asker="curious", text="the GIL, again?"
    )
    assert (dup["kind"], dup["question_id"]) == ("duplicate", None)
    assert ledger.count("question") == 2
    link = ledger.call(
        "question_link", session_id=sid, from_id=again["question_id"],
        to_id=first["question_id"], relation="builds_on",
    )  # fmt: skip
    assert (link["relation"], link["classifier"]) == ("builds_on", "guide")
    assert ledger.count("question_edge WHERE created_at IS NOT NULL") == 1  # question_link too
    same = first["question_id"]
    bad = ledger.call("question_link", session_id=sid, from_id=same, to_id=same, relation="same")
    assert bad["error"] == "invalid_input"


def test_question_submit_and_link_validation(tmp_path: Path) -> None:
    """Blank text is refused; question_link needs both questions in the session's topic and
    marks a user's `same` link as a repeat."""
    ledger = _submit_ledger(tmp_path)
    tid, sid = _session(ledger)
    blank = ledger.call("question_submit", session_id=sid, topic_id=tid, asker="user", text=" ")
    assert blank["error"] == "invalid_input"
    a = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text="a?")
    b = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text="b?")
    other = ledger.call("topic_create", title="other")["id"]
    osid = ledger.call("session_start", topic_id=other)["id"]
    c = ledger.call("question_record", session_id=osid, topic_id=other, asker="user", text="c?")
    cross = ledger.call(
        "question_link", session_id=sid, from_id=a["id"], to_id=c["id"], relation="same"
    )
    assert cross["error"] == "invalid_input"
    missing = ledger.call(
        "question_link", session_id=sid, from_id=a["id"], to_id=MISSING, relation="same"
    )
    assert missing["error"] == "question_not_found"
    ok = ledger.call(
        "question_link", session_id=sid, from_id=a["id"], to_id=b["id"], relation="same"
    )
    assert ok["repeat"] is True


def test_question_link_repeat_adds_evidence_once(tmp_path: Path) -> None:
    """Linking a user's question as `same` writes repeat evidence on the earlier question's
    concepts; linking the same pair again adds nothing."""
    ledger = _submit_ledger(tmp_path)
    tid, sid = _session(ledger)
    earlier = ledger.call(
        "question_record", session_id=sid, topic_id=tid, asker="user", text="a?", concepts=["GIL"]
    )
    again = ledger.call("question_record", session_id=sid, topic_id=tid, asker="user", text="b?")
    for _ in range(2):
        ledger.call(
            "question_link", session_id=sid, from_id=again["id"], to_id=earlier["id"],
            relation="same",
        )  # fmt: skip
    assert ledger.count("knowledge_evidence WHERE kind = 'repeat_question'") == 1
    with Database(ledger.paths.db) as db:
        (gil,) = Store(db).concepts.for_question(earlier["id"])
        (row,) = SqliteKnowledgeStore(db).list_evidence(gil.id)
    assert str(row.question_id) == again["id"]


def test_session_attach_links_and_reattaches(ledger: Ledger) -> None:
    """session_attach stores the link; attaching the same agent id again moves it."""
    _, first = _session(ledger)
    _, second = _session(ledger)
    agent = "11111111-2222-4333-8444-555555555555"
    got = ledger.call("session_attach", session_id=first, agent_session_id=agent)
    assert (got["agent_session_id"], got["session_id"]) == (agent, first)
    ledger.call("session_attach", session_id=second, agent_session_id=agent)
    assert ledger.count("agent_session") == 1
    row = ledger.call("session_attach", session_id=second, agent_session_id=agent)
    assert row["session_id"] == second


@pytest.mark.parametrize("case", ["unknown", "ended", "bad-agent-id"])
def test_session_attach_refuses(ledger: Ledger, case: str) -> None:
    """An unknown or ended engine session, or a non-UUID agent id, is an ordinary error result."""
    _, sid = _session(ledger)
    agent = "11111111-2222-4333-8444-555555555555"
    if case == "ended":
        ledger.call("session_end", session_id=sid, summary="s")
    got = ledger.call(
        "session_attach",
        session_id=MISSING if case == "unknown" else sid,
        agent_session_id="nope" if case == "bad-agent-id" else agent,
    )
    assert (
        got["error"]
        == {
            "unknown": "session_not_found",
            "ended": "invalid_input",
            "bad-agent-id": "invalid_input",
        }[case]
    )
    assert ledger.count("agent_session") == 0


def test_concept_tools_tag_list_and_merge(ledger: Ledger) -> None:
    """Questions and claims take concept tags; a topic lists them; merge leaves one concept."""
    tid, sid = _session(ledger)
    question = ledger.call(
        "question_record", session_id=sid, topic_id=tid, text="why a GIL?", asker="user",
        concepts=["Locks"],
    )  # fmt: skip
    source = ledger.call(
        "source_register", session_id=sid, url="https://e.com", kind="docs", tier=1
    )
    ledger.call(
        "claim_add", session_id=sid, topic_id=tid, text="the GIL is a lock",
        source_ids=[source["id"]], concepts=["mutex"],
    )  # fmt: skip
    tagged = ledger.call("concept_tag", question_id=question["id"], concepts=["GIL", "lock"])
    names = {c["name"]: c["id"] for c in tagged["concepts"]}
    assert list(names) == ["gil", "lock"]
    listed = ledger.call("concept_list", topic_id=tid)["concepts"]
    assert [c["name"] for c in listed] == ["gil", "lock", "mutex"]
    mutex = listed[2]["id"]
    assert ledger.call("concept_merge", a=names["lock"], b=mutex)["name"] == "lock"
    assert [c["name"] for c in ledger.call("concept_list")["concepts"]] == ["gil", "lock"]


def test_session_student_mode_defaults_to_both_and_can_be_set(ledger: Ledger) -> None:
    """A new session has student_mode both; session_student_mode_set changes it, junk is refused."""
    tid, _ = _session(ledger)
    started = ledger.call("session_start", topic_id=tid)
    assert started["student_mode"] == "both"
    sid = started["id"]
    got = ledger.call("session_student_mode_set", session_id=sid, mode="skeptic")
    assert got["student_mode"] == "skeptic"
    assert ledger.call("session_student_mode_set", session_id=sid, mode="loud")["error"] == (
        "invalid_input"
    )
