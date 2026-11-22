import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from deepdive.cli import app
from deepdive.store.db import Database
from deepdive.store.enums import (
    AgendaItemStatus,
    ClaimStatus,
    DiscoveryEffect,
    DiscoveryTargetType,
    EvidenceStance,
    KnowledgeEvidenceGrade,
    KnowledgeEvidenceKind,
    ProbeRunStatus,
    QuestionAsker,
    QuestionEdgeRelation,
    QuestionStatus,
    SessionStudentMode,
    TopicStatus,
)
from deepdive.store.ids import new_id

runner = CliRunner()

# Every table in docs/design.md "Data model", plus the FTS index and the migration ledger.
DESIGN_TABLES = {
    "topic",
    "charter",
    "session",
    "agenda_item",
    "question",
    "question_edge",
    "concept",
    "question_concept",
    "claim",
    "source",
    "evidence",
    "discovery",
    "probe_run",
    "rubric",
    "knowledge_state",
    "knowledge_evidence",
    "poc_project",
    "frontier",  # 0002
    "agent_session",  # 0005
    "probe_topic",  # 0006
    "concept_alias",  # 0010
    "claim_concept",  # 0010
}
# every column that holds a closed set of values, and the lookup table it references
ENUM_COLUMNS = [
    ("topic", "status", "topic_status"),
    ("agenda_item", "status", "agenda_item_status"),
    ("question", "asker", "question_asker"),
    ("question", "status", "question_status"),
    ("question_edge", "relation", "question_edge_relation"),
    ("claim", "status", "claim_status"),
    ("evidence", "stance", "evidence_stance"),
    ("probe_run", "status", "probe_run_status"),
    ("discovery", "effect", "discovery_effect"),
    ("discovery", "target_type", "discovery_target_type"),
    ("knowledge_evidence", "kind", "knowledge_evidence_kind"),
    ("knowledge_evidence", "grade", "knowledge_evidence_grade"),
    ("session", "student_mode", "session_student_mode"),
]


ENUM_TABLES = {enum_table for _, _, enum_table in ENUM_COLUMNS}
EXTRA_TABLES = {"question_fts", "schema_migrations"} | ENUM_TABLES

NOW = "2026-01-01T00:00:00Z"


def u(n: int) -> str:
    """A well-formed lowercase UUID text for row `n`, for raw SQL."""
    return f"00000000-0000-7000-8000-{n:012x}"


ID1, ID2, MISSING = u(1), u(2), u(999)


@pytest.fixture
def seeded(db: Database) -> sqlite3.Connection:
    """One row of everything the foreign keys point at; ids are u(1) (two questions: u(1), u(2))."""
    db.conn.executescript(
        f"""
        INSERT INTO topic (id, title, status) VALUES ('{ID1}', 'threads', 'active');
        INSERT INTO session (id, topic_id, started_at) VALUES ('{ID1}', '{ID1}', '{NOW}');
        INSERT INTO question (id, topic_id, asker, raw_text, clean_text)
            VALUES ('{ID1}', '{ID1}', 'user', 'raw one', 'one'),
                   ('{ID2}', '{ID1}', 'user', 'raw two', 'two');
        INSERT INTO concept (id, name) VALUES ('{ID1}', 'mutex');
        INSERT INTO source (id, url, kind, tier, first_seen_at)
            VALUES ('{ID1}', 'https://example.com/a', 'docs', 1, '{NOW}');
        INSERT INTO claim (id, topic_id, text, status) VALUES ('{ID1}', '{ID1}', 'a claim', 'open');
        INSERT INTO probe_run (id, started_at, topics, status)
            VALUES ('{ID1}', '{NOW}', '[]', 'ok');
        """
    )
    return db.conn


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM pragma_table_list WHERE type IN ('table', 'virtual')")
    return {name for (name,) in rows if not name.startswith("sqlite_")}


def test_migrate_creates_every_design_table(db: Database) -> None:
    assert tables(db.conn) == DESIGN_TABLES | EXTRA_TABLES
    assert set(db.table_counts()) == DESIGN_TABLES | EXTRA_TABLES


def test_columns_follow_the_type_conventions(db: Database) -> None:
    """Every id is a UUID, every `*_at` a TIMESTAMP and vice versa."""
    cols = db.conn.execute(
        "SELECT t.name, c.name, c.type FROM pragma_table_list t, pragma_table_info(t.name) c"
        " WHERE t.schema = 'main' AND t.name NOT LIKE 'sqlite_%' AND t.type = 'table'"
    ).fetchall()
    assert cols
    for table, name, decl in cols:
        if name == "id" or name.endswith("_id"):
            assert decl == "UUID", f"{table}.{name} is {decl}"
        assert (decl == "TIMESTAMP") == name.endswith("_at"), f"{table}.{name} is {decl}"


def test_migrate_twice_is_a_no_op(tmp_path: Path) -> None:
    with Database(tmp_path / "twice.db") as db:
        assert db.migrate() == [
            "0001_init",
            "0002_frontier",
            "0003_activate_chartered_topics",
            "0004_edge_repeat",
            "0005_agent_session",
            "0006_discovery_target",
            "0007_edge_created_at",
            "0008_discovery_agenda_target",
            "0009_charter_search_terms",
            "0010_concepts",
            "0011_knowledge_level_real",
            "0012_session_student_mode",
        ]
        assert db.migrate() == []
        assert db.conn.execute("SELECT version, name FROM schema_migrations").fetchall() == [
            (1, "0001_init"),
            (2, "0002_frontier"),
            (3, "0003_activate_chartered_topics"),
            (4, "0004_edge_repeat"),
            (5, "0005_agent_session"),
            (6, "0006_discovery_target"),
            (7, "0007_edge_created_at"),
            (8, "0008_discovery_agenda_target"),
            (9, "0009_charter_search_terms"),
            (10, "0010_concepts"),
            (11, "0011_knowledge_level_real"),
            (12, "0012_session_student_mode"),
        ]


def test_connect_sets_pragmas(db: Database) -> None:
    assert db.conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert db.conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert db.conn.execute("PRAGMA busy_timeout").fetchone() == (5000,)


def test_connect_creates_missing_file_and_reopens_migrated(tmp_path: Path) -> None:
    path = tmp_path / "again.db"
    with Database(path) as first:
        first.migrate()
    with Database(path) as second:
        assert second.migrate() == []


# --- migration runner, with throwaway migration folders ---------------------------------------


def test_migrations_apply_in_order_once_each(tmp_path: Path) -> None:
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE second (id INTEGER);")
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE first (id INTEGER);")
    (tmp_path / "notes.txt").write_text("ignored")
    with Database(tmp_path / "order.db") as db:
        assert db.migrate(tmp_path) == ["0001_first", "0002_second"]
        assert db.migrate(tmp_path) == []
        (tmp_path / "0003_third.sql").write_text("CREATE TABLE third (id INTEGER);")
        assert db.migrate(tmp_path) == ["0003_third"]


def test_failing_migration_leaves_nothing_half_applied(tmp_path: Path) -> None:
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE ok (id INTEGER);")
    (tmp_path / "0002_bad.sql").write_text(
        "CREATE TABLE half (id INTEGER);\nINSERT INTO nowhere VALUES (1);"
    )
    with Database(tmp_path / "fail.db") as db:
        with pytest.raises(sqlite3.OperationalError):
            db.migrate(tmp_path)
        assert tables(db.conn) == {"ok", "schema_migrations"}
        assert db.conn.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
        assert not db.conn.in_transaction
        # once the file is fixed it applies cleanly, so nothing was marked applied
        (tmp_path / "0002_bad.sql").write_text("CREATE TABLE half (id INTEGER);")
        assert db.migrate(tmp_path) == ["0002_bad"]


def test_rebuilding_session_keeps_existing_rows_and_their_children(tmp_path: Path) -> None:
    """0012 rebuilds a populated session table; rows, children and foreign keys survive."""
    old = tmp_path / "old"
    old.mkdir()
    for f in resources.files("deepdive.store.migrations").iterdir():
        if f.name[:4].isdigit() and f.name < "0012":
            (old / f.name).write_text(f.read_text("utf-8"))
    topic, session, question = (str(new_id()) for _ in range(3))
    with Database(tmp_path / "old.db") as db:
        db.migrate(old)
        db.conn.execute("INSERT INTO topic (id, title, status) VALUES (?, 't', 'active')", (topic,))
        db.conn.execute(
            "INSERT INTO session (id, topic_id, started_at) VALUES (?, ?, ?)",
            (session, topic, "2026-01-01T00:00:00Z"),
        )
        db.conn.execute(
            "INSERT INTO question (id, topic_id, session_id, asker, raw_text, clean_text)"
            " VALUES (?, ?, ?, 'user', 'q?', 'q')",
            (question, topic, session),
        )
        assert db.migrate()[-1] == "0012_session_student_mode"
        assert db.conn.execute("SELECT id, student_mode FROM session").fetchall() == [
            (UUID(session), "both")
        ]
        assert db.conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute("DELETE FROM session")


def test_migration_that_breaks_foreign_keys_is_refused(tmp_path: Path) -> None:
    """Migrations run with foreign keys off, so a dangling reference is caught before commit."""
    (tmp_path / "0001_parent.sql").write_text(
        "CREATE TABLE parent (id TEXT PRIMARY KEY);"
        "CREATE TABLE child (parent_id TEXT REFERENCES parent (id));"
    )
    (tmp_path / "0002_dangle.sql").write_text("INSERT INTO child VALUES ('missing');")
    with Database(tmp_path / "fk.db") as db:
        with pytest.raises(sqlite3.IntegrityError, match="0002_dangle"):
            db.migrate(tmp_path)
        assert db.conn.execute("SELECT count(*) FROM child").fetchone() == (0,)


def test_duplicate_migration_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError, match="0001"):
        with Database(tmp_path / "dup.db") as db:
            db.migrate(tmp_path)


# --- topics: one level deep -------------------------------------------------------------------


def add_topic(conn: sqlite3.Connection, n: int, parent: int | None = None) -> None:
    conn.execute(
        "INSERT INTO topic (id, title, parent_topic_id, status) VALUES (?, 't', ?, 'active')",
        (u(n), parent and u(parent)),
    )


def test_child_topic_is_allowed(db: Database) -> None:
    add_topic(db.conn, 1)
    add_topic(db.conn, 2, parent=1)
    add_topic(db.conn, 3, parent=1)


def test_grandchild_topic_is_rejected(db: Database) -> None:
    add_topic(db.conn, 1)
    add_topic(db.conn, 2, parent=1)
    with pytest.raises(sqlite3.DatabaseError, match="one level deep"):
        add_topic(db.conn, 3, parent=2)
    assert db.conn.execute("SELECT count(*) FROM topic").fetchone() == (2,)


def test_reparenting_under_a_child_is_rejected(db: Database) -> None:
    add_topic(db.conn, 1)
    add_topic(db.conn, 2, parent=1)
    add_topic(db.conn, 3)
    with pytest.raises(sqlite3.DatabaseError, match="one level deep"):
        db.conn.execute("UPDATE topic SET parent_topic_id = ? WHERE id = ?", (u(2), u(3)))


def test_topic_with_children_cannot_become_a_child(db: Database) -> None:
    add_topic(db.conn, 1)
    add_topic(db.conn, 2, parent=1)
    add_topic(db.conn, 3)
    with pytest.raises(sqlite3.DatabaseError, match="one level deep"):
        db.conn.execute("UPDATE topic SET parent_topic_id = ? WHERE id = ?", (u(3), u(1)))


def test_reparenting_a_leaf_topic_is_allowed(db: Database) -> None:
    add_topic(db.conn, 1)
    add_topic(db.conn, 2)
    add_topic(db.conn, 3, parent=1)
    db.conn.execute("UPDATE topic SET parent_topic_id = ? WHERE id = ?", (u(2), u(3)))
    db.conn.execute("UPDATE topic SET parent_topic_id = NULL WHERE id = ?", (u(3),))


def test_topic_cannot_be_its_own_parent(db: Database) -> None:
    add_topic(db.conn, 1)
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("UPDATE topic SET parent_topic_id = ? WHERE id = ?", (ID1, ID1))


# --- question full-text index -----------------------------------------------------------------


def fts_ids(conn: sqlite3.Connection, query: str) -> list[str]:
    rows = conn.execute("SELECT question_id FROM question_fts WHERE question_fts MATCH ?", (query,))
    return [row[0] for row in rows]


def test_question_is_findable_by_clean_and_raw_text(seeded: sqlite3.Connection) -> None:
    seeded.execute(
        "INSERT INTO question (id, topic_id, asker, raw_text, clean_text)"
        f" VALUES ('{u(10)}', '{ID1}', 'guide', 'why do my goroutines starve',"
        " 'goroutine starvation causes')"
    )
    assert fts_ids(seeded, "starvation") == [u(10)]  # clean_text
    assert fts_ids(seeded, "goroutines") == [u(10)]  # raw_text
    assert fts_ids(seeded, "goroutine") == [u(10)]  # stemmed
    assert fts_ids(seeded, "clean_text: starvation") == [u(10)]
    assert fts_ids(seeded, "raw_text: starvation") == []


def test_fts_follows_update_and_delete(seeded: sqlite3.Connection) -> None:
    assert fts_ids(seeded, "clean_text: one") == [ID1]
    seeded.execute("UPDATE question SET clean_text = 'semaphores' WHERE id = ?", (ID1,))
    assert fts_ids(seeded, "clean_text: one") == []
    assert fts_ids(seeded, "semaphores") == [ID1]
    seeded.execute("UPDATE question SET raw_text = 'spinlocks' WHERE id = ?", (ID1,))
    assert fts_ids(seeded, "spinlocks") == [ID1]
    assert fts_ids(seeded, "raw") == [ID2]  # question 1's old raw text is gone, 2's remains
    seeded.execute("DELETE FROM question WHERE id = ?", (ID1,))
    assert fts_ids(seeded, "semaphores") == []
    assert fts_ids(seeded, "spinlocks") == []
    assert fts_ids(seeded, "two") == [ID2]


def test_fts_ignores_updates_to_other_columns(seeded: sqlite3.Connection) -> None:
    seeded.execute(
        "UPDATE question SET status = 'answered', answer_summary = 'done' WHERE id = ?", (ID1,)
    )
    assert fts_ids(seeded, "one") == [ID1]
    seeded.execute("INSERT INTO question_fts (question_fts, rank) VALUES ('integrity-check', 1)")


# --- value checks: ranges, json, self-rating rule ---------------------------------------------

Params = tuple[object, ...]

KE = (
    "INSERT INTO knowledge_evidence (id, concept_id, kind, grade, level, grader_confidence,"
    f" weight, created_at) VALUES ('{u(50)}', '{ID1}', %s, 1.0, '{NOW}')"
)

# (id, SQL with one placeholder, accepted param, rejected param)
CHECKS: list[tuple[str, str, object, object]] = [
    (
        "question_edge.confidence",
        f"INSERT INTO question_edge (from_id, to_id, relation, confidence)"
        f" VALUES ('{ID1}', '{ID2}', 'same', ?)",
        0.9,
        1.5,
    ),
    (
        "knowledge_evidence.grader_confidence",
        KE % "'recap_check', 'wrong', NULL, ?",
        0.0,
        -0.1,
    ),
    (
        "knowledge_evidence.self_rating_with_grade",
        KE % "'self_rating', ?, 2, NULL",
        None,
        "correct",
    ),
    (
        "knowledge_evidence.self_rating_without_level",
        KE % "'self_rating', NULL, ?, NULL",
        3,
        None,
    ),
    ("knowledge_evidence.level", KE % "'self_rating', NULL, ?, NULL", 4, 5),
    (
        "knowledge_state.level",
        f"INSERT INTO knowledge_state (concept_id, level, confidence, stability)"
        f" VALUES ('{ID1}', ?, 0.5, 1.0)",
        0,
        -1,
    ),
    (
        "knowledge_state.confidence",
        f"INSERT INTO knowledge_state (concept_id, level, confidence, stability)"
        f" VALUES ('{ID1}', 2, ?, 1.0)",
        1.0,
        1.01,
    ),
    (
        "charter.core_questions",
        f"INSERT INTO charter (topic_id, version, core_questions, in_scope, parked, done_when)"
        f" VALUES ('{ID1}', 1, ?, '[]', '[]', 'done')",
        '["why?"]',
        "not json",
    ),
    (
        "probe_run.topics",
        f"INSERT INTO probe_run (id, started_at, topics, status)"
        f" VALUES ('{u(50)}', '{NOW}', ?, 'ok')",
        "[1, 2]",
        "[1, 2",
    ),
    (
        "rubric.misconceptions",
        f"INSERT INTO rubric (question_id, key_points, misconceptions) VALUES ('{ID1}', '[]', ?)",
        "[]",
        "{",
    ),
    (
        "poc_project.question_ids",
        f"INSERT INTO poc_project (id, topic_id, path, question_ids, status)"
        f" VALUES ('{u(50)}', '{ID1}', 'p', ?, 'new')",
        "[1]",
        "1,2",
    ),
]


@pytest.mark.parametrize(("sql", "good", "bad"), [pytest.param(*c[1:], id=c[0]) for c in CHECKS])
def test_check_constraints(seeded: sqlite3.Connection, sql: str, good: object, bad: object) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        seeded.execute(sql, (bad,))
    seeded.execute(sql, (good,))  # the bad attempt left nothing behind that blocks this one


# --- enum columns: the lookup table is the closed set -----------------------------------------


@pytest.mark.parametrize(("table", "column", "enum_table"), ENUM_COLUMNS)
def test_enum_column_references_its_lookup_table(
    db: Database, table: str, column: str, enum_table: str
) -> None:
    fks = {(fk[3], fk[2]) for fk in db.conn.execute(f"PRAGMA foreign_key_list({table})")}
    assert (column, enum_table) in fks


def test_unknown_enum_value_is_rejected(seeded: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO knowledge_evidence (id, concept_id, kind, weight, created_at)"
        f" VALUES ('{ID1}', '{ID1}', ?, 1.0, '{NOW}')"
    )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        seeded.execute(sql, ("guess",))
    seeded.execute(sql, ("explained_back",))


def test_enum_tables_match_the_python_enums(db: Database) -> None:
    for enum in (
        TopicStatus, AgendaItemStatus, QuestionAsker, QuestionStatus, QuestionEdgeRelation,
        ClaimStatus, EvidenceStance, ProbeRunStatus, DiscoveryEffect, DiscoveryTargetType,
        KnowledgeEvidenceKind,
        KnowledgeEvidenceGrade, SessionStudentMode,
    ):  # fmt: skip
        table = "".join("_" + c.lower() if c.isupper() else c for c in enum.__name__).lstrip("_")
        values = {v for (v,) in db.conn.execute(f"SELECT value FROM {table}")}
        assert values == {m.value for m in enum}, table


# --- UUID and TIMESTAMP columns ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id", ["1", "not-a-uuid", u(10).upper(), u(1)[:-1], u(1) + "0", u(1).replace("0", "g", 1)]
)
def test_malformed_ids_are_rejected(db: Database, bad_id: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.conn.execute(
            "INSERT INTO topic (id, title, status) VALUES (?, 't', 'active')", (bad_id,)
        )


@pytest.mark.parametrize(
    "bad_time",
    ["2026-01-01", "2026-01-01T00:00:00", "2026-01-01 00:00:00Z", "2026-01-01T00:00:00+00:00",
     "2026-13-01T00:00:00Z", "yesterday"],
)  # fmt: skip
def test_malformed_timestamps_are_rejected(db: Database, bad_time: str) -> None:
    db.conn.execute("INSERT INTO topic (id, title, status) VALUES (?, 't', 'active')", (ID1,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.conn.execute(
            "INSERT INTO session (id, topic_id, started_at) VALUES (?, ?, ?)", (ID1, ID1, bad_time)
        )


def test_rows_come_back_as_uuid_and_aware_datetime(db: Database) -> None:
    db.conn.execute("INSERT INTO topic (id, title, status) VALUES (?, 't', 'active')", (ID1,))
    when = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=2)))  # stored as UTC
    db.conn.execute(
        "INSERT INTO session (id, topic_id, started_at) VALUES (?, ?, ?)", (ID1, ID1, when)
    )
    row = db.conn.execute("SELECT id, topic_id, started_at, ended_at FROM session").fetchone()
    assert row == (UUID(ID1), UUID(ID1), datetime(2026, 1, 1, 10, tzinfo=UTC), None)
    assert row[2].tzinfo is UTC
    assert db.conn.execute("SELECT started_at FROM session").fetchone()[0] == when
    assert db.conn.execute("SELECT CAST(started_at AS TEXT) FROM session").fetchone() == (
        "2026-01-01T10:00:00Z",
    )
    with pytest.raises(ValueError, match="naive"):
        db.conn.execute("UPDATE session SET ended_at = ?", (datetime(2026, 1, 1),))


def test_question_embedding_is_an_optional_blob(seeded: sqlite3.Connection) -> None:
    seeded.execute("UPDATE question SET embedding = ? WHERE id = ?", (b"\x00\x01\x02", ID1))
    assert seeded.execute("SELECT embedding FROM question WHERE id = ?", (ID1,)).fetchone() == (
        b"\x00\x01\x02",
    )
    assert seeded.execute("SELECT embedding FROM question WHERE id = ?", (ID2,)).fetchone() == (
        None,
    )


def test_charter_is_keyed_by_topic_and_version(seeded: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO charter (topic_id, version, core_questions, in_scope, parked, done_when)"
        f" VALUES ('{ID1}', ?, '[]', '[]', '[]', 'done')"
    )
    seeded.execute(sql, (1,))
    seeded.execute(sql, (2,))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        seeded.execute(sql, (2,))


def test_source_url_and_doi_are_unique(seeded: sqlite3.Connection) -> None:
    sql = (
        "INSERT INTO source (id, url, doi, kind, tier, first_seen_at)"
        " VALUES (?, ?, ?, 'paper', 2, ?)"
    )
    seeded.execute(sql, (u(10), None, "10.1/x", NOW))
    seeded.execute(sql, (u(11), None, None, NOW))
    seeded.execute(sql, (u(12), None, None, NOW))  # NULLs never collide
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        seeded.execute(sql, (u(13), None, "10.1/x", NOW))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        seeded.execute(sql, (u(13), "https://example.com/a", None, NOW))


# --- foreign keys -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param(
            "INSERT INTO question (id, topic_id, asker, raw_text, clean_text)"
            f" VALUES ('{u(50)}', '{MISSING}', 'user', 'r', 'c')",
            id="question.topic_id",
        ),
        pytest.param(
            "INSERT INTO evidence (id, claim_id, source_id, stance)"
            f" VALUES ('{u(50)}', '{ID1}', '{MISSING}', 'supports')",
            id="evidence.source_id",
        ),
        pytest.param(
            f"INSERT INTO question_edge (from_id, to_id, relation)"
            f" VALUES ('{ID1}', '{MISSING}', 'same')",
            id="question_edge.to_id",
        ),
        pytest.param(
            "INSERT INTO discovery (id, topic_id, probe_run_id, source_id, target_type, target_id,"
            " effect, relevance, summary)"
            f" VALUES ('{u(50)}', '{ID1}', '{ID1}', '{MISSING}', 'question', '{ID1}', 'answers',"
            " 0.5, 's')",
            id="discovery.source_id",
        ),
        pytest.param(
            "INSERT INTO knowledge_state (concept_id, level, confidence, stability)"
            f" VALUES ('{MISSING}', 1, 0.5, 1.0)",
            id="knowledge_state.concept_id",
        ),
        pytest.param(
            "INSERT INTO topic (id, title, parent_topic_id, status)"
            f" VALUES ('{u(50)}', 't', '{MISSING}', 'active')",
            id="topic.parent_topic_id",
        ),
    ],
)
def test_foreign_keys_are_enforced(seeded: sqlite3.Connection, sql: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        seeded.execute(sql)


def test_cannot_delete_a_row_that_is_referenced(seeded: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        seeded.execute("DELETE FROM topic WHERE id = ?", (ID1,))


def test_every_foreign_key_column_has_an_index(db: Database) -> None:
    missing: list[str] = []
    for table in sorted(DESIGN_TABLES):
        pk = [r[1] for r in db.conn.execute(f"PRAGMA table_info({table})") if r[5]]
        leading = {pk[0]} if len(pk) == 1 else set()  # a single-column primary key is indexed
        for _, name, *_ in db.conn.execute(f"PRAGMA index_list({table})"):
            leading.add(db.conn.execute(f"PRAGMA index_info({name})").fetchone()[2])
        missing += [
            f"{table}.{fk[3]}"
            for fk in db.conn.execute(f"PRAGMA foreign_key_list({table})")
            if fk[3] not in leading and fk[2] not in ENUM_TABLES  # lookup tables are tiny
        ]
    assert missing == []


def test_next_recap_at_is_indexed(db: Database) -> None:
    rows = db.conn.execute("PRAGMA index_list(knowledge_state)").fetchall()
    leading = {db.conn.execute(f"PRAGMA index_info({r[1]})").fetchone()[2] for r in rows}
    assert "next_recap_at" in leading


# --- CLI --------------------------------------------------------------------------------------


def test_cli_db_migrate_then_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    first = runner.invoke(app, ["db", "migrate"])
    assert first.exit_code == 0, first.output
    assert "0001_init" in first.output
    assert (tmp_path / "deepdive.db").is_file()

    again = runner.invoke(app, ["db", "migrate"])
    assert again.exit_code == 0
    assert "up to date" in again.output

    info = runner.invoke(app, ["db", "info"])
    assert info.exit_code == 0, info.output
    assert str(tmp_path / "deepdive.db") in info.output
    assert "  0001_init (applied " in info.output
    for table in DESIGN_TABLES | {"question_fts"}:
        assert f"{table}: 0" in info.output


def test_cli_db_info_counts_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    runner.invoke(app, ["db", "migrate"])
    with Database(tmp_path / "deepdive.db") as db:
        add_topic(db.conn, 1)
        add_topic(db.conn, 2, parent=1)
    info = runner.invoke(app, ["db", "info"])
    assert "topic: 2" in info.output


def test_cli_db_info_without_a_database_says_to_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    result = runner.invoke(app, ["db", "info"])
    assert result.exit_code == 1
    assert "deepdive db migrate" in result.output
    assert not (tmp_path / "deepdive.db").exists()
