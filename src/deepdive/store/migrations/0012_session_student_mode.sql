-- 0012_session_student_mode: which student personas the guide calls at checkpoints (V2-04).
-- SQLite refuses ADD COLUMN ... REFERENCES with a non-NULL default on a non-empty table, so the
-- session table is rebuilt (Database.migrate runs with foreign keys off and checks them after).
CREATE TABLE session_student_mode (value TEXT PRIMARY KEY);
INSERT INTO session_student_mode (value) VALUES ('off'), ('curious'), ('skeptic'), ('both');

CREATE TABLE session_new (
    id           UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id     UUID NOT NULL REFERENCES topic (id),
    started_at   TIMESTAMP NOT NULL CHECK (started_at IS strftime('%Y-%m-%dT%H:%M:%SZ', started_at)),
    ended_at     TIMESTAMP CHECK (ended_at IS strftime('%Y-%m-%dT%H:%M:%SZ', ended_at)),
    bookmark     TEXT,
    summary      TEXT,
    student_mode TEXT NOT NULL DEFAULT 'both' REFERENCES session_student_mode (value)
);
INSERT INTO session_new (id, topic_id, started_at, ended_at, bookmark, summary)
    SELECT id, topic_id, started_at, ended_at, bookmark, summary FROM session;
DROP TABLE session;
ALTER TABLE session_new RENAME TO session;
CREATE INDEX session_topic_id ON session (topic_id);
