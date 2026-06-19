import asyncio

import httpx

from app.adapters.web_search import (
    DuckDuckGoResultParser,
    ProductMetadataExtractor,
    SearchResult,
    SearxngSearchProvider,
    VisibleTextExtractor,
    WebSearchAdapter,
    contains_barcode,
    decode_duckduckgo_url,
    extract_structured_barcodes,
    is_candidate_product_url,
    llm_confidence,
    titles_conflict,
    web_confidence,
)
from app.cache import LookupCache
from app.llm import LlmProductExtraction, LlmProvider
from app.local_store import LocalProductStore
from app.models import LookupResult
from app.orchestrator import LookupOrchestrator


def run(coro):
    return asyncio.run(coro)


class DisabledAgentSearch:
    class Store:
        def get_result(self, barcode: str):
            return None

    store = Store()

    def submit(self, barcode: str) -> bool:
        return False


class RecordingAgentSearch:
    class Store:
        def get_result(self, barcode: str):
            return None

        def get_status(self, barcode: str):
            return None

    def __init__(self) -> None:
        self.store = self.Store()
        self.submitted: list[tuple[str, LookupResult | None]] = []

    def submit(self, barcode: str, fallback_result: LookupResult | None = None) -> bool:
        self.submitted.append((barcode, fallback_result))
        return True


def test_duckduckgo_result_parser_extracts_candidate_urls() -> None:
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fproduct%2F123">Example Product</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freddit.com%2Fr%2Fbarcode">Reddit Thread</a>
    """

    results = DuckDuckGoResultParser.parse(html, limit=5)

    assert len(results) == 1
    assert results[0].title == "Example Product"
    assert results[0].url == "https://example.com/product/123"


def test_decode_duckduckgo_url_returns_original_target() -> None:
    url = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fshop.example.com%2Fitem%3Fsku%3D123"

    assert decode_duckduckgo_url(url) == "https://shop.example.com/item?sku=123"


def test_candidate_url_filter_rejects_search_and_social_hosts() -> None:
    assert is_candidate_product_url("https://shop.example.com/item/123") is True
    assert is_candidate_product_url("https://www.google.com/search?q=123") is False
    assert is_candidate_product_url("https://reddit.com/r/help/comments/123") is False


def test_extracts_json_ld_product_metadata() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Retailer Product 12 oz",
      "gtin12": "067489302124",
      "brand": {"@type": "Brand", "name": "Retailer Brand"},
      "image": [
        {
          "@type": "ImageObject",
          "contentUrl": "https://example.com/image.jpg"
        }
      ]
    }
    </script>
    """

    product = ProductMetadataExtractor.extract(html, barcode="067489302124")

    assert product is not None
    assert product.name == "Retailer Product 12 oz"
    assert product.brand == "Retailer Brand"
    assert product.image_url == "https://example.com/image.jpg"
    assert product.extraction_method == "json_ld"
    assert product.match_reason == "barcode_in_structured_data"


def test_extracts_embedded_json_product_metadata_when_barcode_is_present() -> None:
    html = """
    <script>
    window.__DATA__ = {
      "product": {
        "upc": "067489302124",
        "productName": "Embedded Retailer Product",
        "brand": "Embedded Brand",
        "imageUrl": "https://example.com/embedded.jpg"
      }
    };
    </script>
    """

    product = ProductMetadataExtractor.extract(html, barcode="067489302124")

    assert product is not None
    assert product.name == "Embedded Retailer Product"
    assert product.brand == "Embedded Brand"
    assert product.image_url == "https://example.com/embedded.jpg"
    assert product.extraction_method == "embedded_json"
    assert product.match_reason == "barcode_in_structured_data"


def test_extracts_open_graph_product_metadata() -> None:
    html = """
    <meta property="og:type" content="product">
    <meta property="og:title" content="Open Graph Product">
    <meta property="og:image" content="https://example.com/og.jpg">
    """

    product = ProductMetadataExtractor.extract(html, barcode="123")

    assert product is not None
    assert product.name == "Open Graph Product"
    assert product.image_url == "https://example.com/og.jpg"
    assert product.extraction_method == "open_graph"
    assert product.match_reason == "search_result_only"


def test_rejects_product_with_conflicting_structured_barcode() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@type": "Product",
      "name": "Wrong Product",
      "gtin12": "111111111111"
    }
    </script>
    """

    assert ProductMetadataExtractor.extract(html, barcode="067489302124") is None


def test_uses_page_content_evidence_when_structured_barcode_is_missing() -> None:
    html = """
    <div>UPC: 067 489 302 124</div>
    <script type="application/ld+json">
    {
      "@type": "Product",
      "name": "Page Evidence Product"
    }
    </script>
    """

    product = ProductMetadataExtractor.extract(html, barcode="067489302124")

    assert product is not None
    assert product.match_reason == "barcode_in_page_content"


def test_barcode_and_title_confidence_helpers() -> None:
    assert contains_barcode("UPC: 067-489-302-124", "067489302124") is True
    assert extract_structured_barcodes({"gtin12": "067489302124"}) == {"067489302124"}
    assert titles_conflict("Oral-B Replacement Brush Heads", "GLAD CLINGWRAP 50M") is True
    assert titles_conflict("GLAD Cling Wrap Online Store", "GLAD CLINGWRAP 50M") is False
    assert web_confidence("barcode_in_structured_data", []) == 0.65
    assert web_confidence("barcode_in_page_content", []) == 0.55
    assert web_confidence("search_result_only", []) == 0.45
    assert web_confidence("barcode_in_structured_data", ["search_title_product_name_mismatch"]) == 0.4
    assert llm_confidence(True, []) == 0.35
    assert llm_confidence(False, []) == 0.25
    assert llm_confidence(True, ["search_title_product_name_mismatch"]) == 0.2


def test_visible_text_extractor_omits_scripts_and_limits_content() -> None:
    html = "<h1>Product Name</h1><script>secret data</script><p>Useful description</p>"

    text = VisibleTextExtractor.extract(html, limit=20)

    assert text == "Product Name Useful "
    assert "secret" not in text


def test_llm_fallback_runs_only_when_structured_extraction_fails() -> None:
    class FakeLlmProvider(LlmProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def extract_product(self, barcode: str, page_url: str, page_text: str) -> LlmProductExtraction:
            self.calls += 1
            return LlmProductExtraction(
                found=True,
                name="LLM Extracted Product 12 oz",
                brand="LLM Brand",
                barcode_seen=True,
            )

    async def scenario():
        provider = FakeLlmProvider()
        adapter = WebSearchAdapter(llm_provider=provider)
        candidate = SearchResult("LLM Extracted Product", "https://example.com/product")
        response = httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>UPC 067489302124 LLM Extracted Product 12 oz by LLM Brand</body></html>",
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
        async with client:
            result = await adapter._fetch_product(client, "067489302124", candidate)
        return result, provider.calls

    result, calls = run(scenario())

    assert calls == 1
    assert result is not None
    assert result.source == "llm_fallback"
    assert result.name == "LLM Extracted Product"
    assert result.size == "12 oz"
    assert result.confidence == 0.35
    assert result.match_reason == "llm_barcode_in_page"


def test_structured_product_prevents_llm_fallback_call() -> None:
    class FailingLlmProvider(LlmProvider):
        async def extract_product(self, barcode: str, page_url: str, page_text: str) -> LlmProductExtraction:
            raise AssertionError("LLM should not run when structured extraction succeeds")

    async def scenario():
        adapter = WebSearchAdapter(llm_provider=FailingLlmProvider())
        candidate = SearchResult("Structured Product", "https://example.com/product")
        html = """
        <script type="application/ld+json">
        {"@type":"Product","name":"Structured Product","gtin12":"067489302124"}
        </script>
        """
        response = httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
        async with client:
            return await adapter._fetch_product(client, "067489302124", candidate)

    result = run(scenario())

    assert result is not None
    assert result.source == "web_json_ld"


def test_structured_product_resolves_relative_image_url() -> None:
    async def scenario():
        adapter = WebSearchAdapter(llm_provider=None)
        candidate = SearchResult("Structured Product", "https://shop.example.com/products/item")
        html = """
        <script type="application/ld+json">
        {
          "@type":"Product",
          "name":"Structured Product",
          "gtin12":"067489302124",
          "image":"/-/media/project/oneweb/product.jpg"
        }
        </script>
        """
        response = httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
        async with client:
            return await adapter._fetch_product(client, "067489302124", candidate)

    result = run(scenario())

    assert result is not None
    assert str(result.image_url) == "https://shop.example.com/-/media/project/oneweb/product.jpg"


def test_malformed_llm_fallback_returns_no_product() -> None:
    class EmptyLlmProvider(LlmProvider):
        async def extract_product(self, barcode: str, page_url: str, page_text: str) -> None:
            return None

    async def scenario():
        adapter = WebSearchAdapter(llm_provider=EmptyLlmProvider())
        candidate = SearchResult("Unknown Page", "https://example.com/product")
        response = httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Unknown page</p>")
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
        async with client:
            return await adapter._fetch_product(client, "067489302124", candidate)

    assert run(scenario()) is None


def test_web_search_uses_multiple_barcoded_queries_with_deduped_fetches(monkeypatch) -> None:
    class FakeSearchProvider:
        def __init__(self) -> None:
            self.queries: list[tuple[str, int]] = []

        async def search(self, query: str, limit: int) -> list[SearchResult]:
            self.queries.append((query, limit))
            return [
                SearchResult(f"{query} duplicate", "https://shop.example.com/product"),
                SearchResult(f"{query} duplicate again", "https://shop.example.com/product"),
                SearchResult(f"{query} ignored social", "https://reddit.com/r/barcode"),
            ]

    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
            <script type="application/ld+json">
            {"@type":"Product","name":"Verified Search Product","gtin12":"067489302124"}
            </script>
            """,
        )

    async def scenario():
        provider = FakeSearchProvider()
        adapter = WebSearchAdapter(search_provider=provider, llm_provider=None)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with client:
            result = await adapter.lookup("067489302124", client=client)
        return result, provider.queries

    monkeypatch.setattr("app.adapters.web_search.settings.web_search_max_queries", 2)
    monkeypatch.setattr("app.adapters.web_search.settings.web_search_max_results", 4)

    result, queries = run(scenario())

    assert result is not None
    assert result.source == "web_json_ld"
    assert result.match_reason == "barcode_in_structured_data"
    assert [query for query, _limit in queries] == [
        '"067489302124" product',
        "067489302124 barcode product",
    ]
    assert [limit for _query, limit in queries] == [4, 4]
    assert requests == ["https://shop.example.com/product"]


def test_searxng_search_provider_parses_json_results() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example Product",
                        "url": "https://shop.example.com/product",
                    },
                    {
                        "title": "Search Result Page",
                        "url": "https://www.google.com/search?q=067489302124",
                    },
                ]
            },
        )

    async def scenario():
        provider = SearxngSearchProvider(
            base_url="https://search.example.test",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        async with provider.client:
            return await provider.search('"067489302124" product', limit=5)

    results = run(scenario())

    assert seen_urls == [
        "https://search.example.test/search?q=%22067489302124%22+product&format=json"
    ]
    assert len(results) == 1
    assert results[0].title == "Example Product"
    assert results[0].url == "https://shop.example.com/product"


def test_verified_web_result_does_not_queue_agent_search(tmp_path) -> None:
    class FakeWebAdapter:
        name = "fake_web"

        async def lookup(self, barcode: str) -> LookupResult:
            return LookupResult(
                barcode=barcode,
                name="Verified Web Product",
                normalized_name="Verified Web Product",
                source="web_json_ld",
                confidence=0.65,
                match_reason="barcode_in_structured_data",
            )

    orchestrator = LookupOrchestrator(adapters=[FakeWebAdapter()])
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    orchestrator.agent_search = RecordingAgentSearch()

    response = run(orchestrator.lookup("067489302124", use_cache=False))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "web_json_ld"
    assert orchestrator.agent_search.submitted == []


def test_low_confidence_web_result_can_autofill_but_is_not_cached(tmp_path) -> None:
    class FakeWebAdapter:
        name = "fake_web"

        async def lookup(self, barcode: str) -> LookupResult:
            return LookupResult(
                barcode=barcode,
                name="Web Product",
                normalized_name="Web Product",
                source="web_json_ld",
                confidence=0.55,
            )

    orchestrator = LookupOrchestrator(adapters=[FakeWebAdapter()])
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    orchestrator.agent_search = DisabledAgentSearch()

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is True
    assert response.result is not None
    assert response.result.name == "Web Product"
    assert orchestrator.cache.get("123") is None
