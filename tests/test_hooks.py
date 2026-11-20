"""Claude Code hooks: stdin JSON in, stdout out; real temp DB, fake classifiers, no network."""

import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_ledger_server import Ledger, _session
from typer.testing import CliRunner

from deepdive import clock
from deepdive.adapters.claude_code import hooks
from deepdive.adapters.claude_code.hooks import FALLBACK, Hooks
from deepdive.classify import Answer, ClassifyResult, Question
from deepdive.cli import app
from deepdive.ledger.server import create_server
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.repos import Store

AGENT = str(uuid4())


class Fixed:
    """Every key answers: a question, in scope, unrelated to anything."""

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        def pick(key: str) -> Answer:
            return Answer(probs={"yes" if key == "is_question" else "in": 0.99, "x": 0.01})

        return ClassifyResult(answers={k: pick(k) for k in questions}, provider="fake")


class Raising:
    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        raise RuntimeError("jev is down")


class Slow(Fixed):
    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        time.sleep(1)
        return super().classify(state, questions)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    p = Paths(tmp_path)
    p.ensure_dirs()
    with Database(p.db) as db:
        db.migrate()
    return p


def attach(paths: Paths, *, ended: bool = False) -> None:
    """One topic with an open (or ended) session attached to AGENT."""
    with Database(paths.db) as db:
        store = Store(db)
        topic = store.topics.create("GIL")
        now = clock.now()
        session = store.sessions.start(topic.id, at=now)
        if ended:
            store.sessions.end(session.id, "done", at=now)
        store.agent_sessions.attach(UUID(AGENT), session.id, at=now)


def payload(prompt: str, session_id: str = AGENT) -> str:
    return json.dumps({"prompt": prompt, "session_id": session_id, "hook_event_name": "x"})


def test_user_prompt_prints_the_nested_context(paths: Paths) -> None:
    """The output is exactly hookSpecificOutput.additionalContext, the matcher's rendered text."""
    attach(paths)
    out = json.loads(Hooks(paths, Fixed()).user_prompt(payload("what is the GIL?")))
    assert list(out) == ["hookSpecificOutput"]
    inner = out["hookSpecificOutput"]
    assert list(inner) == ["hookEventName", "additionalContext"]
    assert inner["hookEventName"] == "UserPromptSubmit" and inner["additionalContext"]
    with Database(paths.db) as db:  # the hook stored the question for the attached session
        assert db.conn.execute("SELECT COUNT(*) FROM question").fetchone() == (1,)


@pytest.mark.parametrize(
    ("prompt", "session_id", "ended"),
    [
        ("what is the GIL?", str(uuid4()), False),
        ("what is the GIL?", AGENT, True),
        ("/resume GIL", AGENT, False),
        ("   ", AGENT, False),
    ],
    ids=["not-attached", "session-ended", "slash-command", "blank"],
)
def test_user_prompt_stays_silent(paths: Paths, prompt: str, session_id: str, ended: bool) -> None:
    """Nothing to add: no output, and nothing stored."""
    attach(paths, ended=ended)
    assert Hooks(paths, Raising()).user_prompt(payload(prompt, session_id)) == ""
    with Database(paths.db) as db:
        assert db.conn.execute("SELECT COUNT(*) FROM question").fetchone() == (0,)


def fallback() -> str:
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": FALLBACK}}
    )


def test_classifier_error_gives_the_fallback_and_is_logged(paths: Paths) -> None:
    """A raising classifier on an attached session: fallback context; log has class, not prompt."""
    attach(paths)
    assert Hooks(paths, Raising()).user_prompt(payload("what is the GIL?")) == fallback()
    log = (paths.logs / "hooks.log").read_text()
    assert "RuntimeError" in log and "GIL" not in log


def test_slow_classifier_is_cut_at_the_timeout(
    paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A classifier slower than TIMEOUT yields the fallback after about TIMEOUT, and a log line."""
    assert hooks.TIMEOUT == 8
    monkeypatch.setattr(hooks, "TIMEOUT", 0.2)
    attach(paths)
    start = time.monotonic()
    assert Hooks(paths, Slow()).user_prompt(payload("what is the GIL?")) == fallback()
    assert time.monotonic() - start < 0.9
    assert "timeout" in (paths.logs / "hooks.log").read_text()


def test_bad_stdin_is_swallowed(paths: Paths) -> None:
    """Garbage on stdin never raises."""
    assert Hooks(paths).user_prompt("not json") == ""


def test_session_start_brief(paths: Paths) -> None:
    """The brief lists the recent topic, a /resume hint, and the agent_session_id line."""
    attach(paths)
    out = Hooks(paths).session_start(json.dumps({"session_id": AGENT, "source": "startup"}))
    assert "- GIL" in out and "/resume GIL" in out
    assert out.splitlines()[-1] == f"agent_session_id: {AGENT}"


def test_fresh_home_gives_the_empty_brief_and_silent_prompts(tmp_path: Path) -> None:
    """A home never touched by the MCP server: a no-topics brief, and no per-prompt error."""
    fresh = Paths(tmp_path / "new")
    out = Hooks(fresh).session_start(json.dumps({"session_id": AGENT}))
    assert "no topics yet" in out and out.endswith(f"agent_session_id: {AGENT}")
    assert Hooks(fresh, Raising()).user_prompt(payload("what is the GIL?")) == ""
    assert not (fresh.logs / "hooks.log").exists()


def test_attach_through_the_mcp_tool_then_the_hook_finds_the_topic(tmp_path: Path) -> None:
    """End to end: session_start + session_attach over MCP, then the hook matches that topic."""
    paths = Paths(tmp_path)
    ledger = Ledger(create_server(paths, classifier=Fixed()), paths)
    tid, sid = _session(ledger)
    ledger.call("session_attach", session_id=sid, agent_session_id=AGENT)
    out = json.loads(Hooks(paths, Fixed()).user_prompt(payload("what is the GIL?")))
    assert out["hookSpecificOutput"]["additionalContext"]
    with Database(paths.db) as db:
        assert db.conn.execute("SELECT topic_id, session_id FROM question").fetchall() == [
            (UUID(tid), UUID(sid))
        ]


def test_cli_hooks_read_stdin_and_print(paths: Paths, monkeypatch: pytest.MonkeyPatch) -> None:
    """The commands wire stdin to the hook and exit 0, with empty stdout when nothing to say."""
    monkeypatch.setenv("DEEPDIVE_HOME", str(paths.root))
    runner = CliRunner()
    brief = runner.invoke(app, ["hook", "session-start"], input=json.dumps({"session_id": AGENT}))
    assert brief.exit_code == 0 and brief.output.strip().endswith(f"agent_session_id: {AGENT}")
    quiet = runner.invoke(app, ["hook", "user-prompt"], input=payload("hi"))
    assert (quiet.exit_code, quiet.output) == (0, "")
