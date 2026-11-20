"""Search and fetch through the ledger server; every HTTP call is answered from fixtures."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from test_ledger_server import Ledger

from deepdive.ledger.server import create_server
from deepdive.paths import Paths
from deepdive.search.arxiv import Arxiv
from deepdive.search.github import GitHub
from deepdive.search.hn import HackerNews

FIX = Path(__file__).parent / "fixtures" / "http"


def handler(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "api.github.com":
        name = {"/search/repositories": "github_repos", "/search/issues": "github_issues"}.get(
            path, "github_releases"
        )
        return httpx.Response(200, content=(FIX / f"{name}.json").read_bytes())
    if host == "export.arxiv.org":
        return httpx.Response(200, content=(FIX / "arxiv.xml").read_bytes())
    if host == "hn.algolia.com":
        return httpx.Response(200, content=(FIX / "hn.json").read_bytes())
    if host == "raw.githubusercontent.com":
        return httpx.Response(200, text="# readme", headers={"content-type": "text/plain"})
    return httpx.Response(500)


@pytest.fixture
def web(tmp_path: Path) -> Ledger:
    paths = Paths(tmp_path)
    return Ledger(create_server(paths, transport=httpx.MockTransport(handler)), paths)


def run_provider(provider: GitHub | Arxiv | HackerNews) -> list:  # type: ignore[type-arg]
    async def go() -> list:  # type: ignore[type-arg]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await provider.search(c, "iceberg", since=None, limit=5)

    return asyncio.run(go())


def test_github_parses_repos_and_issues() -> None:
    kinds = {r.kind for r in run_provider(GitHub())}
    assert kinds == {"repo", "issue"}


def test_github_releases_parse() -> None:
    async def go() -> list:  # type: ignore[type-arg]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await GitHub().releases(c, "apache/iceberg", limit=5)

    assert {r.kind for r in asyncio.run(go())} == {"release"}


def test_arxiv_parses_papers() -> None:
    papers = run_provider(Arxiv())
    assert papers and all(p.kind == "paper" and p.url.startswith("https://") for p in papers)


def test_hn_parses_stories_and_comments() -> None:
    assert {r.kind for r in run_provider(HackerNews())} == {"story", "comment"}


def test_search_registers_sources_and_returns_their_ids(web: Ledger) -> None:
    out = web.call("search", query="iceberg")
    assert out["errors"] == {} and out["results"]
    assert web.count("source") == len({r["source_id"] for r in out["results"]})
    web.call("search", query="iceberg")  # second call is a cache hit and adds no sources
    assert web.count("source") == len({r["source_id"] for r in out["results"]})


def test_search_budget_runs_out(web: Ledger) -> None:
    (web.paths.config).write_text('[search]\nsession_budget = 2\napis = ["hn"]\n')
    server = create_server(web.paths, transport=httpx.MockTransport(handler))
    tight = Ledger(server, web.paths)
    assert "results" in tight.call("search", query="a")
    assert tight.call("search", query="b")["budget_remaining"] == 0
    assert tight.call("search", query="c")["error"] == "budget_exhausted"


def test_search_rejects_unknown_providers_and_lists_enabled_ones(web: Ledger) -> None:
    """An unknown provider name is invalid input whose detail names the enabled providers."""
    out = web.call("search", query="x", providers=["nope"])
    assert out["error"] == "invalid_input"
    assert out["detail"] == "unknown providers ['nope']; enabled: ['github', 'arxiv', 'hn']"


def test_provider_failure_is_reported_without_message(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-url-detail")

    paths = Paths(tmp_path)
    out = Ledger(create_server(paths, transport=httpx.MockTransport(boom)), paths).call(
        "search", query="x"
    )
    assert out["results"] == [] and "secret-url-detail" not in json.dumps(out)


def test_fetch_refuses_hosts_off_the_allowlist(web: Ledger) -> None:
    out = web.call("fetch", url="https://evil.example.com/x")
    assert out["error"] == "host_not_allowed" and web.count("source") == 0


def test_fetch_allowlisted_github_readme_registers_source(web: Ledger) -> None:
    out = web.call("fetch", url="https://github.com/apache/iceberg")
    assert out["text"] == "# readme" and web.count("source") == 1


@pytest.mark.live
def test_live_hn_search() -> None:
    import os

    if not os.environ.get("DEEPDIVE_LIVE"):
        pytest.skip("set DEEPDIVE_LIVE=1")

    async def go() -> list:  # type: ignore[type-arg]
        async with httpx.AsyncClient() as c:
            return await HackerNews().search(c, "sqlite", since=None, limit=3)

    assert asyncio.run(go())
