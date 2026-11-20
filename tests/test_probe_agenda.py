"""Probe topic selection and search agenda: real temp SQLite on the seeded topics."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import Seed
from typer.testing import CliRunner

from deepdive.cli import app
from deepdive.config import ProbeConfig
from deepdive.probe.agenda import AgendaBuilder
from deepdive.probe.select import TopicSelector
from deepdive.store.enums import QuestionEdgeRelation
from deepdive.store.repos import Store

NOW = datetime(2026, 1, 20, tzinfo=UTC)


@pytest.fixture
def prepared(store: Store, seed_topics: Seed) -> Seed:
    """Iceberg pinned; Python concurrency had a session 3 days ago, Iceberg one 30 days ago."""
    store.topics.pin(seed_topics.topics["iceberg"])
    store.sessions.start(seed_topics.topics["iceberg"], at=NOW - timedelta(days=30))
    store.sessions.start(seed_topics.topics["python-concurrency"], at=NOW - timedelta(days=3))
    return seed_topics


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (dict(topic_selection="all"), ["iceberg", "python-concurrency"]),
        (dict(topic_selection="pinned"), ["iceberg"]),
        (dict(topic_selection="active"), ["python-concurrency"]),
        (dict(topic_selection="active", active_days=60), ["python-concurrency", "iceberg"]),
        (dict(topic_selection="active", active_days=60, max_topics=1), ["python-concurrency"]),
        (dict(topic_selection="list", topics=["Some other topic"]), []),
        (
            dict(topic_selection="list", topics=["concurrency control in python vs parallelism"]),
            ["python-concurrency"],
        ),
        (dict(topic_selection="all", max_topics=1), ["iceberg"]),
    ],
    ids=["all", "pinned", "active", "active-window", "active-cap", "list-miss", "list-hit", "cap"],
)
def test_selection(
    store: Store, prepared: Seed, config: dict[str, object], expected: list[str]
) -> None:
    """Each topic_selection mode picks the right topics (pinned first) and max_topics caps them."""
    picked = TopicSelector(store, ProbeConfig(**config)).select(NOW)  # type: ignore[arg-type]
    assert [t.id for t in picked] == [prepared.topics[k] for k in expected]


def test_ranking_on_seeded_data(store: Store, prepared: Seed) -> None:
    """Clash first, then open questions on the current agenda item, then frontier, then oldest."""
    topic, q = prepared.topics["python-concurrency"], prepared.questions
    store.edges.add(q["asyncio_cpu"], q["locks_needed"], QuestionEdgeRelation.CLASHES)
    store.agenda.replace_items(topic, ["Real parallelism"])
    entries = AgendaBuilder(store, ProbeConfig()).build(topic)
    assert [(e.question_id, e.kind) for e in entries] == [
        (q["asyncio_cpu"], "clash"),
        (q["free_threaded"], "clash"),  # partial, clash edge from the seed
        (q["locks_needed"], "clash"),
        (q["multiprocessing"], "agenda"),
    ]
    first = entries[0]
    assert first.queries[0] == first.question
    assert len(first.queries) == 3 and first.queries[1].startswith(first.question)


def test_partial_question_with_clash_ranks_first(store: Store, prepared: Seed) -> None:
    """A partially answered question still counts as unresolved, so a clash puts it first."""
    q = prepared.questions
    entries = AgendaBuilder(store, ProbeConfig()).build(prepared.topics["python-concurrency"])
    assert (entries[0].question_id, entries[0].kind) == (q["free_threaded"], "clash")


def test_agenda_is_capped(store: Store, prepared: Seed) -> None:
    """searches_per_topic limits the agenda length."""
    entries = AgendaBuilder(store, ProbeConfig(searches_per_topic=2)).build(
        prepared.topics["iceberg"]
    )
    assert len(entries) == 2


def test_probe_plan_output(
    store: Store,
    prepared: Seed,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frozen_clock: object,
) -> None:
    """`deepdive probe plan` prints the selected topics' agendas, in a stable format."""
    # the db fixture names its file test.db; the CLI reads deepdive.db, so link the two
    (tmp_path / "deepdive.db").symlink_to(tmp_path / "test.db")
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[probe]\ntopic_selection = "pinned"\nsearches_per_topic = 2\n', "utf-8"
    )
    result = CliRunner().invoke(app, ["probe", "plan"])
    assert result.exit_code == 0, result.output
    q1 = "What happens when two writers commit to an Iceberg table at the same moment?"
    q2 = "Does adding more writer threads or CPU cores make Iceberg commits conflict more often?"
    assert result.output == (
        "# Apache Iceberg and what it solves\n"
        f"1. [challenge] {q1}\n"
        f"   - {q1}\n"
        f"   - {q1} table metadata\n"
        f"   - {q1} table metadata snapshots\n"
        f"2. [challenge] {q2}\n"
        f"   - {q2}\n"
        f"   - {q2} table metadata\n"
        f"   - {q2} table metadata snapshots\n"
    )
