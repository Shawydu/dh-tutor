-- 0015_session_searches_used: interactive searches spent in a session, shared by the engine's
-- search tool and the agent tool's built-in search hook (V3-05).
ALTER TABLE session ADD COLUMN searches_used INTEGER NOT NULL DEFAULT 0 CHECK (searches_used >= 0);
