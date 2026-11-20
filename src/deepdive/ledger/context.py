"""What every tool module shares: the open database, the paths, the clock."""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from deepdive import clock
from deepdive.paths import Paths
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
