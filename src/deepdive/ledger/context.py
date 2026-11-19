"""What every tool module shares: the open database, the paths, the clock."""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from deepdive import clock
from deepdive.paths import Paths
from deepdive.store.models import Session, Topic
from deepdive.store.repos import Store


@dataclass
class LedgerContext:
    conn: sqlite3.Connection
    paths: Paths
    store: Store = field(init=False)

    def __post_init__(self) -> None:
        self.store = Store(self.conn)

    def now(self) -> datetime:
        """Time for `at` / `seen_at` parameters (the store never reads the clock)."""
        return clock.now()

    def require_topic(self, topic_id: UUID) -> Topic:
        topic = self.store.topics.get(topic_id)
        if topic is None:
            raise self.store.topics.not_found(topic_id)
        return topic

    def require_session(self, session_id: UUID) -> Session:
        session = self.store.sessions.get(session_id)
        if session is None:
            raise self.store.sessions.not_found(session_id)
        return session
