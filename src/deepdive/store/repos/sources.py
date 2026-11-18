import sqlite3
from datetime import datetime
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.errors import InvalidSourceError
from deepdive.store.ids import new_id
from deepdive.store.models import Source
from deepdive.store.repos._common import check_session, one


def find(
    conn: sqlite3.Connection, *, url: str | None = None, doi: str | None = None
) -> Source | None:
    """The source already registered under this URL, else under this DOI."""
    found = one(conn, Source, "source", "WHERE url = ?", (url,)) if url else None
    return found or (one(conn, Source, "source", "WHERE doi = ?", (doi,)) if doi else None)


def register(
    conn: sqlite3.Connection,
    *,
    url: str | None = None,
    doi: str | None = None,
    kind: str,
    tier: int,
    seen_at: datetime,
    session_id: UUID | None = None,
) -> Source:
    """Return the source for this URL or DOI, creating it on first sight.

    `session_id` is the session that first registered it; an existing source keeps its own.
    """
    if not url and not doi:
        raise InvalidSourceError("a source needs a url or a doi")
    with transaction(conn):  # lookup and insert under one write lock, so two writers agree
        check_session(conn, session_id)
        existing = find(conn, url=url, doi=doi)
        if existing:
            return existing
        source_id = new_id()
        conn.execute(
            "INSERT INTO source (id, url, doi, kind, tier, first_seen_at, session_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, url or None, doi or None, kind, tier, seen_at, session_id),
        )
    source = get(conn, source_id)
    assert source is not None
    return source


def get(conn: sqlite3.Connection, source_id: UUID) -> Source | None:
    return one(conn, Source, "source", "WHERE id = ?", (source_id,))


def exists(conn: sqlite3.Connection, source_id: UUID) -> bool:
    return conn.execute("SELECT 1 FROM source WHERE id = ?", (source_id,)).fetchone() is not None
