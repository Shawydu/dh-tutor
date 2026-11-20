"""What every tool module shares: the open database, the paths, the clock."""

from dataclasses import dataclass, field
from datetime import datetime

from deepdive import clock
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.repos import Store


@dataclass
class LedgerContext:
    db: Database
    paths: Paths
    store: Store = field(init=False)

    def __post_init__(self) -> None:
        self.store = Store(self.db)

    def now(self) -> datetime:
        """Time for `at` / `seen_at` parameters (the store never reads the clock)."""
        return clock.now()
