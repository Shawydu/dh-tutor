from datetime import datetime
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.errors import InvalidSourceError, SourceNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Source
from deepdive.store.repos._common import IdRepo


class SourceRepo(IdRepo[Source]):
    table = "source"
    model = Source
    not_found = SourceNotFoundError

    def find(self, *, url: str | None = None, doi: str | None = None) -> Source | None:
        """The source already registered under this URL, else under this DOI."""
        found = self._one("WHERE url = ?", (url,)) if url else None
        return found or (self._one("WHERE doi = ?", (doi,)) if doi else None)

    def register(
        self,
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
        with transaction(self.conn):  # lookup and insert under one write lock: writers agree
            self._check_session(session_id)
            existing = self.find(url=url, doi=doi)
            if existing:
                return existing
            source_id = new_id()
            self.conn.execute(
                "INSERT INTO source (id, url, doi, kind, tier, first_seen_at, session_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source_id, url or None, doi or None, kind, tier, seen_at, session_id),
            )
        source = self.get(source_id)
        assert source is not None
        return source
