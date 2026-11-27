"""Search and fetch through the ledger server; every HTTP call is answered from fixtures."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from test_ledger_server import Ledger, _session

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
    sid = _session(web)[1]
    out = web.call("search", query="iceberg", session_id=sid)
    assert out["errors"] == {} and out["results"]
    ids = {r["source_id"] for r in out["results"]} - {None}
    assert web.count("source") == len(ids)
    web.call(
        "search", query="iceberg", session_id=sid
    )  # second call is a cache hit and adds no sources
    assert web.count("source") == len(ids)


def test_search_does_not_register_results_off_the_allowlist(web: Ledger) -> None:
    """A Hacker News story linking off the allowlist has source_id null."""
    sid = _session(web)[1]
    out = web.call("search", query="iceberg", providers=["hn"], session_id=sid)
    by_url = {r["url"]: r["source_id"] for r in out["results"]}
    assert by_url["https://joshdata.me/iceberger.html"] is None
    assert by_url["https://github.com/Snowflake-Labs/pg_lake"] is not None
    assert web.count("source") == sum(v is not None for v in by_url.values())


def test_search_budget_runs_out(web: Ledger) -> None:
    (web.paths.config).write_text('[search]\nsession_budget = 2\napis = ["hn"]\n')
    server = create_server(web.paths, transport=httpx.MockTransport(handler))
    tight = Ledger(server, web.paths)
    sid = _session(tight)[1]
    assert "results" in tight.call("search", query="a", session_id=sid)
    assert tight.call("search", query="b", session_id=sid)["budget_remaining"] == 0
    assert tight.call("search", query="c", session_id=sid)["error"] == "budget_exhausted"
    assert tight.call("search", query="c")["error"] == "invalid_input"  # no session to charge


def test_search_rejects_unknown_providers_and_lists_enabled_ones(web: Ledger) -> None:
    """An unknown provider name is invalid input whose detail names the enabled providers."""
    out = web.call("search", query="x", providers=["nope"])
    assert out["error"] == "invalid_input"
    assert out["detail"] == "unknown providers ['nope']; enabled: ['github', 'arxiv', 'hn']"


def test_provider_failure_is_reported_without_message(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-url-detail")

    paths = Paths(tmp_path)
    led = Ledger(create_server(paths, transport=httpx.MockTransport(boom)), paths)
    out = led.call("search", query="x", session_id=_session(led)[1])
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


@pytest.mark.parametrize(
    ("provider", "param", "expected"),
    [
        (HackerNews(), "query", "python threading race lock"),
        (HackerNews(), "optionalWords", "race lock"),
        (Arxiv(), "search_query",
         "all:python AND all:threading AND (all:race OR all:lock) AND cat:cs.*"),
        (GitHub(), "q", "python threading race lock"),
    ],
    ids=["hn-query", "hn-optional", "arxiv-or-group", "github-and"],
)  # fmt: skip
def test_optional_keywords_reach_each_provider_in_its_own_form(
    provider: GitHub | Arxiv | HackerNews, param: str, expected: str
) -> None:
    """Required words must match; optional ones go where each API ranks them without requiring."""
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def go() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as c:
            await provider.search(
                c, "python threading", optional=["race", "lock"], since=None, limit=5
            )

    asyncio.run(go())
    assert seen[0].url.params[param] == expected


def test_optional_keywords_are_part_of_the_cache_key(tmp_path: Path) -> None:
    """Two searches that differ only in optional keywords both reach the provider."""
    hits: list[str] = []

    def count(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.host)
        return handler(request)

    paths = Paths(tmp_path)
    web = Ledger(create_server(paths, transport=httpx.MockTransport(count)), paths)
    sid = _session(web)[1]
    for optional in (["race"], ["lock"], ["lock"]):
        web.call("search", query="python", optional=optional, providers=["hn"], session_id=sid)
    assert hits == ["hn.algolia.com"] * 2


@pytest.mark.parametrize(
    "args",
    [
        {"query": "how does the python interpreter release the gil during blocking io"},
        {"query": "python", "optional": [f"w{i}" for i in range(9)]},
        {"query": "python", "optional": ["x" * 65]},
    ],
    ids=["sentence-query", "too-many-keywords", "long-keyword"],
)
def test_search_input_is_a_few_keywords(web: Ledger, args: dict[str, object]) -> None:
    """A sentence as query, or too many / too long optional keywords, is invalid input."""
    assert web.call("search", **args)["error"] == "invalid_input"
