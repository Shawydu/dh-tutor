"""GitHub REST: repository and issue search, plus releases of one repo."""

from datetime import date
from typing import Any

import httpx

from deepdive.search.base import SNIPPET_MAX, SearchResult

_API = "https://api.github.com"


class GitHub:
    name = "github"

    def __init__(self, token: str | None = None) -> None:
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        resp = await client.get(f"{_API}{path}", params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def search(
        self, client: httpx.AsyncClient, query: str, *, since: date | None, limit: int
    ) -> list[SearchResult]:
        half = (limit + 1) // 2  # repos and issues share the limit
        when = f" pushed:>={since}" if since else ""
        repos = await self._get(
            client, "/search/repositories", {"q": query + when, "per_page": half}
        )
        when = f" updated:>={since}" if since else ""
        issues = await self._get(
            client, "/search/issues", {"q": f"{query} is:issue{when}", "per_page": half}
        )
        found = [
            SearchResult(
                title=r["full_name"],
                url=r["html_url"],
                snippet=(r["description"] or "")[:SNIPPET_MAX],
                published_at=r["created_at"],
                provider=self.name,
                kind="repo",
            )
            for r in repos["items"]
        ] + [
            SearchResult(
                title=i["title"],
                url=i["html_url"],
                snippet=(i["body"] or "")[:SNIPPET_MAX],
                published_at=i["created_at"],
                provider=self.name,
                kind="issue",
            )
            for i in issues["items"]
        ]
        return found[:limit]

    async def releases(
        self, client: httpx.AsyncClient, repo: str, *, limit: int = 5
    ) -> list[SearchResult]:
        """Latest releases of `repo` ("owner/name"); not part of the query search."""
        rows = await self._get(client, f"/repos/{repo}/releases", {"per_page": limit})
        return [
            SearchResult(
                title=r["name"] or r["tag_name"],
                url=r["html_url"],
                snippet=(r["body"] or "")[:SNIPPET_MAX],
                published_at=r["published_at"],
                provider=self.name,
                kind="release",
            )
            for r in rows
        ]
