"""What every tool module shares: the open database, the paths, the clock."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from deepdive import clock
from deepdive.knowledge.store import KnowledgeStore, SqliteKnowledgeStore
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.repos import Store


@dataclass(frozen=True)
class ProbeScope:
    """A headless probe's server serves one topic of one probe run (budget and discoveries)."""

    probe_run_id: UUID
    topic_id: UUID


@dataclass
class LedgerContext:
    db: Database
    paths: Paths
    probe: ProbeScope | None = None
    store: Store = field(init=False)
    knowledge: KnowledgeStore = field(init=False)

    def __post_init__(self) -> None:
        self.store = Store(self.db)
        self.knowledge = SqliteKnowledgeStore(self.db)

    def now(self) -> datetime:
        """Time for `at` / `seen_at` parameters (the store never reads the clock)."""
        return clock.now()
