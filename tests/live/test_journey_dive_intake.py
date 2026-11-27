import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from live.session import Session

TOPIC = "/dive Python list comprehensions"
CONTEXT = "I know basic Python loops. I want to read other people's code more easily."
CHARTER = (
    "Just curiosity. Core question: when to use one instead of a for loop. Skip generators for "
    "now. Search term: Python. Done when I can rewrite a loop as a comprehension. "
    "That charter looks good, please save it."
)


@pytest.mark.live
def test_dive_intake_ends_scoping_with_a_charter(home: Path) -> None:
    """`/dive` plus scoping answers creates a topic and an open session, then writes a charter."""
    session = Session(home, "dive-intake", max_turns=25)
    turns = [session.turn(text) for text in (TOPIC, CONTEXT, CHARTER)]
    calls = [c for t in turns for c in t.tool_calls]
    for name in ("topic_create", "session_start", "charter_write"):
        made = [c for c in calls if c.name == f"mcp__deepdive__{name}"]
        assert made, f"{name} never called"
        assert not any(c.error for c in made), f"{name} failed: {[c.result for c in made]}"

    with closing(sqlite3.connect(f"file:{home / 'deepdive.db'}?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM topic").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM session WHERE ended_at IS NULL").fetchone() == (1,)
        attached = db.execute(
            "SELECT count(*) FROM agent_session a JOIN session s ON s.id = a.session_id"
            " WHERE s.ended_at IS NULL"
        ).fetchone()
        latest = db.execute("SELECT search_terms FROM charter ORDER BY version DESC").fetchone()
    assert attached == (1,)  # the PostToolUse hook linked Claude's session, not the guide
    assert latest and latest[0] != "[]", latest  # charters are versioned; the guide may revise
