from typing import Any


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
