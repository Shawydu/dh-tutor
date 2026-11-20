-- 0005_agent_session: maps an agent tool's session id (a Claude Code session UUID) to the engine
-- session it is working in, so the user-prompt hook can find the active topic.
CREATE TABLE agent_session (
    agent_session_id UUID PRIMARY KEY CHECK (agent_session_id GLOB '????????-????-????-????-????????????' AND agent_session_id NOT GLOB '*[^0-9a-f-]*'),
    session_id       UUID NOT NULL REFERENCES session (id),
    attached_at      TIMESTAMP NOT NULL CHECK (attached_at IS strftime('%Y-%m-%dT%H:%M:%SZ', attached_at))
);
CREATE INDEX agent_session_session ON agent_session (session_id);
