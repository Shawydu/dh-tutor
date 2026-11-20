-- 0004_edge_repeat: a user's repeated question is a teaching signal. The matcher marks the edge
-- until v2 records it as knowledge evidence.
ALTER TABLE question_edge ADD COLUMN repeat INTEGER NOT NULL DEFAULT 0 CHECK (repeat IN (0, 1));
