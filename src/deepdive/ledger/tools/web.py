from datetime import date
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from deepdive.config import Config, Secrets
from deepdive.domain_packs import DomainPack
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Limit, Title, Url
from deepdive.search import cache
from deepdive.search.arxiv import Arxiv
from deepdive.search.base import TIER_KEY, SearchProvider, SearchResult
from deepdive.search.budget import Budget
from deepdive.search.fetch import FetchError, fetch_text
from deepdive.search.github import GitHub
from deepdive.search.hn import HackerNews


def register(
    server: MCPServer[None],
    ctx: LedgerContext,
    config: Config,
    pack: DomainPack,
    secrets: Secrets,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    budget = Budget(config.search.session_budget)
    registry: dict[str, SearchProvider] = {
        p.name: p for p in (GitHub(secrets.github_token), Arxiv(), HackerNews())
    }
    enabled = [n for n in registry if n in config.search.apis and n in pack.providers]

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport, timeout=20, headers={"User-Agent": "deepdive/0"}
        )

    def source_id(url: str, tier_key: str, session_id: Id | None) -> str:
        row = ctx.store.sources.register(
            url=url,
            kind=tier_key,
            tier=pack.source_tiers[tier_key],
            seen_at=ctx.now(),
            session_id=session_id,
        )
        return str(row.id)

    @server.tool()
    async def search(
        query: Title,
        providers: list[str] | None = None,
        since: date | None = None,
        limit: Limit = 10,
        session_id: Id | None = None,
    ) -> dict[str, Any]:
        """Search GitHub, arXiv and Hacker News; each result carries a citable source_id.

        providers picks from the enabled providers (default all). Each call costs one search
        from the session budget; at zero the answer is {"error": "budget_exhausted"}.
        """
        chosen = providers or enabled
        if unknown := [n for n in chosen if n not in enabled]:
            raise InvalidInputError(f"unknown providers {unknown}; enabled: {enabled}")
        if session_id:
            ctx.require_session(session_id)
        run = str(session_id or "interactive")
        if not budget.spend(run):
            return {"error": "budget_exhausted", "detail": "no searches left in this session"}
        results: list[SearchResult] = []
        errors: dict[str, str] = {}
        async with client() as http:
            for name in chosen:
                key = (name, query, str(since), str(limit))
                hit = cache.get(ctx.paths.cache, *key)
                try:
                    if hit is None:
                        found = await registry[name].search(http, query, since=since, limit=limit)
                        cache.put(ctx.paths.cache, [r.model_dump(mode="json") for r in found], *key)
                    else:
                        found = [SearchResult.model_validate(r) for r in hit]
                except httpx.HTTPError as err:
                    errors[name] = type(err).__name__  # never the message: it may echo the URL
                    continue
                results += found
        out = [
            {
                **r.model_dump(mode="json"),
                "source_id": source_id(r.url, TIER_KEY[r.kind], session_id),
            }
            for r in results
        ]
        return {"results": out, "errors": errors, "budget_remaining": budget.remaining(run)}

    @server.tool()
    async def fetch(url: Url, session_id: Id | None = None) -> dict[str, Any]:
        """Fetch a page from an allowlisted host as text (truncated, with `truncated: true`)."""
        if session_id:
            ctx.require_session(session_id)
        try:
            async with client() as http:
                text, truncated = await fetch_text(
                    http, url, pack.fetch_allowlist, config.search.fetch_max_chars
                )
        except FetchError as err:
            return {"error": err.code, "detail": str(err)}
        host = (httpx.URL(url).host).lower()
        key = (
            "paper" if host.endswith("arxiv.org") else "repo" if "github" in host else "discussion"
        )
        return {
            "source_id": source_id(url, key, session_id),
            "url": url,
            "text": text,
            "truncated": truncated,
        }
