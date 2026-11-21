"""What every search provider returns and implements."""

from collections.abc import Sequence
from datetime import date
from typing import Literal, Protocol

import httpx
from pydantic import AwareDatetime, BaseModel

Kind = Literal["repo", "issue", "release", "paper", "story", "comment"]
SNIPPET_MAX = 300

# Domain-pack source_tiers key for each result kind; the pack decides the tier number.
TIER_KEY: dict[Kind, str] = {
    "repo": "repo",
    "release": "repo",
    "issue": "discussion",
    "story": "discussion",
    "comment": "discussion",
    "paper": "paper",
}


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    published_at: AwareDatetime | None
    provider: str
    kind: Kind


class SearchProvider(Protocol):
    name: str

    # query: words every result must match; optional: words that rank results but may be missing
    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        optional: Sequence[str] = (),
        since: date | None,
        limit: int,
    ) -> list[SearchResult]: ...
