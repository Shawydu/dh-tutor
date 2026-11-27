-- 0016_session_fetched_url: pages the agent opened with its built-in WebFetch, recorded by the
-- PreToolUse hook; source_register accepts them for that session even off the allowlist.
CREATE TABLE session_fetched_url (
    session_id UUID NOT NULL REFERENCES session (id),
    url        TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL CHECK (fetched_at IS strftime('%Y-%m-%dT%H:%M:%SZ', fetched_at)),
    PRIMARY KEY (session_id, url)
);
