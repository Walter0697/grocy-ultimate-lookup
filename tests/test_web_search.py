import asyncio

from app.adapters.web_search import (
    DuckDuckGoResultParser,
    ProductMetadataExtractor,
    decode_duckduckgo_url,
    is_candidate_product_url,
)
from app.cache import LookupCache
from app.local_store import LocalProductStore
from app.models import LookupResult
from app.orchestrator import LookupOrchestrator


def run(coro):
    return asyncio.run(coro)


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

    product = ProductMetadataExtractor.extract(html, barcode="123")

    assert product is not None
    assert product.name == "Retailer Product 12 oz"
    assert product.brand == "Retailer Brand"
    assert product.image_url == "https://example.com/image.jpg"
    assert product.extraction_method == "json_ld"


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


def test_low_confidence_web_result_is_returned_as_candidate_not_autofill(tmp_path) -> None:
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

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is False
    assert response.result is None
    assert len(response.candidates) == 1
    assert response.candidates[0].name == "Web Product"
