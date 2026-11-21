-- 0009_charter_search_terms: the topic words a probe search must contain (a JSON list; empty = use
-- the topic title's words).
ALTER TABLE charter ADD COLUMN search_terms TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(search_terms));
