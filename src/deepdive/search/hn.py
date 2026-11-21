"""Hacker News via the Algolia search API: stories and comments."""

import html
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

import httpx

from deepdive.search.base import SNIPPET_MAX, SearchResult


class HackerNews:
    name = "hn"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        optional: Sequence[str] = (),
        since: date | None,
        limit: int,
    ) -> list[SearchResult]:
        words = " ".join(optional)
        params: dict[str, str | int] = {
            "query": f"{query} {words}".strip(),
            "tags": "(story,comment)",
            "hitsPerPage": limit,
        }
        if words:
            params["optionalWords"] = words  # Algolia ANDs every word otherwise
        if since:
            stamp = int(datetime.combine(since, time(), UTC).timestamp())
            params["numericFilters"] = f"created_at_i>={stamp}"
        resp = await client.get("https://hn.algolia.com/api/v1/search", params=params)
        resp.raise_for_status()
        found: list[SearchResult] = []
        for hit in resp.json()["hits"]:
            is_comment = "comment" in hit["_tags"]
            item = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            text = hit["comment_text"] if is_comment else (hit.get("story_text") or "")
            found.append(
                SearchResult(
                    title=(hit["story_title"] if is_comment else hit["title"]) or "(untitled)",
                    url=item if is_comment else hit.get("url") or item,
                    snippet=html.unescape(re.sub(r"<[^>]+>", " ", text or ""))[:SNIPPET_MAX],
                    published_at=hit["created_at"],
                    provider=self.name,
                    kind="comment" if is_comment else "story",
                )
            )
        return found
