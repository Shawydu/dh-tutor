import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from replay import assert_dive_intake_state

from live.journeys import dive_intake
from live.session import Session


@pytest.mark.live
def test_dive_intake_ends_scoping_with_a_charter(home: Path) -> None:
    """`/dive` plus scoping answers creates a topic and an open session, then writes a charter."""
    session = Session(home, "dive-intake", max_turns=25)
    turns = dive_intake(session)
    calls = [c for t in turns for c in t.tool_calls]
    for name in ("topic_create", "session_start", "charter_write"):
        made = [c for c in calls if c.name == f"mcp__deepdive__{name}"]
        assert made, f"{name} never called"
        assert not any(c.error for c in made), f"{name} failed: {[c.result for c in made]}"

    assert_dive_intake_state(home / "deepdive.db")
    with closing(sqlite3.connect(f"file:{home / 'deepdive.db'}?mode=ro", uri=True)) as db:
        attached = db.execute(
            "SELECT count(*) FROM agent_session a JOIN session s ON s.id = a.session_id"
            " WHERE s.ended_at IS NULL"
        ).fetchone()
    assert attached == (1,)  # the PostToolUse hook linked Claude's session, not the guide
