from datetime import UTC, datetime
from uuid import UUID

import pytest

from deepdive import clock
from deepdive.store.db import Database
from deepdive.store.errors import InvalidSourceError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store

SEEN = datetime(2026, 1, 1, tzinfo=UTC)


def _register(store: Store, **ids: str | None) -> UUID:
    return store.sources.register(
        url=ids.get("url"), doi=ids.get("doi"), kind="docs", tier=2, seen_at=SEEN
    ).id


def test_same_url_twice_returns_the_same_source(store: Store, db: Database) -> None:
    """Registering the same url twice returns the same source."""
    first = _register(store, url="https://example.com/a")
    assert _register(store, url="https://example.com/a") == first
    assert _register(store, url="https://example.com/b") != first
    count = db.conn.execute("SELECT COUNT(*) FROM source WHERE url = ?", ("https://example.com/a",))
    assert count.fetchone()[0] == 1


def test_same_doi_twice_and_mixed_identifiers_dedupe(store: Store) -> None:
    """Sources dedupe on doi and on mixed url/doi identifiers."""
    by_doi = _register(store, doi="10.1/x")
    assert _register(store, doi="10.1/x") == by_doi
    assert _register(store, url="https://example.com/p", doi="10.1/x") == by_doi
    by_url = _register(store, url="https://example.com/q")
    assert _register(store, url="https://example.com/q", doi="10.1/other") == by_url


def test_url_only_and_doi_only_sources(store: Store) -> None:
    """A source may have only a url or only a doi."""
    url_only = store.sources.register(url="https://e.com/u", kind="repo", tier=1, seen_at=SEEN)
    doi_only = store.sources.register(doi="10.1/d", kind="paper", tier=2, seen_at=SEEN)
    assert (url_only.doi, doi_only.url) == (None, None)
    assert (doi_only.kind, doi_only.tier, doi_only.first_seen_at) == ("paper", 2, SEEN)


def test_get_find_exists(store: Store, frozen_clock: object) -> None:
    """get, find and exists locate a registered source."""
    source = store.sources.register(url="https://e.com/u", kind="repo", tier=1, seen_at=clock.now())
    assert source.first_seen_at == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert store.sources.get(source.id) == source
    assert store.sources.find(url="https://e.com/u") == source
    assert store.sources.find(doi="10.1/none") is None
    assert store.sources.exists(source.id) is True
    assert store.sources.exists(new_id()) is False
    assert store.sources.get(new_id()) is None


@pytest.mark.parametrize("ids", [{}, {"url": ""}, {"url": None, "doi": ""}])
def test_a_source_needs_a_url_or_a_doi(
    store: Store, db: Database, ids: dict[str, str | None]
) -> None:
    """A source with neither url nor doi is refused and nothing is stored."""
    with pytest.raises(InvalidSourceError):
        _register(store, **ids)
    assert db.conn.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0
