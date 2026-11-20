"""On-disk JSON cache with a time-to-live, keyed by provider and query."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from deepdive import clock

TTL = timedelta(hours=24)


class Cache:
    """JSON files under `folder`, each fresh for `ttl`."""

    def __init__(self, folder: Path, ttl: timedelta = TTL) -> None:
        self.folder = folder
        self.ttl = ttl

    def _file(self, *key: str) -> Path:
        return self.folder / (hashlib.sha256("\0".join(key).encode()).hexdigest() + ".json")

    def get(self, *key: str) -> Any | None:
        path = self._file(*key)
        if not path.exists():
            return None
        age = clock.now().timestamp() - path.stat().st_mtime
        return json.loads(path.read_text("utf-8")) if age < self.ttl.total_seconds() else None

    def put(self, value: Any, *key: str) -> None:
        self._file(*key).write_text(json.dumps(value), "utf-8")
