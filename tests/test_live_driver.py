import stat
from pathlib import Path

import pytest
from live.session import JourneyError, Session, parse_stream

STREAM = Path(__file__).parent / "fixtures" / "sessions" / "smoke.jsonl"


def test_parse_stream_extracts_calls_hooks_and_text() -> None:
    """A recorded stream folds into tool calls (with denials), hook responses and assistant text."""
    turn = parse_stream(STREAM)
    assert [(c.name, c.error, c.result) for c in turn.tool_calls] == [
        ("mcp__deepdive__topic_overview", False, '{"topics":[],"page":1,"pages":1,"total":0}'),
        (
            "WebSearch",
            True,
            "PreToolUse:WebSearch hook error: No open deepdive session: start one with /dive first.",  # noqa: E501
        ),
    ]
    assert [(h.name, h.exit_code) for h in turn.hooks] == [
        ("SessionStart:startup", 0),
        ("UserPromptSubmit", 0),
    ]
    assert turn.text.startswith("The topic") and turn.num_turns == 7 and turn.session_id


def test_turn_cap_fails_naming_journey_and_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A claude run that ends in error_max_turns fails the journey with a clear message."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(
        "#!/bin/sh\n"
        'echo \'{"type":"result","subtype":"error_max_turns","num_turns":3,"session_id":"s"}\'\n'
        "exit 1\n"
    )
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPDIVE_HOME", str(home))  # keep the real secrets.env out of it
    (home / "workspace" / ".claude").mkdir(parents=True)
    (home / "workspace" / ".claude" / "settings.json").write_text(
        '{"permissions": {"allow": ["mcp__deepdive__*"]}}'
    )
    with pytest.raises(JourneyError, match=r"journey 'demo' hit its cap of 5 agent turns"):
        Session(home, "demo", max_turns=5).turn("hi")
