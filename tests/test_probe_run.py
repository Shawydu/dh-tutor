"""Probe run: discovery_add, the per-topic search budget, the lock and the runner. Real SQLite."""

import asyncio
import os
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fakes import FakeClassifier
from mcp import Client
from test_ledger_server import MISSING, Ledger
from test_search_web import handler

from deepdive.adapters.claude_code.headless import ClaudeProbe
from deepdive.classify import Answer, ClassifierUnavailable, ClassifyResult
from deepdive.config import ProbeConfig
from deepdive.knowledge.store import KnowledgeState, SqliteKnowledgeStore
from deepdive.ledger.context import ProbeScope
from deepdive.ledger.server import create_server
from deepdive.paths import Paths
from deepdive.probe.agenda import AgendaEntry
from deepdive.probe.lock import ProbeLock, ProbeLockedError
from deepdive.probe.runner import ProbeRunner
from deepdive.store.db import Database
from deepdive.store.enums import QuestionAsker, TopicStatus
from deepdive.store.models import TopicOutcome
from deepdive.store.repos import Store

NOW = datetime(2026, 1, 20, tzinfo=UTC)


@dataclass
class World:
    paths: Paths
    store: Store
    run: UUID
    topic: UUID
    question: UUID
    claim: UUID
    cited: UUID  # a source already evidence for `claim`
    fresh: UUID  # a source nothing cites yet
    other_question: UUID  # belongs to another topic
    item: UUID  # an agenda item of `topic`
    other_item: UUID  # an agenda item of the other topic


@pytest.fixture
def world(tmp_path: Path) -> World:
    paths = Paths(tmp_path)
    paths.ensure_dirs()
    db = Database(paths.db)
    db.migrate()
    store = Store(db)
    topic = store.topics.create("Iceberg")
    other = store.topics.create("Other")
    q = store.questions.add(topic.id, QuestionAsker.USER, "raw", "How do commits work?")
    oq = store.questions.add(other.id, QuestionAsker.USER, "raw", "Elsewhere?")

    def src(url: str) -> UUID:
        return store.sources.register(url=url, kind="web", tier=2, seen_at=NOW).id

    cited, fresh = src("https://e.com/cited"), src("https://e.com/fresh")
    claim = store.claims.add(topic.id, "Commits are atomic", [cited])
    run = store.probe_runs.create([topic.id], at=NOW)
    item = store.agenda.replace_items(topic.id, ["Commit protocol"])[0]
    other_item = store.agenda.replace_items(other.id, ["Elsewhere facet"])[0]
    return World(
        paths, store, run.id, topic.id, q.id, claim.id, cited, fresh, oq.id, item.id, other_item.id
    )


def ledger(
    w: World, relevant: float = 0.95, effect: str = "supports", budget: int | None = None
) -> Ledger:
    if budget:
        w.paths.config.write_text(
            f"[probe]\nsearches_per_topic = {budget}\nfetches_per_topic = {budget}\n"
        )
    fake = FakeClassifier(
        {
            "relevant": Answer(probs={"yes": relevant, "no": 1 - relevant}),
            "effect": Answer(probs={effect: 0.9, "answers": 0.1}),
        }
    )
    server = create_server(
        w.paths,
        transport=httpx.MockTransport(handler),
        classifier=fake,
        probe=ProbeScope(w.run, w.topic),
    )
    return Ledger(server, w.paths)


def add(led: Ledger, w: World, **over: object) -> dict:  # type: ignore[type-arg]
    args = dict(
        probe_run_id=str(w.run), topic_id=str(w.topic), source_id=str(w.fresh),
        target_type="question", target_id=str(w.question), summary="It says X. That matters.",
    )  # fmt: skip
    return led.call("discovery_add", **{**args, **over})


def test_discovery_add_stores_relevance_and_effect(world: World) -> None:
    """A relevant finding is stored with the classifier's effect and relevance."""
    led = ledger(world, relevant=0.95, effect="weakens")
    out = add(led, world)
    assert (out["effect"], out["relevance"], out["target_type"]) == ("weakens", 0.95, "question")
    assert led.count("discovery") == 1


def test_discovery_add_below_threshold_writes_nothing(world: World) -> None:
    """A finding under auto_threshold is dropped and not stored."""
    led = ledger(world, relevant=0.4)
    assert add(led, world)["dropped"] is True
    assert led.count("discovery") == 0


def test_discovery_add_accepts_an_agenda_item(world: World) -> None:
    """A facet finding is filed against the topic's agenda item."""
    out = add(ledger(world), world, target_type="agenda_item", target_id=str(world.item))
    assert (out["target_type"], out["target_id"]) == ("agenda_item", str(world.item))


FAR = datetime(2030, 1, 1, tzinfo=UTC)
PAST = datetime(2000, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("target", "level", "start", "due"),
    [("question", 3.5, FAR, True), ("claim", 3.5, FAR, True), ("question", 2.5, FAR, False),
     ("agenda_item", 3.5, FAR, False), ("question", 3.5, PAST, False)],
    ids=["question", "claim", "level_too_low", "agenda_item_never", "already_earlier_kept"],
)  # fmt: skip
def test_discovery_sets_well_known_concepts_due_now(
    world: World, target: str, level: float, start: datetime, due: bool
) -> None:
    """A stored discovery makes its concepts of level 3+ due now, never later than they were."""
    store = world.store
    far = start
    ids = {"question": world.question, "claim": world.claim, "agenda_item": world.item}
    (c,) = store.concepts.tag_question(world.question, ["commit"], NOW)
    store.concepts.tag_claim(world.claim, ["commit"])
    knowledge = SqliteKnowledgeStore(store.db)
    knowledge.set_state(
        KnowledgeState(concept_id=c.id, level=level, confidence=0.5, stability=0,
                       last_evidence_at=NOW, next_recap_at=far)
    )  # fmt: skip
    add(ledger(world), world, target_type=target, target_id=str(ids[target]))
    state = knowledge.get_state(c.id)
    assert state is not None and (state.next_recap_at != far) == due


@pytest.mark.parametrize("which", ["fresh", "cited"])
def test_discovery_add_refuses_a_source_the_topic_already_cites(world: World, which: str) -> None:
    """A source already in a discovery (twice) or in evidence (cited) is a duplicate_source."""
    led = ledger(world)
    sid = str(getattr(world, which))
    if which == "fresh":
        assert "error" not in add(led, world, source_id=sid)
    assert add(led, world, source_id=sid)["error"] == "duplicate_source"
    assert led.count("discovery") == (1 if which == "fresh" else 0)


@pytest.mark.parametrize(
    ("over", "error"),
    [
        ({"target_id": "other_question"}, "invalid_target"),  # another topic's question
        ({"target_type": "claim", "target_id": "question"}, "invalid_target"),  # wrong table
        ({"target_id": MISSING}, "invalid_target"),
        ({"target_type": "agenda_item", "target_id": "other_item"}, "invalid_target"),  # foreign
        ({"source_id": MISSING}, "source_not_found"),
        ({"topic_id": MISSING}, "invalid_input"),  # not this probe's scope
    ],
)
def test_discovery_add_refuses_bad_input(world: World, over: dict[str, str], error: str) -> None:
    """A bad target, source or scope is refused and nothing is written."""
    led = ledger(world)
    resolved = {k: str(getattr(world, v, v)) if k.endswith("_id") else v for k, v in over.items()}
    assert add(led, world, **resolved)["error"] == error
    assert led.count("discovery") == 0


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("search", {"query": "iceberg"}),
        ("fetch", {"url": "https://github.com/apache/iceberg"}),
    ],
)
def test_search_and_fetch_are_refused_past_the_topic_budget(
    world: World, tool: str, args: dict[str, str]
) -> None:
    """The third call with a limit of 2 is refused, and a new server instance keeps the count."""
    led = ledger(world, budget=2)
    assert "error" not in led.call(tool, **args)
    assert "error" not in led.call(tool, **args)
    again = ledger(world, budget=2)  # a restarted server: the count lives in the database
    assert again.call(tool, **args)["error"] == "budget_exhausted"
    if tool == "search":
        assert world.store.probe_runs.require(world.run).searches_used == 2


def test_probe_server_registers_exactly_its_tools(world: World) -> None:
    """A probe server offers the five probe tools and nothing else."""

    async def names() -> set[str]:
        async with Client(ledger(world).server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(names()) == {
        "search",
        "fetch",
        "discovery_add",
        "claim_list",
        "evidence_list",
    }


def test_discovery_add_reports_an_unavailable_classifier(world: World) -> None:
    """If no classifier can answer, discovery_add returns an error and writes nothing."""

    class Down:
        def classify(self, state: str, questions: object) -> ClassifyResult:
            raise ClassifierUnavailable("down")

    server = create_server(world.paths, classifier=Down(), probe=ProbeScope(world.run, world.topic))
    led = Ledger(server, world.paths)
    assert add(led, world)["error"] == "classifier_unavailable"
    assert led.count("discovery") == 0


# --- lock -------------------------------------------------------------------------------------


def test_lock_refuses_a_second_taker_until_released(tmp_path: Path) -> None:
    """A held lock refuses a second taker; leaving the block frees it."""
    path = tmp_path / "probe.lock"
    with ProbeLock(path):
        with pytest.raises(ProbeLockedError):
            ProbeLock(path).__enter__()
    with ProbeLock(path):
        pass


# --- runner -----------------------------------------------------------------------------------

STUB = """#!{python}
import json, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
if "FAILME" in prompt:
    print("boom", file=sys.stderr); sys.exit(1)
print(json.dumps({{"is_error": False, "result": "done: 0 discoveries, 0 dropped"}}))
"""


@pytest.fixture
def stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text(STUB.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.parametrize(
    ("bad", "status", "outcomes"),
    [
        ({"Bad"}, "failed", {"Bad": "failed", "Good": "ok"}),  # one fails, the other still runs
        ({"Bad", "Good"}, "failed", {"Bad": "failed", "Good": "failed"}),
        (set(), "ok", {"Bad": "ok", "Good": "ok"}),
    ],
)
def test_runner_isolates_a_failing_topic(
    world: World, stub_claude: None, bad: set[str], status: str, outcomes: dict[str, str]
) -> None:
    """The stub claude exits 1 when the prompt says FAILME; the other topics still run."""
    store = world.store
    for title in ("Bad", "Good"):
        t = store.topics.create(title, status=TopicStatus.ACTIVE)
        text = "FAILME" if title in bad else "a fine question"
        store.questions.add(t.id, QuestionAsker.USER, "r", text)
    cfg = ProbeConfig(topic_selection="list", topics=["Bad", "Good"])
    agent = ClaudeProbe(world.paths, timeout=30)
    result = ProbeRunner(store, cfg, world.paths, agent, lambda: NOW).run()
    titles = {t.id: t.title for t in store.topics.list_by_status(TopicStatus.ACTIVE)}
    assert {titles[t.topic_id]: t.outcome.value for t in result.run.topics} == outcomes
    assert result.run.status == status
    assert (world.paths.logs / "probe" / f"{result.run.id}.log").read_text().startswith("status:")
    assert not world.paths.probe_lock.exists()


def test_claude_command_line_is_locked_down(world: World) -> None:
    """The command carries the guide-02 flags and the prompt carries the agenda."""
    cmd = ClaudeProbe(world.paths).command("P", Path("m.json"))
    assert cmd[:3] == ["claude", "-p", "P"]
    assert "--bare" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__deepdive__*"
    assert "Bash" in cmd[cmd.index("--disallowedTools") + 1]
    assert cmd[-2:] == ["--output-format", "json"]


@pytest.mark.parametrize(
    ("stdout", "ok"),
    [
        (b"[]", False),
        (b'"x"', False),
        (b"\xff\xfe not utf8", False),
        (b'{"is_error": false, "result": "done"}', True),
    ],
)
def test_claude_output_that_is_not_an_envelope_is_a_failure(
    world: World, monkeypatch: pytest.MonkeyPatch, stdout: bytes, ok: bool
) -> None:
    """Non-dict JSON and undecodable bytes fail the topic instead of raising."""
    exe = world.paths.root / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(
        f"#!/bin/sh\nprintf '%b' '{stdout.decode('latin-1').encode('unicode_escape').decode()}'\n"
    )
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    entry = AgendaEntry(world.question, "open", "q", "x", [])
    assert ClaudeProbe(world.paths, timeout=30).run(world.run, world.topic, [entry]).ok is ok


@pytest.mark.parametrize(
    ("script", "detail"),
    [
        (
            """printf '{"is_error": true, "result": "  rate   limited "}'; exit 1""",
            "claude failed (exit 1): rate limited",
        ),
        ("echo 'x' >&2; echo '  bad   thing ' >&2; exit 2", "claude failed (exit 2): x bad thing"),
        ("echo 'auth s3cret-key failed' >&2; exit 1", "claude failed (exit 1): auth *** failed"),
    ],
    ids=["envelope", "stderr-tail", "secret-redacted"],
)
def test_claude_failure_detail_keeps_the_cause(
    world: World, monkeypatch: pytest.MonkeyPatch, script: str, detail: str
) -> None:
    """A failed claude run reports its cause on one line with secret values blanked."""
    exe = world.paths.root / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(f"#!/bin/sh\n{script}\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GITHUB_TOKEN", "s3cret-key")
    entry = AgendaEntry(world.question, "open", "q", "x", [])
    result = ClaudeProbe(world.paths, timeout=30).run(world.run, world.topic, [entry])
    assert (result.ok, result.detail) == (False, detail)


@pytest.mark.parametrize(
    ("outcomes", "status"),
    [
        ([], "ok"),
        (["ok", "skipped"], "ok"),
        (["ok", "budget_exhausted"], "budget_exhausted"),
        (["ok", "failed", "budget_exhausted"], "failed"),
    ],
)
def test_run_status_rule(outcomes: list[str], status: str) -> None:
    """failed beats budget_exhausted beats ok; no topics is ok."""
    assert ProbeRunner.status([TopicOutcome(o) for o in outcomes]) == status


def test_an_agent_that_raises_fails_only_its_topic(world: World) -> None:
    """An exception from the agent is that topic's failure, and the run is still finished."""

    class Boom:
        def run(self, *_: object) -> object:
            raise RuntimeError("x")

    t = world.store.topics.create("Live", status=TopicStatus.ACTIVE)
    world.store.questions.add(t.id, QuestionAsker.USER, "r", "an open question")
    cfg = ProbeConfig(topic_selection="all")
    result = ProbeRunner(world.store, cfg, world.paths, Boom(), lambda: NOW).run()  # type: ignore[arg-type]
    assert [t.outcome.value for t in result.run.topics] == ["failed"]
    assert result.run.status == "failed"
