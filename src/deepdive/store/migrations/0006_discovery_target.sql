-- 0006_discovery_target: a discovery names what it is about (a question or a claim) and carries
-- the probe's two-sentence summary. Nothing wrote to discovery before this, so the table is rebuilt.
DROP TABLE discovery;

CREATE TABLE discovery_target_type (value TEXT PRIMARY KEY);
INSERT INTO discovery_target_type (value) VALUES ('question'), ('claim');

-- target_id points at a question or a claim, so no foreign key; DiscoveryRepo checks it.
CREATE TABLE discovery (
    id           UUID PRIMARY KEY CHECK (id GLOB '????????-????-????-????-????????????' AND id NOT GLOB '*[^0-9a-f-]*'),
    topic_id     UUID NOT NULL REFERENCES topic (id),
    probe_run_id UUID NOT NULL REFERENCES probe_run (id),
    source_id    UUID NOT NULL REFERENCES source (id),
    target_type  TEXT NOT NULL REFERENCES discovery_target_type (value),
    target_id    UUID NOT NULL,
    effect       TEXT NOT NULL REFERENCES discovery_effect (value),
    relevance    REAL NOT NULL,
    summary      TEXT NOT NULL,
    read_at      TIMESTAMP CHECK (read_at IS strftime('%Y-%m-%dT%H:%M:%SZ', read_at))
);

-- What a probe run has spent on each topic. The engine enforces the per-topic limits on these
-- counters, so a restarted server cannot reset a budget. Outcomes stay in probe_run.topics.
CREATE TABLE probe_topic (
    probe_run_id  UUID NOT NULL REFERENCES probe_run (id),
    topic_id      UUID NOT NULL REFERENCES topic (id),
    searches_used INTEGER NOT NULL DEFAULT 0,
    fetches_used  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (probe_run_id, topic_id)
);

CREATE INDEX probe_topic_topic_id ON probe_topic (topic_id);
CREATE INDEX discovery_topic_id ON discovery (topic_id);
CREATE INDEX discovery_probe_run_id ON discovery (probe_run_id);
CREATE INDEX discovery_source_id ON discovery (source_id);
