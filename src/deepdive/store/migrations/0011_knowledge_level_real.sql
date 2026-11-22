-- 0011_knowledge_level_real: the update rule stores level as a weighted mean, so it is REAL.
CREATE TABLE knowledge_state_new (
    concept_id       UUID PRIMARY KEY REFERENCES concept (id)
                     CHECK (concept_id GLOB '????????-????-????-????-????????????'
                            AND concept_id NOT GLOB '*[^0-9a-f-]*'),
    level            REAL NOT NULL CHECK (level BETWEEN 0 AND 4),
    confidence       REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    stability        REAL NOT NULL,
    last_evidence_at TIMESTAMP CHECK (last_evidence_at IS strftime('%Y-%m-%dT%H:%M:%SZ', last_evidence_at)),
    next_recap_at    TIMESTAMP CHECK (next_recap_at IS strftime('%Y-%m-%dT%H:%M:%SZ', next_recap_at))
);

INSERT INTO knowledge_state_new SELECT * FROM knowledge_state;
DROP TABLE knowledge_state;
ALTER TABLE knowledge_state_new RENAME TO knowledge_state;
CREATE INDEX knowledge_state_next_recap_at ON knowledge_state (next_recap_at);
