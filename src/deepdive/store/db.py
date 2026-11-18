"""SQLite connection and the migration runner. Imports nothing else from deepdive."""

import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

_MIGRATION_NAME = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               CHECK (applied_at IS strftime('%Y-%m-%dT%H:%M:%SZ', applied_at))
)
"""


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime: the database stores aware UTC instants")
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _convert_timestamp(value: bytes) -> datetime:
    return datetime.strptime(value.decode(), _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


# The schema declares UUID and TIMESTAMP columns; PARSE_DECLTYPES returns them as native types.
# Registering our own "timestamp" converter replaces the stdlib default (deprecated since 3.12).
sqlite3.register_adapter(uuid.UUID, str)
sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("UUID", lambda value: uuid.UUID(value.decode()))
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database with foreign keys on, WAL journaling and a 5 s busy timeout.

    Columns declared UUID and TIMESTAMP are returned as `uuid.UUID` and aware UTC `datetime`.
    """
    # autocommit=True: sqlite3 never opens a transaction by itself, so `transaction()` owns every
    # BEGIN/COMMIT and executescript() cannot commit half a migration behind our back.
    conn = sqlite3.connect(path, autocommit=True, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One write transaction: takes the write lock up front, commits on success, else rolls back."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection, source: Traversable | None = None) -> list[str]:
    """Apply every pending `NNNN_name.sql` in order, each in its own transaction.

    Returns the names applied (empty when up to date). `source` defaults to the packaged
    `deepdive.store.migrations`; tests pass a folder.
    """
    source = source or resources.files("deepdive.store.migrations")
    files: dict[int, Traversable] = {}
    for entry in source.iterdir():
        if match := _MIGRATION_NAME.fullmatch(entry.name):
            version = int(match.group(1))
            if version in files:
                raise ValueError(f"two migrations share version {version:04d}")
            files[version] = entry
    conn.execute(_SCHEMA_MIGRATIONS)
    applied: list[str] = []
    for version, entry in sorted(files.items()):
        with transaction(conn):
            # checked inside the write lock, so two processes migrating at once apply it once
            if conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
            ).fetchone():
                continue
            conn.executescript(entry.read_text("utf-8"))
            name = entry.name.removesuffix(".sql")
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name)
            )
            applied.append(name)
    return applied


def applied_migrations(conn: sqlite3.Connection) -> list[tuple[str, datetime]]:
    """(name, applied_at) of every applied migration, oldest first.

    Raises sqlite3.OperationalError when the database was never migrated.
    """
    rows = conn.execute("SELECT name, applied_at FROM schema_migrations ORDER BY version")
    return [(name, applied_at) for name, applied_at in rows]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row count per user table, by name; FTS shadow tables are left out."""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM pragma_table_list WHERE schema='main' "
            "AND type IN ('table', 'virtual') "
            "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
        )
    ]
    return {name: conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names}
