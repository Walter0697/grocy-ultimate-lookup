import json
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.config import settings
from app.search.extraction import normalize_text
from app.search.models import SearchResult


BLOCKED_HOST_PARTS = (
    "duckduckgo.",
    "google.",
    "bing.",
    "facebook.",
    "instagram.",
    "pinterest.",
    "reddit.",
    "tiktok.",
    "youtube.",
)


class DuckDuckGoSearchProvider:
    search_url = "https://duckduckgo.com/html/"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(
                f"{self.search_url}?q={quote_plus(query)}",
                headers={"User-Agent": settings.lookup_user_agent},
            )
        if response.status_code != 200:
            return []
        return DuckDuckGoResultParser.parse(response.text, limit=limit)


class SearxngSearchProvider:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        close_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=settings.lookup_request_timeout_seconds,
            follow_redirects=True,
        )
        try:
            response = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json"},
                headers={"User-Agent": settings.lookup_user_agent},
            )
        except httpx.HTTPError:
            return []
        finally:
            if close_client:
                await client.aclose()
        if response.status_code != 200:
            return []
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return []
        results = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            url = item.get("url")
            if isinstance(title, str) and isinstance(url, str) and is_candidate_product_url(url):
                results.append(SearchResult(title=normalize_text(title), url=url))
            if len(results) >= limit:
                break
        return results


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    @classmethod
    def parse(cls, html: str, limit: int) -> list[SearchResult]:
        parser = cls()
        parser.feed(html)
        return parser.results[:limit]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        css_class = attr_map.get("class") or ""
        href = attr_map.get("href")
        if href and "result__a" in css_class:
            self._current_href = decode_duckduckgo_url(href)
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            title = normalize_text(" ".join(self._current_text))
            if title and is_candidate_product_url(self._current_href):
                self.results.append(SearchResult(title=title, url=self._current_href))
            self._current_href = None
            self._current_text = []


def create_search_provider() -> DuckDuckGoSearchProvider | SearxngSearchProvider:
    provider = settings.web_search_provider.strip().lower()
    if provider == "searxng" and settings.searxng_base_url:
        return SearxngSearchProvider(settings.searxng_base_url)
    return DuckDuckGoSearchProvider()


def decode_duckduckgo_url(url: str) -> str:
    parsed = urlparse(unescape(url))
    params = parse_qs(parsed.query)
    if "uddg" in params:
        return unquote(params["uddg"][0])
    return unescape(url)


def is_candidate_product_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    return not any(blocked in host for blocked in BLOCKED_HOST_PARTS)
