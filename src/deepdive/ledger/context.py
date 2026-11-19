"""What every tool module shares: the open database, the paths, the clock."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from deepdive import clock
from deepdive.paths import Paths
from deepdive.store.errors import SessionNotFoundError, TopicNotFoundError
from deepdive.store.models import Session, Topic
from deepdive.store.repos import sessions, topics


@dataclass
class LedgerContext:
    conn: sqlite3.Connection
    paths: Paths

    def now(self) -> datetime:
        """Time for `at` / `seen_at` parameters (the store never reads the clock)."""
        return clock.now()

    def require_topic(self, topic_id: UUID) -> Topic:
        topic = topics.get(self.conn, topic_id)
        if topic is None:
            raise TopicNotFoundError(topic_id)
        return topic

    def require_session(self, session_id: UUID) -> Session:
        session = sessions.get(self.conn, session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session
