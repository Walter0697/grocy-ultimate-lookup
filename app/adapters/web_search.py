from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.base import LookupAdapter
from app.config import settings
from app.llm import LlmProvider, create_llm_provider
from app.models import LookupResult
from app.normalization import normalize_product_name
from app.search.extraction import (
    ProductMetadataExtractor,
    VisibleTextExtractor,
    contains_barcode,
    extract_structured_barcodes,
)
from app.search.models import SearchResult, StructuredProduct
from app.search.providers import (
    DuckDuckGoResultParser,
    DuckDuckGoSearchProvider,
    SearxngSearchProvider,
    create_search_provider,
    decode_duckduckgo_url,
    is_candidate_product_url,
)
from app.search.scoring import llm_confidence, titles_conflict, web_confidence


_LLM_PROVIDER_UNSET = object()


class WebSearchAdapter(LookupAdapter):
    name = "web_search"

    def __init__(
        self,
        search_provider: DuckDuckGoSearchProvider | SearxngSearchProvider | None = None,
        llm_provider: LlmProvider | None | object = _LLM_PROVIDER_UNSET,
        *,
        use_structured_extraction: bool = True,
        use_llm_fallback: bool = True,
    ) -> None:
        self.search_provider = search_provider or create_search_provider()
        self.use_structured_extraction = use_structured_extraction
        if not use_llm_fallback:
            self.llm_provider = None
        elif llm_provider is _LLM_PROVIDER_UNSET:
            self.llm_provider = create_llm_provider()
        else:
            self.llm_provider = llm_provider

    async def lookup(self, barcode: str, client: httpx.AsyncClient | None = None) -> LookupResult | None:
        candidates = await self._search_candidates(barcode)
        if not candidates:
            return None

        if client is not None:
            return await self._lookup_candidates(client, barcode, candidates)

        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds, follow_redirects=True) as owned_client:
            return await self._lookup_candidates(owned_client, barcode, candidates)

    async def _search_candidates(self, barcode: str) -> list[SearchResult]:
        candidates: list[SearchResult] = []
        seen_urls: set[str] = set()
        for query in search_queries_for_barcode(barcode)[: settings.web_search_max_queries]:
            results = await self.search_provider.search(query, limit=settings.web_search_max_results)
            for result in results:
                if not is_candidate_product_url(result.url) or result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                candidates.append(result)
                if len(candidates) >= settings.web_search_fetch_limit:
                    return candidates
        return candidates

    async def _lookup_candidates(
        self,
        client: httpx.AsyncClient,
        barcode: str,
        candidates: list[SearchResult],
    ) -> LookupResult | None:
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

        if self.use_structured_extraction:
            product = ProductMetadataExtractor.extract(response.text, barcode)
            if product is not None:
                return build_structured_lookup_result(barcode, candidate, product)
        return await self._fetch_llm_product(response.text, barcode, candidate)

    async def _fetch_llm_product(self, html: str, barcode: str, candidate: SearchResult) -> LookupResult | None:
        if self.llm_provider is None:
            return None

        page_text = VisibleTextExtractor.extract(html, limit=settings.llm_max_page_chars)
        if not page_text:
            return None
        extracted = await self.llm_provider.extract_product(barcode, candidate.url, page_text)
        if extracted is None:
            return None

        normalized = normalize_product_name(extracted.name or "", brand=extracted.brand, quantity=extracted.quantity)
        match_reason = "llm_barcode_in_page" if extracted.barcode_seen else "llm_page_extraction"
        match_warnings: list[str] = []
        if not extracted.barcode_seen:
            match_warnings.append("llm_did_not_see_exact_barcode")
        if titles_conflict(candidate.title, extracted.name or ""):
            match_warnings.append("search_title_product_name_mismatch")
        return LookupResult(
            barcode=barcode,
            name=normalized.normalized_name,
            raw_name=extracted.name,
            normalized_name=normalized.normalized_name,
            brand=normalized.brand,
            quantity=extracted.quantity,
            size=extracted.size or normalized.size,
            count=extracted.count or normalized.count,
            variant=extracted.variant or normalized.variant,
            image_url=absolute_image_url(extracted.image_url, candidate.url),
            source="llm_fallback",
            confidence=llm_confidence(extracted.barcode_seen, match_warnings),
            match_reason=match_reason,
            match_warnings=match_warnings,
            raw_url=candidate.url,
            raw_payload={
                "search_title": candidate.title,
                "extraction_method": "llm_fallback",
                "match_reason": match_reason,
                "match_warnings": match_warnings,
                "product": extracted.model_dump(mode="json"),
            },
        )


class WebSearchLlmFallbackAdapter(WebSearchAdapter):
    name = "web_search_llm_fallback"

    def __init__(
        self,
        search_provider: DuckDuckGoSearchProvider | SearxngSearchProvider | None = None,
        llm_provider: LlmProvider | None | object = _LLM_PROVIDER_UNSET,
    ) -> None:
        super().__init__(
            search_provider=search_provider,
            llm_provider=llm_provider,
            use_structured_extraction=False,
            use_llm_fallback=True,
        )


def build_structured_lookup_result(
    barcode: str,
    candidate: SearchResult,
    product: StructuredProduct,
) -> LookupResult:
    normalized = normalize_product_name(product.name, brand=product.brand)
    match_warnings: list[str] = []
    if titles_conflict(candidate.title, product.name):
        match_warnings.append("search_title_product_name_mismatch")
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
        image_url=absolute_image_url(product.image_url, candidate.url),
        source=f"web_{product.extraction_method}",
        confidence=web_confidence(product.match_reason, match_warnings),
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


def absolute_image_url(image_url: str | None, page_url: str) -> str | None:
    if not image_url:
        return None
    return urljoin(page_url, image_url)


def search_queries_for_barcode(barcode: str) -> list[str]:
    return [
        f'"{barcode}" product',
        f"{barcode} barcode product",
        f"{barcode} UPC",
    ]


def normalize_barcode(value: str) -> str:
    from app.search.extraction import normalize_barcode as _normalize_barcode

    return _normalize_barcode(value)


def normalize_text(value: str) -> str:
    from app.search.extraction import normalize_text as _normalize_text

    return _normalize_text(value)


def parse_json(value: str) -> Any:
    from app.search.extraction import parse_json as _parse_json

    return _parse_json(value)


def parse_first_json_object(value: str) -> Any:
    from app.search.extraction import parse_first_json_object as _parse_first_json_object

    return _parse_first_json_object(value)


def extract_brand(value: Any) -> str | None:
    from app.search.extraction import extract_brand as _extract_brand

    return _extract_brand(value)


def extract_image_url(value: Any) -> str | None:
    from app.search.extraction import extract_image_url as _extract_image_url

    return _extract_image_url(value)
