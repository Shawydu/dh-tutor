"""arXiv Atom API, restricted to cs.* categories."""

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import date, datetime

import httpx

from deepdive.search.base import SNIPPET_MAX, SearchResult

_NS = {"a": "http://www.w3.org/2005/Atom"}


class Arxiv:
    name = "arxiv"

    async def search(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        optional: Sequence[str] = (),
        since: date | None,
        limit: int,
    ) -> list[SearchResult]:
        terms = re.findall(r"\w+", query)  # words only: no arXiv query syntax from callers
        extra = [t for w in optional for t in re.findall(r"\w+", w)]
        if not terms and not extra:
            return []
        parts = [f"all:{t}" for t in terms]
        if extra:  # bare words are OR'ed by arXiv anyway; the group just keeps `query` required
            parts.append("(" + " OR ".join(f"all:{t}" for t in extra) + ")")
        q = " AND ".join([*parts, "cat:cs.*"])
        if since:
            q += f" AND submittedDate:[{since:%Y%m%d}0000 TO 999912312359]"
        resp = await client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": q, "max_results": limit, "sortBy": "relevance"},
        )
        resp.raise_for_status()
        # shortcut: stdlib XML parser (arXiv is allowlisted), use defusedxml if hosts widen
        root = ET.fromstring(resp.text)
        return [
            SearchResult(
                title=" ".join((e.findtext("a:title", "", _NS)).split()),
                url=e.findtext("a:id", "", _NS).replace("http://", "https://", 1),
                snippet=" ".join(e.findtext("a:summary", "", _NS).split())[:SNIPPET_MAX],
                published_at=datetime.fromisoformat(pub)
                if (pub := e.findtext("a:published", "", _NS))
                else None,
                provider=self.name,
                kind="paper",
            )
            for e in root.findall("a:entry", _NS)
        ]
