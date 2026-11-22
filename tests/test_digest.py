"""The morning digest: building, the digest_get tool, resume with an item, config fallback."""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from conftest import Seed

from deepdive.config import Config, DigestConfig
from deepdive.digest.build import NOTHING_NEW, DigestBuilder
from deepdive.knowledge.store import KnowledgeState, SqliteKnowledgeStore
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import MARKDOWN_MAX
from deepdive.ledger.tools.digest import DigestTools
from deepdive.ledger.tools.topics import TopicTools
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.enums import (
    ClaimStatus,
    DiscoveryEffect,
    DiscoveryTargetType,
    QuestionEdgeRelation,
)
from deepdive.store.errors import DigestNotFoundError
from deepdive.store.models import Discovery
from deepdive.store.repos import Store

DAY = date(2026, 1, 2)


def _discover(store: Store, seed: Seed) -> tuple[Discovery, Discovery]:
    run = store.probe_runs.create(list(seed.topics.values()), at=datetime(2026, 1, 1, tzinfo=UTC))
    topic = seed.topics["iceberg"]
    at = datetime(2026, 1, 1, tzinfo=UTC)
    new = store.sources.register(url="https://example.org/a", kind="blog", tier=3, seen_at=at).id
    other = store.sources.register(url="https://example.org/b", kind="blog", tier=3, seen_at=at).id
    weak = store.discoveries.add(
        run.id, topic, new, DiscoveryTargetType.CLAIM, seed.claims[0],
        DiscoveryEffect.WEAKENS, 0.4, "The spec allows a retry.",
    )  # fmt: skip
    strong = store.discoveries.add(
        run.id, topic, other, DiscoveryTargetType.QUESTION,
        seed.questions["problem"], DiscoveryEffect.ANSWERS, 0.9, "A table is a metadata tree.",
    )  # fmt: skip
    return weak, strong


def test_digest_snapshot(store: Store, seed_topics: Seed, tmp_path: Path) -> None:
    """Findings are grouped by topic, best first, with link and resume line; edges and shared
    concepts listed."""
    weak, strong = _discover(store, seed_topics)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    with store.db.transaction():
        store.concepts.tag_question(seed_topics.questions["commit_concurrent"], ["OCC"], at)
        store.concepts.tag_question(seed_topics.questions["locks_needed"], ["occ"], at)
    claim = store.claims.require(seed_topics.claims[0])
    question = store.questions.require(seed_topics.questions["problem"])
    topic = "Apache Iceberg and what it solves"
    expected = f"""# Digest — 2026-01-02

## {topic}

- **answers** question: A table is a metadata tree.
  Why it matters: "{question.clean_text}". Source: [example.org](https://example.org/b).
  Resume: `/resume {topic} --item {strong.id}`
- **weakens** claim: The spec allows a retry.
  Why it matters: "{claim.text}". Source: [example.org](https://example.org/a).
  Resume: `/resume {topic} --item {weak.id}`

## Connections across topics

- {topic}: "{store.questions.require(seed_topics.questions["commit_concurrent"]).clean_text}" ↔ Concurrency control in Python vs parallelism: "{store.questions.require(seed_topics.questions["locks_needed"]).clean_text}" (aspect)
- {topic}: "{store.questions.require(seed_topics.questions["commit_concurrent"]).clean_text}" ↔ Concurrency control in Python vs parallelism: "{store.questions.require(seed_topics.questions["locks_needed"]).clean_text}" (concept: occ)
"""  # noqa: E501
    assert DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(DAY) == expected


def test_empty_day_says_nothing_new(store: Store, tmp_path: Path) -> None:
    """No unread discoveries and no new edges give the short digest."""
    builder = DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path)
    assert builder.build(DAY) == f"# Digest — 2026-01-02\n\n{NOTHING_NEW}\n"


def test_read_discoveries_and_old_edges_drop_out(
    store: Store, seed_topics: Seed, tmp_path: Path
) -> None:
    """An opened discovery and an edge older than the previous digest are not listed again."""
    weak, strong = _discover(store, seed_topics)
    for d in (weak, strong):
        store.discoveries.mark_read(d.id, datetime(2026, 1, 1, tzinfo=UTC))
    (tmp_path / "2026-01-01.md").write_text("x")  # the edge was made 2026-01-01 06:00, so new
    assert "Connections across topics" in DigestBuilder(
        store, SqliteKnowledgeStore(store.db), tmp_path
    ).build(DAY)
    (tmp_path / "2026-01-02.md").write_text("x")
    assert NOTHING_NEW in DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(
        date(2026, 1, 3)
    )


@pytest.mark.parametrize(
    ("earlier", "listed"), [(None, True), ("2026-01-01", True), ("2026-01-02", False)]
)
def test_unread_findings_older_than_the_last_digest_drop_out(
    store: Store, seed_topics: Seed, tmp_path: Path, earlier: str | None, listed: bool
) -> None:
    """An unread finding from a probe run before the last digest's day is not repeated."""
    _discover(store, seed_topics)  # probe run on 2026-01-01
    if earlier:
        (tmp_path / f"{earlier}.md").write_text("x")
    (tmp_path / "notes.md").write_text("x")  # not a digest file: ignored
    assert (
        "## Apache Iceberg"
        in DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(date(2026, 1, 3))
    ) is listed


@pytest.mark.parametrize(("earlier", "listed"), [(None, True), ("2026-01-02", False)])
def test_edge_without_a_time_is_new_only_with_no_earlier_digest(
    store: Store, seed_topics: Seed, tmp_path: Path, earlier: str | None, listed: bool
) -> None:
    """A pre-0007 edge (no created_at) shows only when there is no earlier digest."""
    q = seed_topics.questions
    store.edges.add(q["problem"], q["gil"], QuestionEdgeRelation.NARROWER)
    if earlier:
        (tmp_path / f"{earlier}.md").write_text("x")
    text = DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(date(2026, 1, 3))
    assert ("(narrower)" in text) is listed


def test_resume_with_item_marks_it_read(db: Database, store: Store, seed_topics: Seed) -> None:
    """Resuming with an item marks only it read; plain resume lists the unread ones."""
    weak, strong = _discover(store, seed_topics)
    topics = TopicTools(LedgerContext(db, Paths(Path("."))))
    topic = seed_topics.topics["iceberg"]

    def ids(**kw: object) -> list[str]:
        brief = asyncio.run(topics.resume_brief(topic, **kw))  # type: ignore[arg-type]
        return [f["id"] for f in brief["new_findings"]]

    assert ids() == [str(strong.id), str(weak.id)]
    assert ids(item=weak.id) == [str(weak.id), str(strong.id)]
    assert store.claims.require(seed_topics.claims[0]).status == ClaimStatus.OPEN
    assert ids() == [str(strong.id)]
    with pytest.raises(InvalidInputError):
        ids(item=seed_topics.sources["spec"])


def test_resume_lists_the_best_three_findings(
    db: Database, store: Store, seed_topics: Seed
) -> None:
    """Of four unread findings, resume lists the three most relevant, best first."""
    at = datetime(2026, 1, 1, tzinfo=UTC)
    topic = seed_topics.topics["iceberg"]
    run = store.probe_runs.create([topic], at=at)
    made = []
    for n, relevance in enumerate([0.5, 0.9, 0.6, 0.8]):
        source = store.sources.register(
            url=f"https://example.org/{n}", kind="blog", tier=3, seen_at=at
        )
        made.append(store.discoveries.add(
            run.id, topic, source.id, DiscoveryTargetType.QUESTION,
            seed_topics.questions["problem"], DiscoveryEffect.ANSWERS, relevance, "A finding.",
        ))  # fmt: skip
    brief = asyncio.run(TopicTools(LedgerContext(db, Paths(Path(".")))).resume_brief(topic))
    assert [f["id"] for f in brief["new_findings"]] == [str(made[i].id) for i in (1, 3, 2)]


@pytest.mark.parametrize(
    ("which", "status"),
    [(0, ClaimStatus.OPEN), (1, ClaimStatus.ESTABLISHED)],
    ids=["weakens-reopens", "answers-leaves-claims"],
)
def test_opening_a_finding_marks_it_read_and_reopens_a_weakened_claim(
    db: Database, store: Store, seed_topics: Seed, which: int, status: ClaimStatus
) -> None:
    """discovery_open marks the finding read; only a weakening one reopens its claim."""
    found = _discover(store, seed_topics)[which]
    got = asyncio.run(TopicTools(LedgerContext(db, Paths(Path(".")))).discovery_open(found.id))
    opened = store.discoveries.get(found.id)
    assert opened is not None and opened.read_at is not None
    assert store.claims.require(seed_topics.claims[0]).status == status
    assert (got["reopened_claim"] is not None) is (status == ClaimStatus.OPEN)


def test_digest_get_truncates_long_markdown(db: Database, tmp_path: Path) -> None:
    """A digest over MARKDOWN_MAX is cut and flagged truncated."""
    paths = Paths(tmp_path)
    paths.digests.mkdir()
    (paths.digests / "2026-01-02.md").write_text("x" * (MARKDOWN_MAX + 1))
    got = asyncio.run(DigestTools(LedgerContext(db, paths), Config()).digest_get(DAY))
    assert (len(got["markdown"]), got["truncated"]) == (MARKDOWN_MAX, True)


@pytest.mark.parametrize("built", [True, False])
def test_digest_get_found_or_not_found(db: Database, tmp_path: Path, built: bool) -> None:
    """digest_get returns the file's markdown, or a not_found error."""
    paths = Paths(tmp_path)
    tools = DigestTools(LedgerContext(db, paths), Config())
    if built:
        DigestBuilder(Store(db), SqliteKnowledgeStore(db), paths.digests).write(DAY)
        got = asyncio.run(tools.digest_get(DAY))
        assert got["markdown"].startswith("# Digest — 2026-01-02") and not got["truncated"]
    else:
        with pytest.raises(DigestNotFoundError):
            asyncio.run(tools.digest_get(DAY))


@pytest.mark.parametrize(("path", "want"), [(None, Path("/home/x")), ("/else", Path("/else"))])
def test_unset_digest_path_follows_paths_and_a_set_one_wins(path: str | None, want: Path) -> None:
    """With no digest path configured the folder is Paths.digests; a set path overrides it."""
    assert DigestConfig(path=path).folder(Path("/home/x")) == want


def test_digest_renders_an_agenda_item_finding(
    store: Store, seed_topics: Seed, tmp_path: Path
) -> None:
    """A facet finding reads 'agenda item "<facet>"' under Why it matters."""
    topic = seed_topics.topics["iceberg"]
    run = store.probe_runs.create([topic], at=datetime(2026, 1, 1, tzinfo=UTC))
    src = store.sources.register(
        url="https://example.org/c", kind="blog", tier=3, seen_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    item = store.agenda.list_items(topic)[0]
    store.discoveries.add(
        run.id, topic, src.id, DiscoveryTargetType.AGENDA_ITEM, item.id,
        DiscoveryEffect.SUPPORTS, 0.9, "It covers this. It matters.",
    )  # fmt: skip
    out = DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(DAY)
    assert f'Why it matters: agenda item "{item.facet}".' in out
    assert "**supports** agenda item:" in out


def test_recaps_due_lists_concepts_due_by_the_end_of_the_day(
    store: Store, db: Database, tmp_path: Path
) -> None:
    """The digest's Recaps due section names each due concept with level and confidence."""
    with store.db.transaction():
        due, later = store.concepts.ensure(["GIL", "locks"])
        for concept, day in ((due, 2), (later, 3)):
            SqliteKnowledgeStore(db).set_state(
                KnowledgeState(
                    concept_id=concept.id,
                    level=3,
                    confidence=0.4,
                    stability=0,
                    last_evidence_at=None,
                    next_recap_at=datetime(2026, 1, day, 9, tzinfo=UTC),
                )  # fmt: skip
            )
    out = DigestBuilder(store, SqliteKnowledgeStore(store.db), tmp_path).build(DAY)
    assert out == "# Digest — 2026-01-02\n\n## Recaps due\n\n- gil (level 3.0, confidence 0.4)\n"
