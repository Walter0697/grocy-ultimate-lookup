import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.adapters.base import LookupAdapter
from app.config import settings
from app.models import LookupResult
from app.normalization import normalize_product_name


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


class SearchResult:
    def __init__(self, title: str, url: str) -> None:
        self.title = title
        self.url = url


class StructuredProduct:
    def __init__(
        self,
        name: str,
        brand: str | None = None,
        image_url: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        extraction_method: str = "structured",
    ) -> None:
        self.name = name
        self.brand = brand
        self.image_url = image_url
        self.raw_payload = raw_payload or {}
        self.extraction_method = extraction_method


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


class ProductMetadataExtractor(HTMLParser):
    def __init__(self, barcode: str) -> None:
        super().__init__()
        self.barcode = barcode
        self.json_ld_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self.script_blocks: list[str] = []
        self._script_type: str | None = None
        self._script_content: list[str] = []

    @classmethod
    def extract(cls, html: str, barcode: str) -> StructuredProduct | None:
        parser = cls(barcode)
        parser.feed(html)
        return parser.extract_product()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "meta":
            key = attr_map.get("property") or attr_map.get("name")
            content = attr_map.get("content")
            if key and content:
                self.meta[key.lower()] = content
        if tag == "script":
            self._script_type = attr_map.get("type", "")
            self._script_content = []

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_content.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self._script_type is None:
            return
        content = "".join(self._script_content).strip()
        if self._script_type.lower() == "application/ld+json":
            self.json_ld_blocks.append(content)
        elif content:
            self.script_blocks.append(content)
        self._script_type = None
        self._script_content = []

    def extract_product(self) -> StructuredProduct | None:
        json_ld_product = self._extract_json_ld_product()
        if json_ld_product is not None:
            return json_ld_product

        embedded_product = self._extract_embedded_product_json()
        if embedded_product is not None:
            return embedded_product

        return self._extract_open_graph_product()

    def _extract_json_ld_product(self) -> StructuredProduct | None:
        for block in self.json_ld_blocks:
            for item in iter_json_values(parse_json(block)):
                if not isinstance(item, dict) or not is_product_type(item.get("@type")):
                    continue
                name = first_string(item.get("name"))
                if not name:
                    continue
                return StructuredProduct(
                    name=name,
                    brand=extract_brand(item.get("brand")),
                    image_url=extract_image_url(item.get("image")),
                    raw_payload=item,
                    extraction_method="json_ld",
                )
        return None

    def _extract_embedded_product_json(self) -> StructuredProduct | None:
        for block in self.script_blocks:
            if self.barcode not in block:
                continue
            for item in iter_json_values(parse_first_json_object(block)):
                if not isinstance(item, dict):
                    continue
                name = first_string(item.get("name") or item.get("productName") or item.get("title"))
                if not name:
                    continue
                return StructuredProduct(
                    name=name,
                    brand=extract_brand(item.get("brand")),
                    image_url=extract_image_url(item.get("image") or item.get("imageUrl")),
                    raw_payload=item,
                    extraction_method="embedded_json",
                )
        return None

    def _extract_open_graph_product(self) -> StructuredProduct | None:
        title = self.meta.get("og:title") or self.meta.get("twitter:title")
        page_type = self.meta.get("og:type", "")
        if not title or ("product" not in page_type.lower() and self.barcode not in title):
            return None
        return StructuredProduct(
            name=title,
            image_url=self.meta.get("og:image") or self.meta.get("twitter:image"),
            raw_payload={"meta": self.meta},
            extraction_method="open_graph",
        )


class WebSearchAdapter(LookupAdapter):
    name = "web_search"

    def __init__(self, search_provider: DuckDuckGoSearchProvider | None = None) -> None:
        self.search_provider = search_provider or DuckDuckGoSearchProvider()

    async def lookup(self, barcode: str) -> LookupResult | None:
        results = await self.search_provider.search(f'"{barcode}" product', limit=settings.web_search_max_results)
        candidates = [result for result in results if is_candidate_product_url(result.url)]
        if not candidates:
            return None

        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds, follow_redirects=True) as client:
            for candidate in candidates[: settings.web_search_fetch_limit]:
                product = await self._fetch_product(client, barcode, candidate)
                if product is not None:
                    return product
        return None

    async def _fetch_product(
        self,
        client: httpx.AsyncClient,
        barcode: str,
        candidate: SearchResult,
    ) -> LookupResult | None:
        try:
            response = await client.get(candidate.url, headers={"User-Agent": settings.lookup_user_agent})
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
            return None

        product = ProductMetadataExtractor.extract(response.text, barcode)
        if product is None:
            return None

        normalized = normalize_product_name(product.name, brand=product.brand)
        return LookupResult(
            barcode=barcode,
            name=normalized.normalized_name,
            raw_name=product.name,
            normalized_name=normalized.normalized_name,
            brand=normalized.brand,
            quantity=None,
            size=normalized.size,
            count=normalized.count,
            variant=normalized.variant,
            image_url=product.image_url,
            source=f"web_{product.extraction_method}",
            confidence=0.55,
            raw_url=candidate.url,
            raw_payload={
                "search_title": candidate.title,
                "extraction_method": product.extraction_method,
                "product": product.raw_payload,
            },
        )


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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def parse_first_json_object(value: str) -> Any:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", value):
        try:
            parsed, _ = decoder.raw_decode(value[match.start() :])
            return parsed
        except json.JSONDecodeError:
            continue
    return None


def iter_json_values(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_values(child)


def is_product_type(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "product"
    if isinstance(value, list):
        return any(is_product_type(item) for item in value)
    return False


def first_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return normalize_text(value)
    if isinstance(value, list):
        for item in value:
            found = first_string(item)
            if found:
                return found
    return None


def extract_brand(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_string(value.get("name"))
    return first_string(value)


def extract_image_url(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_string(value.get("contentUrl") or value.get("thumbnailUrl") or value.get("url"))
    if isinstance(value, list):
        for item in value:
            found = extract_image_url(item)
            if found:
                return found
    return first_string(value)
