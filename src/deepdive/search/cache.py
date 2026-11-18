"""On-disk JSON cache with a time-to-live, keyed by provider and query."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from deepdive import clock

TTL = timedelta(hours=24)


def _file(folder: Path, *key: str) -> Path:
    return folder / (hashlib.sha256("\0".join(key).encode()).hexdigest() + ".json")


def get(folder: Path, *key: str) -> Any | None:
    path = _file(folder, *key)
    if not path.exists():
        return None
    age = clock.now().timestamp() - path.stat().st_mtime
    return json.loads(path.read_text("utf-8")) if age < TTL.total_seconds() else None


def put(folder: Path, value: Any, *key: str) -> None:
    _file(folder, *key).write_text(json.dumps(value), "utf-8")
