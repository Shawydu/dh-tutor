-- 0007_edge_created_at: the digest lists cross-topic edges created since the last digest.
-- Edges written before this migration have no time (NULL) and are never "new".
ALTER TABLE question_edge ADD COLUMN created_at TIMESTAMP
    CHECK (created_at IS strftime('%Y-%m-%dT%H:%M:%SZ', created_at));
