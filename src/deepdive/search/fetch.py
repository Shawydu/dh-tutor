"""Allowlisted GET: https only, every redirect hop re-checked, size capped, HTML to text."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
_BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section"}
_README = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/?$")


class FetchError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _check(url: str, allowed: list[str]) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port not in (None, 443):
        raise FetchError("scheme_not_allowed", "only plain https URLs are fetched")
    if (parts.hostname or "") not in allowed:
        raise FetchError("host_not_allowed", f"{parts.hostname} is not on the domain allowlist")
    return url


async def fetch_text(
    client: httpx.AsyncClient, url: str, allowed: list[str], max_chars: int
) -> tuple[str, bool]:
    """The page as text and whether it was cut short. Raises FetchError."""
    target = _check(url, allowed)
    if m := _README.match(target):  # a repo page is mostly navigation: take its README instead
        target = f"https://raw.githubusercontent.com/{m[1]}/{m[2]}/HEAD/README.md"
    for _ in range(MAX_REDIRECTS + 1):
        _check(target, allowed)
        try:
            async with client.stream("GET", target) as resp:
                if resp.is_redirect:
                    target = urljoin(target, resp.headers.get("location", ""))
                    continue
                if resp.status_code != 200:
                    raise FetchError("fetch_failed", f"HTTP {resp.status_code}")
                kind = resp.headers.get("content-type", "").split(";")[0].strip()
                if not (kind.startswith("text/") or kind.endswith(("json", "xml"))):
                    raise FetchError("unsupported_content_type", kind or "unknown")
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                cut = len(body) > MAX_BYTES
                text = body[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as err:
            raise FetchError("fetch_failed", type(err).__name__) from err
        if kind == "text/html":
            text = html_to_text(text)
        return text[:max_chars], cut or len(text) > max_chars
    raise FetchError("too_many_redirects", f"more than {MAX_REDIRECTS} redirects")
