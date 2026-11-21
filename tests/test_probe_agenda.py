"""Probe topic selection and search agenda: real temp SQLite on the seeded topics."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import Seed
from typer.testing import CliRunner

from deepdive.adapters.claude_code.headless import ClaudeProbe
from deepdive.cli import app
from deepdive.config import ProbeConfig
from deepdive.paths import Paths
from deepdive.probe.agenda import AgendaBuilder, search_words
from deepdive.probe.select import TopicSelector
from deepdive.store.enums import QuestionAsker, QuestionEdgeRelation, QuestionStatus
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


def test_default_selection_is_active_topics(store: Store, prepared: Seed) -> None:
    """With no config the probe covers topics with a recent session, not only pinned ones."""
    picked = TopicSelector(store, ProbeConfig()).select(NOW)
    assert [t.id for t in picked] == [prepared.topics["python-concurrency"]]


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
        (None, "agenda"),  # the open facet itself, after the questions on it
    ]
    assert entries[-1].question == "Real parallelism"
    # every entry searches the topic name; its own words only rank
    assert {e.query for e in entries} == {"Concurrency control"}


def test_topic_with_only_agenda_items_gets_entries(store: Store, prepared: Seed) -> None:
    """Open facets are searched even when the topic has no unresolved question."""
    topic = store.topics.create("Fresh topic").id
    items = store.agenda.replace_items(topic, ["First facet", "Second facet"])
    store.agenda.mark_done(items[0].id)
    entries = AgendaBuilder(store, ProbeConfig()).build(topic)
    assert [(e.question_id, e.agenda_item_id, e.kind, e.question) for e in entries] == [
        (None, items[1].id, "agenda", "Second facet")
    ]
    assert (entries[0].query, entries[0].keywords) == ("Fresh topic", ["Second", "facet"])


@pytest.mark.parametrize(
    ("terms", "query"),
    [(["Python", "asyncio"], "Python asyncio"), ([], "Fresh topic")],
    ids=["charter-terms", "empty-falls-back-to-title"],
)
def test_query_words_come_from_the_charter(store: Store, terms: list[str], query: str) -> None:
    """The charter's search terms are the required query words; no terms means the title's words."""
    topic = store.topics.create("Fresh topic").id
    store.charters.write(
        topic, core_questions=["a"], in_scope=["b"], parked=[], done_when="c", search_terms=terms
    )
    store.agenda.replace_items(topic, ["Some facet"])
    assert AgendaBuilder(store, ProbeConfig()).build(topic)[0].query == query


def test_only_the_next_facet_is_on_the_agenda(store: Store) -> None:
    """Several open facets give one entry (the next), so they do not crowd out questions."""
    topic = store.topics.create("Fresh topic").id
    items = store.agenda.replace_items(topic, ["First facet", "Second facet"])
    entries = AgendaBuilder(store, ProbeConfig()).build(topic)
    assert [e.agenda_item_id for e in entries] == [items[0].id]


def test_hands_on_facets_are_skipped(store: Store) -> None:
    """A facet the user does by hand is passed over for the next researchable one."""
    topic = store.topics.create("Fresh topic").id
    items = store.agenda.replace_items(topic, ["Hands-on experiment", "Snapshot isolation"])
    entries = AgendaBuilder(store, ProbeConfig()).build(topic)
    assert [e.agenda_item_id for e in entries] == [items[1].id]


def test_same_linked_questions_get_one_entry(store: Store, prepared: Seed) -> None:
    """A re-asked question (same edge) is researched once: the earliest of the group stays."""
    topic = prepared.topics["python-concurrency"]
    first = store.questions.add(topic, QuestionAsker.USER, "How do I use GIL?", "How do I use GIL?")
    again = store.questions.add(topic, QuestionAsker.USER, "Using the GIL?", "Using the GIL?")
    store.edges.add(again.id, first.id, QuestionEdgeRelation.SAME, repeat=True)
    ids = [e.question_id for e in AgendaBuilder(store, ProbeConfig()).build(topic)]
    assert first.id in ids and again.id not in ids


def test_reask_of_an_answered_question_is_not_researched(store: Store, prepared: Seed) -> None:
    """A same edge to an earlier question of any status drops the later open one."""
    topic = prepared.topics["python-concurrency"]
    first = store.questions.add(topic, QuestionAsker.USER, "How do I use GIL?", "How do I use GIL?")
    store.questions.set_status(first.id, QuestionStatus.ANSWERED)
    again = store.questions.add(topic, QuestionAsker.USER, "Using the GIL?", "Using the GIL?")
    store.edges.add(again.id, first.id, QuestionEdgeRelation.SAME, repeat=True)
    ids = [e.question_id for e in AgendaBuilder(store, ProbeConfig()).build(topic)]
    assert again.id not in ids


@pytest.mark.parametrize(
    ("text", "skip", "expected"),
    [
        ("Why?", set(), []),
        ("How does the GIL limit threads?", set(), ["GIL", "limit", "threads"]),
        ("Is IO or io faster than threads, threads?", {"threads"}, ["IO", "faster"]),
        (
            "one two three four five six seven",
            set(),
            ["one", "two", "three", "four", "five", "six"],
        ),
    ],
    ids=["only-stop-words", "question", "caps-skip-repeat", "capped"],
)
def test_keywords_shape(text: str, skip: set[str], expected: list[str]) -> None:
    """Keywords drop stop words, repeats and skipped words, keep 2-letter capitals, at most 6."""
    assert search_words(text, skip) == expected


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
        "   - search: Apache Iceberg | optional: happens two writers commit table same\n"
        f"2. [challenge] {q2}\n"
        "   - search: Apache Iceberg | optional: adding more writer threads CPU cores\n"
    )


def test_headless_prompt_names_a_facet_by_agenda_item(store: Store) -> None:
    """A facet entry has no question id; the prompt gives the agenda item id to file against."""
    topic = store.topics.create("Fresh topic").id
    item = store.agenda.replace_items(topic, ["First facet"])[0]
    entries = AgendaBuilder(store, ProbeConfig()).build(topic)
    prompt = ClaudeProbe(Paths(Path("/x")), timeout=1).prompt(uuid4(), topic, entries)
    assert f"1. [agenda] agenda_item_id {item.id}: First facet" in prompt
