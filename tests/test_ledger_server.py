"""Ledger MCP contract tests: the server runs in-process on a real temp SQLite file; no network."""

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from deepdive.ledger.server import LedgerServer, create_server
from deepdive.paths import Paths
from deepdive.store.ids import new_id

TOOLS = {
    "topic_create", "topic_get", "topic_list", "topic_pin", "map_get",
    "charter_write", "charter_get",
    "session_start", "session_bookmark", "session_end",
    "agenda_set", "agenda_next", "agenda_done",
    "source_register", "claim_add", "claim_list", "evidence_add", "evidence_list",
    "question_get", "question_answer", "parked_list",
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
    assert empty == {"charter": None, "agenda": [], "claims": []}
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
    assert [(c["text"], c["source_ids"]) for c in got["claims"]] == [
        ("GIL serialises", [src["id"]])
    ]
