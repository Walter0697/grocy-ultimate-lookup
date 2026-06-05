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

BARCODE_FIELD_NAMES = {
    "barcode",
    "ean",
    "ean8",
    "ean13",
    "gtin",
    "gtin8",
    "gtin12",
    "gtin13",
    "gtin14",
    "sku",
    "upc",
}

TITLE_STOP_WORDS = {
    "and",
    "for",
    "from",
    "online",
    "product",
    "shop",
    "store",
    "the",
    "with",
}


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
        match_reason: str = "search_result_only",
    ) -> None:
        self.name = name
        self.brand = brand
        self.image_url = image_url
        self.raw_payload = raw_payload or {}
        self.extraction_method = extraction_method
        self.match_reason = match_reason


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
        self.page_contains_barcode = False
        self._script_type: str | None = None
        self._script_content: list[str] = []

    @classmethod
    def extract(cls, html: str, barcode: str) -> StructuredProduct | None:
        parser = cls(barcode)
        parser.page_contains_barcode = contains_barcode(html, barcode)
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
                match_reason = self._match_reason(item)
                if match_reason is None:
                    continue
                return StructuredProduct(
                    name=name,
                    brand=extract_brand(item.get("brand")),
                    image_url=extract_image_url(item.get("image")),
                    raw_payload=item,
                    extraction_method="json_ld",
                    match_reason=match_reason,
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
                match_reason = self._match_reason(item)
                if match_reason is None:
                    continue
                return StructuredProduct(
                    name=name,
                    brand=extract_brand(item.get("brand")),
                    image_url=extract_image_url(item.get("image") or item.get("imageUrl")),
                    raw_payload=item,
                    extraction_method="embedded_json",
                    match_reason=match_reason,
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
            match_reason="barcode_in_page_content" if self.page_contains_barcode else "search_result_only",
        )

    def _match_reason(self, item: dict[str, Any]) -> str | None:
        structured_barcodes = extract_structured_barcodes(item)
        if structured_barcodes:
            if normalize_barcode(self.barcode) not in structured_barcodes:
                return None
            return "barcode_in_structured_data"
        if self.page_contains_barcode:
            return "barcode_in_page_content"
        return "search_result_only"


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
        match_warnings: list[str] = []
        if titles_conflict(candidate.title, product.name):
            match_warnings.append("search_title_product_name_mismatch")
        confidence = web_confidence(product.match_reason, match_warnings)
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
            confidence=confidence,
            match_reason=product.match_reason,
            match_warnings=match_warnings,
            raw_url=candidate.url,
            raw_payload={
                "search_title": candidate.title,
                "extraction_method": product.extraction_method,
                "match_reason": product.match_reason,
                "match_warnings": match_warnings,
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


def normalize_barcode(value: str) -> str:
    return re.sub(r"\D", "", value)


def contains_barcode(value: str, barcode: str) -> bool:
    expected = normalize_barcode(barcode)
    if not expected:
        return False
    if expected in value:
        return True
    return any(normalize_barcode(candidate) == expected for candidate in re.findall(r"\d[\d\s-]{6,}\d", value))


def extract_structured_barcodes(value: Any) -> set[str]:
    barcodes: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized_key in BARCODE_FIELD_NAMES:
                for candidate in iter_scalar_strings(child):
                    normalized = normalize_barcode(candidate)
                    if len(normalized) >= 8:
                        barcodes.add(normalized)
            elif isinstance(child, (dict, list)):
                barcodes.update(extract_structured_barcodes(child))
    elif isinstance(value, list):
        for child in value:
            barcodes.update(extract_structured_barcodes(child))
    return barcodes


def iter_scalar_strings(value: Any):
    if isinstance(value, (str, int)):
        yield str(value)
    elif isinstance(value, list):
        for item in value:
            yield from iter_scalar_strings(item)


def title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in TITLE_STOP_WORDS and not token.isdigit()
    }


def titles_conflict(search_title: str, product_name: str) -> bool:
    search_tokens = title_tokens(search_title)
    product_tokens = title_tokens(product_name)
    return bool(search_tokens and product_tokens and search_tokens.isdisjoint(product_tokens))


def web_confidence(match_reason: str, match_warnings: list[str]) -> float:
    confidence_by_reason = {
        "barcode_in_structured_data": 0.65,
        "barcode_in_page_content": 0.55,
        "search_result_only": 0.45,
    }
    confidence = confidence_by_reason.get(match_reason, 0.4)
    if "search_title_product_name_mismatch" in match_warnings:
        confidence = min(confidence, 0.4)
    return confidence


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
