"""Claude Code workspace generation: files land in tmp_path, nothing touches the real home."""

import json
from pathlib import Path

from typer.testing import CliRunner

from deepdive.adapters.claude_code.install import MARKER, REPO
from deepdive.cli import app

runner = CliRunner()


def init(ws: Path, *flags: str) -> tuple[int, str]:
    result = runner.invoke(app, ["init", "--workspace", str(ws), *flags])
    return result.exit_code, result.output


def test_init_writes_the_locked_down_workspace(tmp_path: Path) -> None:
    assert init(tmp_path)[0] == 0
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp["mcpServers"]["deepdive"] == {
        "command": "uv",
        "args": ["run", "--project", str(REPO), "deepdive", "mcp", "serve"],
    }
    settings = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert settings["permissions"]["allow"] == ["mcp__deepdive__*"]
    assert {"WebSearch", "WebFetch", "Bash", "Edit", "Write", "Read", "Glob", "Grep"} <= set(
        settings["permissions"]["deny"]
    )
    run = f"uv run --project {REPO} deepdive hook"
    assert settings["hooks"] == {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f"{run} user-prompt", "timeout": 10}]}
        ],
        "SessionStart": [
            {
                "matcher": "startup|resume|clear",
                "hooks": [{"type": "command", "command": f"{run} session-start"}],
            }
        ],
    }
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "# Shared rules" in claude_md and "# Guide" in claude_md and "---" not in claude_md[:4]
    assert not (tmp_path / ".claude/agents").exists()
    for skill in ("dive", "topics", "resume", "parked", "sumup", "digest"):
        assert (tmp_path / f".claude/skills/{skill}/SKILL.md").exists()
    assert "$ARGUMENTS" in (tmp_path / ".claude/skills/dive/SKILL.md").read_text()
    assert (tmp_path / MARKER).exists()


def test_init_twice_changes_nothing_and_check_reports_edits(tmp_path: Path) -> None:
    init(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    code, out = init(tmp_path)
    assert code == 0 and "up to date" in out
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert init(tmp_path, "--check")[0] == 0

    (tmp_path / "CLAUDE.md").write_text("edited")
    code, out = init(tmp_path, "--check")
    assert code == 1 and "drift: CLAUDE.md" in out
    assert (tmp_path / "CLAUDE.md").read_text() == "edited"  # --check never writes
    init(tmp_path)
    assert init(tmp_path, "--check")[0] == 0


def test_init_refuses_a_workspace_without_the_marker(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("mine")
    code, out = init(tmp_path)
    assert code == 1 and "refusing" in out
    assert (tmp_path / "CLAUDE.md").read_text() == "mine"
    assert not (tmp_path / ".mcp.json").exists() and not (tmp_path / MARKER).exists()
    assert init(tmp_path, "--check")[0] == 1
