import pytest
from live.session import Session


@pytest.mark.live
def test_topics_lists_through_the_engine(session: Session) -> None:
    """`/topics` in a fresh home calls topic_overview, and deepdive's hooks answer with exit 0."""
    turn = session.turn("/topics")
    assert "mcp__deepdive__topic_overview" in [c.name for c in turn.tool_calls]
    hooks = {h.name.split(":")[0]: h.exit_code for h in turn.hooks}
    assert hooks["SessionStart"] == 0 and hooks["UserPromptSubmit"] == 0
