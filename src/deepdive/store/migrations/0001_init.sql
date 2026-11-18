-- 0001_init: every table in docs/design.md "Data model", for all phases (v0 to v3).
-- This file was rewritten once, before it was ever applied, to tighten the column types (UUID ids,
-- TIMESTAMP instants, enum lookup tables) and to fold in the old 0002_session_attribution. From now on
-- it is never edited: add 0002_*.sql instead. The runner wraps a file in one transaction, so a
-- migration must not contain BEGIN/COMMIT outside trigger bodies.
--
-- Column types. SQLite has no native UUID, timestamp or enum types, so the schema declares them by
-- type name, enforces them with CHECKs and lookup tables, and store/db.py turns the declared names
-- into Python types (sqlite3 adapters and converters).
--   UUID       lowercase hyphenated UUIDv7 text (store/ids.py). Every `id` and `*_id` column. Each
--              single-column primary key carries the shape CHECK; foreign keys are covered by REFERENCES.
--   TIMESTAMP  UTC instant as 'YYYY-MM-DDTHH:MM:SSZ' text. Every `*_at` column, with a round-trip CHECK.
--   enum       a lookup table `<table>_<column>` (value TEXT PRIMARY KEY) seeded below and referenced by
--              the column. A new value is an INSERT in a later migration; a CHECK list could not be
--              changed without rebuilding the table. store/enums.py has one StrEnum per lookup table.
-- List-valued columns hold JSON arrays. Column names follow the design, including "order" on
-- agenda_item, which is an SQL keyword and must be quoted in queries.

-- Enum lookup tables and their values.
CREATE TABLE topic_status (value TEXT PRIMARY KEY);
INSERT INTO topic_status (value) VALUES ('scoping'), ('active'), ('paused'), ('finished');

CREATE TABLE agenda_item_status (value TEXT PRIMARY KEY);
INSERT INTO agenda_item_status (value) VALUES ('open'), ('done');

CREATE TABLE question_asker (value TEXT PRIMARY KEY);
INSERT INTO question_asker (value) VALUES ('user'), ('guide'), ('curious'), ('skeptic'), ('probe');

CREATE TABLE question_status (value TEXT PRIMARY KEY);
INSERT INTO question_status (value) VALUES ('open'), ('answered'), ('partial'), ('parked');

CREATE TABLE question_edge_relation (value TEXT PRIMARY KEY);
INSERT INTO question_edge_relation (value) VALUES ('same'), ('narrower'), ('broader'), ('aspect'), ('builds_on'), ('clashes'), ('unrelated');

CREATE TABLE claim_status (value TEXT PRIMARY KEY);
INSERT INTO claim_status (value) VALUES ('open'), ('established'), ('weakened');

CREATE TABLE evidence_stance (value TEXT PRIMARY KEY);
INSERT INTO evidence_stance (value) VALUES ('supports'), ('weakens');

CREATE TABLE probe_run_status (value TEXT PRIMARY KEY);
INSERT INTO probe_run_status (value) VALUES ('running'), ('ok'), ('budget_exhausted'), ('failed');

CREATE TABLE discovery_effect (value TEXT PRIMARY KEY);
INSERT INTO discovery_effect (value) VALUES ('answers'), ('supports'), ('weakens'), ('new_thread');

CREATE TABLE knowledge_evidence_kind (value TEXT PRIMARY KEY);
INSERT INTO knowledge_evidence_kind (value) VALUES ('answered_student_q'), ('repeat_question'), ('explained_back'), ('poc_completed'), ('recap_check'), ('self_rating');

CREATE TABLE knowledge_evidence_grade (value TEXT PRIMARY KEY);
INSERT INTO knowledge_evidence_grade (value) VALUES ('wrong'), ('partial'), ('correct'), ('insightful');

CREATE TABLE topic (
    id              UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    title           TEXT NOT NULL,
    parent_topic_id UUID REFERENCES topic (id),
    status          TEXT NOT NULL REFERENCES topic_status (value),
    pinned          INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    CHECK (parent_topic_id IS NULL OR parent_topic_id <> id)
);

-- Child topics are one level deep: the store enforces it (invariant 4).
CREATE TRIGGER topic_one_level_insert BEFORE INSERT ON topic
WHEN NEW.parent_topic_id IS NOT NULL
 AND (SELECT parent_topic_id FROM topic WHERE id = NEW.parent_topic_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'child topics are one level deep: the parent is itself a child');
END;

-- Re-parenting must keep the rule: not under a child, and not while it has children of its own.
CREATE TRIGGER topic_one_level_update BEFORE UPDATE OF parent_topic_id ON topic
WHEN NEW.parent_topic_id IS NOT NULL
 AND ((SELECT parent_topic_id FROM topic WHERE id = NEW.parent_topic_id) IS NOT NULL
      OR EXISTS (SELECT 1 FROM topic WHERE parent_topic_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'child topics are one level deep: re-parenting would create a grandchild');
END;

CREATE INDEX topic_parent_topic_id ON topic (parent_topic_id);

CREATE TABLE charter (
    topic_id       UUID NOT NULL REFERENCES topic (id),
    version        INTEGER NOT NULL,
    core_questions TEXT NOT NULL CHECK (json_valid(core_questions)),
    in_scope       TEXT NOT NULL CHECK (json_valid(in_scope)),
    parked         TEXT NOT NULL CHECK (json_valid(parked)),
    done_when      TEXT NOT NULL,
    session_id     UUID REFERENCES session (id),
    PRIMARY KEY (topic_id, version)
);

CREATE INDEX charter_session_id ON charter (session_id);

CREATE TABLE session (
    id         UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id   UUID NOT NULL REFERENCES topic (id),
    started_at TIMESTAMP NOT NULL CHECK (started_at IS strftime('%Y-%m-%dT%H:%M:%SZ', started_at)),
    ended_at   TIMESTAMP CHECK (ended_at IS strftime('%Y-%m-%dT%H:%M:%SZ', ended_at)),
    bookmark   TEXT,
    summary    TEXT
);

CREATE INDEX session_topic_id ON session (topic_id);

CREATE TABLE agenda_item (
    id         UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id   UUID NOT NULL REFERENCES topic (id),
    session_id UUID REFERENCES session (id),
    facet      TEXT NOT NULL,
    status     TEXT NOT NULL REFERENCES agenda_item_status (value),
    "order"    INTEGER NOT NULL
);

CREATE INDEX agenda_item_topic_id ON agenda_item (topic_id, "order");
CREATE INDEX agenda_item_session_id ON agenda_item (session_id);

CREATE TABLE question (
    id             UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id       UUID NOT NULL REFERENCES topic (id),
    session_id     UUID REFERENCES session (id),
    asker          TEXT NOT NULL REFERENCES question_asker (value),
    raw_text       TEXT NOT NULL,
    clean_text     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' REFERENCES question_status (value),
    answer_summary TEXT,
    embedding      BLOB
);

CREATE INDEX question_topic_id ON question (topic_id);
CREATE INDEX question_session_id ON question (session_id);

-- Keyword search over questions. A normal FTS5 table that keeps its own copy of the text: an
-- external-content table would key on rowid, and a table with a UUID primary key has an unstable
-- implicit rowid (VACUUM may renumber it). The triggers below keep it in step, keyed on question_id.
-- The porter stemmer lets "thread" match "threads".
-- shortcut: delete/update scan the FTS table (question_id is unindexed), fine for thousands of questions; upgrade if it ever matters
CREATE VIRTUAL TABLE question_fts USING fts5 (
    question_id UNINDEXED,
    clean_text,
    raw_text,
    tokenize = 'porter unicode61'
);

CREATE TRIGGER question_fts_insert AFTER INSERT ON question
BEGIN
    INSERT INTO question_fts (question_id, clean_text, raw_text)
    VALUES (NEW.id, NEW.clean_text, NEW.raw_text);
END;

CREATE TRIGGER question_fts_delete AFTER DELETE ON question
BEGIN
    DELETE FROM question_fts WHERE question_id = OLD.id;
END;

CREATE TRIGGER question_fts_update AFTER UPDATE OF clean_text, raw_text ON question
BEGIN
    DELETE FROM question_fts WHERE question_id = OLD.id;
    INSERT INTO question_fts (question_id, clean_text, raw_text)
    VALUES (NEW.id, NEW.clean_text, NEW.raw_text);
END;

CREATE TABLE question_edge (
    from_id    UUID NOT NULL REFERENCES question (id),
    to_id      UUID NOT NULL REFERENCES question (id),
    relation   TEXT NOT NULL REFERENCES question_edge_relation (value),
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    classifier TEXT, -- a provider name, an open set: not an enum
    PRIMARY KEY (from_id, to_id)
);

CREATE INDEX question_edge_to_id ON question_edge (to_id);

CREATE TABLE concept (
    id                UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    name              TEXT NOT NULL,
    domain            TEXT, -- a domain pack's name, an open set: not an enum
    parent_concept_id UUID REFERENCES concept (id)
);

CREATE INDEX concept_parent_concept_id ON concept (parent_concept_id);

CREATE TABLE question_concept (
    question_id UUID NOT NULL REFERENCES question (id),
    concept_id  UUID NOT NULL REFERENCES concept (id),
    PRIMARY KEY (question_id, concept_id)
);

CREATE INDEX question_concept_concept_id ON question_concept (concept_id);

CREATE TABLE claim (
    id         UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id   UUID NOT NULL REFERENCES topic (id),
    session_id UUID REFERENCES session (id),
    text       TEXT NOT NULL,
    status     TEXT NOT NULL REFERENCES claim_status (value)
);

CREATE INDEX claim_topic_id ON claim (topic_id);
CREATE INDEX claim_session_id ON claim (session_id);

-- UNIQUE url and doi make "drop sources already seen" a store rule; NULLs are allowed and distinct.
-- tier is the domain pack's number, 1 = most trusted.
CREATE TABLE source (
    id            UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    url           TEXT UNIQUE,
    doi           TEXT UNIQUE,
    kind          TEXT NOT NULL, -- the domain pack defines the kinds, an open set: not an enum
    tier          INTEGER NOT NULL,
    first_seen_at TIMESTAMP NOT NULL CHECK (first_seen_at IS strftime('%Y-%m-%dT%H:%M:%SZ', first_seen_at)),
    session_id    UUID REFERENCES session (id)
);

CREATE INDEX source_session_id ON source (session_id);

-- Evidence must cite a source that exists (invariant 2).
CREATE TABLE evidence (
    id              UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    claim_id        UUID NOT NULL REFERENCES claim (id),
    source_id       UUID NOT NULL REFERENCES source (id),
    session_id      UUID REFERENCES session (id),
    stance          TEXT NOT NULL REFERENCES evidence_stance (value),
    excerpt_summary TEXT
);

CREATE INDEX evidence_claim_id ON evidence (claim_id);
CREATE INDEX evidence_source_id ON evidence (source_id);
CREATE INDEX evidence_session_id ON evidence (session_id);

CREATE TABLE probe_run (
    id            UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    started_at    TIMESTAMP NOT NULL CHECK (started_at IS strftime('%Y-%m-%dT%H:%M:%SZ', started_at)),
    topics        TEXT NOT NULL CHECK (json_valid(topics)),
    searches_used INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL REFERENCES probe_run_status (value)
);

-- target_id points at a question or a claim; the design names no type column, so none here.
CREATE TABLE discovery (
    id           UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id     UUID NOT NULL REFERENCES topic (id),
    probe_run_id UUID NOT NULL REFERENCES probe_run (id),
    source_id    UUID NOT NULL REFERENCES source (id),
    target_id    UUID,
    effect       TEXT NOT NULL REFERENCES discovery_effect (value),
    relevance    REAL NOT NULL,
    read_at      TIMESTAMP CHECK (read_at IS strftime('%Y-%m-%dT%H:%M:%SZ', read_at))
);

CREATE INDEX discovery_topic_id ON discovery (topic_id);
CREATE INDEX discovery_probe_run_id ON discovery (probe_run_id);
CREATE INDEX discovery_source_id ON discovery (source_id);

CREATE TABLE rubric (
    question_id    UUID PRIMARY KEY REFERENCES question (id)
                   CHECK (question_id GLOB '????????-????-????-????-????????????'
                          AND question_id NOT GLOB '*[^0-9a-f-]*'),
    key_points     TEXT NOT NULL CHECK (json_valid(key_points)),
    misconceptions TEXT NOT NULL CHECK (json_valid(misconceptions))
);

CREATE TABLE knowledge_state (
    concept_id       UUID PRIMARY KEY REFERENCES concept (id)
                     CHECK (concept_id GLOB '????????-????-????-????-????????????'
                            AND concept_id NOT GLOB '*[^0-9a-f-]*'),
    level            INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
    confidence       REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    stability        REAL NOT NULL,
    last_evidence_at TIMESTAMP CHECK (last_evidence_at IS strftime('%Y-%m-%dT%H:%M:%SZ', last_evidence_at)),
    next_recap_at    TIMESTAMP CHECK (next_recap_at IS strftime('%Y-%m-%dT%H:%M:%SZ', next_recap_at))
);

CREATE INDEX knowledge_state_next_recap_at ON knowledge_state (next_recap_at);

-- A self-rating stores the level you claim and no grade; every other kind may carry a grade.
-- level is not in the design's column list; the task requires it ("self-ratings store a level").
CREATE TABLE knowledge_evidence (
    id                UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    concept_id        UUID NOT NULL REFERENCES concept (id),
    session_id        UUID REFERENCES session (id),
    question_id       UUID REFERENCES question (id),
    kind              TEXT NOT NULL REFERENCES knowledge_evidence_kind (value),
    grade             TEXT REFERENCES knowledge_evidence_grade (value),
    level             INTEGER CHECK (level BETWEEN 0 AND 4),
    grader            TEXT, -- a provider name, an open set: not an enum
    grader_confidence REAL CHECK (grader_confidence BETWEEN 0 AND 1),
    weight            REAL NOT NULL,
    created_at        TIMESTAMP NOT NULL CHECK (created_at IS strftime('%Y-%m-%dT%H:%M:%SZ', created_at)),
    CHECK (kind <> 'self_rating' OR (grade IS NULL AND level IS NOT NULL))
);

CREATE INDEX knowledge_evidence_concept_id ON knowledge_evidence (concept_id);
CREATE INDEX knowledge_evidence_session_id ON knowledge_evidence (session_id);
CREATE INDEX knowledge_evidence_question_id ON knowledge_evidence (question_id);

CREATE TABLE poc_project (
    id             UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id       UUID NOT NULL REFERENCES topic (id),
    path           TEXT NOT NULL,
    question_ids   TEXT NOT NULL CHECK (json_valid(question_ids)),
    status         TEXT NOT NULL, -- the value set is not defined until V3-02: make it an enum there
    result_summary TEXT
);

CREATE INDEX poc_project_topic_id ON poc_project (topic_id);
