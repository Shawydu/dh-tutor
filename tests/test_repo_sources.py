import sqlite3
from datetime import UTC, datetime
from uuid import UUID

import pytest

from deepdive import clock
from deepdive.store.errors import InvalidSourceError
from deepdive.store.ids import new_id
from deepdive.store.repos import sources

SEEN = datetime(2026, 1, 1, tzinfo=UTC)


def _register(db: sqlite3.Connection, **ids: str | None) -> UUID:
    return sources.register(
        db, url=ids.get("url"), doi=ids.get("doi"), kind="docs", tier=2, seen_at=SEEN
    ).id


def test_same_url_twice_returns_the_same_source(db: sqlite3.Connection) -> None:
    first = _register(db, url="https://example.com/a")
    assert _register(db, url="https://example.com/a") == first
    assert _register(db, url="https://example.com/b") != first
    assert db.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 2


def test_same_doi_twice_and_mixed_identifiers_dedupe(db: sqlite3.Connection) -> None:
    by_doi = _register(db, doi="10.1/x")
    assert _register(db, doi="10.1/x") == by_doi
    assert _register(db, url="https://example.com/p", doi="10.1/x") == by_doi
    by_url = _register(db, url="https://example.com/q")
    assert _register(db, url="https://example.com/q", doi="10.1/other") == by_url


def test_url_only_and_doi_only_sources(db: sqlite3.Connection) -> None:
    url_only = sources.register(db, url="https://e.com/u", kind="repo", tier=1, seen_at=SEEN)
    doi_only = sources.register(db, doi="10.1/d", kind="paper", tier=2, seen_at=SEEN)
    assert (url_only.doi, doi_only.url) == (None, None)
    assert (doi_only.kind, doi_only.tier, doi_only.first_seen_at) == ("paper", 2, SEEN)


def test_get_find_exists(db: sqlite3.Connection, frozen_clock: object) -> None:
    source = sources.register(db, url="https://e.com/u", kind="repo", tier=1, seen_at=clock.now())
    assert source.first_seen_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert sources.get(db, source.id) == source
    assert sources.find(db, url="https://e.com/u") == source
    assert sources.find(db, doi="10.1/none") is None
    assert sources.exists(db, source.id) is True
    assert sources.exists(db, new_id()) is False
    assert sources.get(db, new_id()) is None


@pytest.mark.parametrize("ids", [{}, {"url": ""}, {"url": None, "doi": ""}])
def test_a_source_needs_a_url_or_a_doi(db: sqlite3.Connection, ids: dict[str, str]) -> None:
    with pytest.raises(InvalidSourceError):
        _register(db, **ids)
    assert db.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0
