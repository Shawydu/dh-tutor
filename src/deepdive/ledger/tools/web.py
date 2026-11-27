from datetime import date
from typing import Any, Literal

import httpx

from deepdive.config import Config, Secrets
from deepdive.domain_packs import DomainPack
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.limits import Id, Keywords, Limit, Query, Url
from deepdive.ledger.tools._common import Tools
from deepdive.search.arxiv import Arxiv
from deepdive.search.base import TIER_KEY, SearchProvider, SearchResult
from deepdive.search.cache import Cache
from deepdive.search.fetch import Fetcher, FetchError, check_url
from deepdive.search.github import GitHub
from deepdive.search.hn import HackerNews


class WebTools(Tools):
    def __init__(
        self,
        ctx: LedgerContext,
        config: Config,
        pack: DomainPack,
        secrets: Secrets,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(ctx)
        self.pack = pack
        self.transport = transport
        self.cache = Cache(ctx.paths.cache)
        self.fetcher = Fetcher(pack.fetch_allowlist, config.search.fetch_max_chars)
        self.session_budget = config.search.session_budget  # a probe's budget is in probe_runs
        self.probe_limits = config.probe
        self.registry: dict[str, SearchProvider] = {
            p.name: p for p in (GitHub(secrets.github_token), Arxiv(), HackerNews())
        }
        self.enabled = [n for n in self.registry if n in config.search.apis and n in pack.providers]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport, timeout=20, headers={"User-Agent": "deepdive/0"}
        )

    def _source_id(self, url: str, tier_key: str, session_id: Id | None) -> str:
        row = self.ctx.store.sources.register(
            url=url,
            kind=tier_key,
            tier=self.pack.source_tiers[tier_key],
            seen_at=self.ctx.now(),
            session_id=session_id,
        )
        return str(row.id)

    def _register_result(self, r: SearchResult, session_id: Id | None) -> str | None:
        try:
            check_url(r.url, self.pack.fetch_allowlist)
        except FetchError:
            return None  # e.g. a Hacker News story's external link: never registered
        return self._source_id(r.url, TIER_KEY[r.kind], session_id)

    def _spent(self, kind: Literal["search", "fetch"], session_id: Id | None) -> bool:
        """Count one call against the budget; True when the budget is already used up."""
        if probe := self.ctx.probe:
            limit = (
                self.probe_limits.searches_per_topic
                if kind == "search"
                else self.probe_limits.fetches_per_topic
            )
            return not self.ctx.store.probe_runs.spend(
                probe.probe_run_id, probe.topic_id, kind, limit
            )
        if kind == "fetch":
            return False
        if session_id is None:
            raise InvalidInputError("search needs the session_id returned by session_start")
        return not self.ctx.store.sessions.spend_search(session_id, self.session_budget)

    async def search(
        self,
        query: Query,
        optional: Keywords | None = None,
        providers: list[str] | None = None,
        since: date | None = None,
        limit: Limit = 10,
        session_id: Id | None = None,
    ) -> dict[str, Any]:
        """Search GitHub, arXiv and Hacker News; each result carries a citable source_id.

        A result off the domain allowlist has source_id null and can't be cited unless the
        agent opens it with WebFetch.

        query: 1-4 keywords every result must match (the topic name), never a sentence.
        optional: a few more keywords that rank results but may be missing.

        session_id is required outside a probe.

        providers picks from the enabled providers (default all). Each call costs one search
        from the session budget; at zero the answer is {"error": "budget_exhausted"}.
        """
        chosen = providers or self.enabled
        if unknown := [n for n in chosen if n not in self.enabled]:
            raise InvalidInputError(f"unknown providers {unknown}; enabled: {self.enabled}")
        if session_id:
            self.ctx.store.sessions.require(session_id)
        if self._spent("search", session_id):
            return {"error": "budget_exhausted", "detail": "no searches left in this session"}
        results: list[SearchResult] = []
        errors: dict[str, str] = {}
        async with self._client() as http:
            for name in chosen:
                key = (name, query, *(optional or ()), str(since), str(limit))
                hit = self.cache.get(*key)
                try:
                    if hit is None:
                        found = await self.registry[name].search(
                            http, query, optional=optional or (), since=since, limit=limit
                        )
                        self.cache.put([r.model_dump(mode="json") for r in found], *key)
                    else:
                        found = [SearchResult.model_validate(r) for r in hit]
                except httpx.HTTPError as err:
                    errors[name] = type(err).__name__  # never the message: it may echo the URL
                    continue
                results += found
        out = [
            {**r.model_dump(mode="json"), "source_id": self._register_result(r, session_id)}
            for r in results
        ]
        left = (
            None
            if self.ctx.probe or session_id is None
            else self.session_budget - self.ctx.store.sessions.require(session_id).searches_used
        )
        return {"results": out, "errors": errors, "budget_remaining": left}

    async def fetch(self, url: Url, session_id: Id | None = None) -> dict[str, Any]:
        """Fetch a page from an allowlisted host as text (truncated, with `truncated: true`)."""
        if session_id:
            self.ctx.store.sessions.require(session_id)
        if self._spent("fetch", session_id):
            return {"error": "budget_exhausted", "detail": "no fetches left for this topic"}
        try:
            async with self._client() as http:
                text, truncated = await self.fetcher.text(http, url)
        except FetchError as err:
            return {"error": err.code, "detail": str(err)}
        host = (httpx.URL(url).host).lower()
        key = (
            "paper" if host.endswith("arxiv.org") else "repo" if "github" in host else "discussion"
        )
        return {
            "source_id": self._source_id(url, key, session_id),
            "url": url,
            "text": text,
            "truncated": truncated,
        }
