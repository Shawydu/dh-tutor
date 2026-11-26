"""Claude Code hooks: stdin JSON in, stdout out; real temp DB, fake classifiers, no network."""

import json
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx
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


def pre_tool(paths: Paths, tool: str = "WebSearch", session_id: str = AGENT) -> dict[str, str]:
    raw = json.dumps({"session_id": session_id, "tool_name": tool, "tool_input": {}})
    return json.loads(Hooks(paths).pre_tool(raw))["hookSpecificOutput"]  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("tool", "calls", "decision"),
    [
        ("WebSearch", 2, "allow"),
        ("WebSearch", 3, "deny"),
        ("WebFetch", 3, "allow"),
    ],
    ids=["within-budget", "budget-spent", "fetch-is-not-counted"],
)
def test_pre_tool_counts_searches_against_the_session_budget(
    paths: Paths, tool: str, calls: int, decision: str
) -> None:
    """WebSearch spends the session budget and is denied once it is spent; WebFetch never is."""
    paths.config.write_text("[search]\nsession_budget = 2\n")
    attach(paths)
    outs = [pre_tool(paths, tool) for _ in range(calls)]
    assert outs[-1]["permissionDecision"] == decision
    assert outs[-1]["hookEventName"] == "PreToolUse" and outs[-1]["permissionDecisionReason"]


def test_pre_tool_denies_without_an_engine_session(paths: Paths) -> None:
    """An unattached Claude session cannot search: the reason says to start a session."""
    out = pre_tool(paths, session_id=str(uuid4()))
    assert out["permissionDecision"] == "deny" and "/dive" in out["permissionDecisionReason"]


@pytest.mark.parametrize("case", ["unknown-tool", "ended-session", "malformed-json"])
def test_pre_tool_fails_closed(paths: Paths, case: str) -> None:
    """An unknown tool, an ended session or malformed JSON is denied."""
    attach(paths, ended=case == "ended-session")
    if case == "malformed-json":
        out = json.loads(Hooks(paths).pre_tool("not json"))["hookSpecificOutput"]
    else:
        out = pre_tool(paths, "Bash" if case == "unknown-tool" else "WebSearch")
    assert out["permissionDecision"] == "deny"


def test_engine_search_and_the_hook_share_one_counter(tmp_path: Path) -> None:
    """One engine search plus one hook search reach a limit of 2; the next of either is refused."""
    paths = Paths(tmp_path)
    paths.config.write_text('[search]\nsession_budget = 2\napis = ["hn"]\n')
    ledger = Ledger(
        create_server(
            paths, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": []}))
        ),
        paths,
    )
    sid = _session(ledger)[1]
    ledger.call("session_attach", session_id=sid, agent_session_id=AGENT)
    assert ledger.call("search", query="gil", session_id=sid)["budget_remaining"] == 1
    assert pre_tool(paths)["permissionDecision"] == "allow"
    assert ledger.call("search", query="gil2", session_id=sid)["error"] == "budget_exhausted"
    assert pre_tool(paths)["permissionDecision"] == "deny"
