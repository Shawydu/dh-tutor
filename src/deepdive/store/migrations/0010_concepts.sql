-- 0010_concepts: concept names are unique once normalised; an alias points a merged-away name at
-- the concept it became; claims carry concept tags too; a question tag's created_at lets the
-- digest list new concept connections (no rows existed before this migration).
CREATE UNIQUE INDEX concept_name ON concept (name);

CREATE TABLE concept_alias (
    alias      TEXT PRIMARY KEY,
    concept_id UUID NOT NULL REFERENCES concept (id)
);

CREATE INDEX concept_alias_concept_id ON concept_alias (concept_id);

CREATE TABLE claim_concept (
    claim_id   UUID NOT NULL REFERENCES claim (id),
    concept_id UUID NOT NULL REFERENCES concept (id),
    PRIMARY KEY (claim_id, concept_id)
);

CREATE INDEX claim_concept_concept_id ON claim_concept (concept_id);

ALTER TABLE question_concept ADD COLUMN created_at TIMESTAMP
    CHECK (created_at IS strftime('%Y-%m-%dT%H:%M:%SZ', created_at));
