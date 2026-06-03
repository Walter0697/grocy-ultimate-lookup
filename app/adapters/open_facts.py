import httpx

from app.adapters.base import LookupAdapter
from app.config import settings
from app.models import LookupResult
from app.normalization import normalize_product_name


class OpenFactsAdapter(LookupAdapter):
    def __init__(self, name: str, host: str) -> None:
        self.name = name
        self.host = host

    async def lookup(self, barcode: str) -> LookupResult | None:
        url = f"https://{self.host}/api/v0/product/{barcode}.json"
        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds) as client:
            response = await client.get(url, headers={"User-Agent": settings.lookup_user_agent})
        if response.status_code != 200:
            return None

        payload = response.json()
        if payload.get("status") != 1:
            return None

        product = payload.get("product") or {}
        name = product.get("product_name") or product.get("product_name_en")
        if not name:
            return None

        brand = product.get("brands")
        quantity = product.get("quantity")
        normalized = normalize_product_name(name, brand=brand, quantity=quantity)
        image_url = product.get("image_front_url") or product.get("image_url")
        return LookupResult(
            barcode=barcode,
            name=normalized.normalized_name,
            raw_name=name,
            normalized_name=normalized.normalized_name,
            brand=normalized.brand,
            quantity=quantity,
            size=normalized.size,
            count=normalized.count,
            variant=normalized.variant,
            image_url=image_url,
            source=self.name,
            confidence=0.95,
            raw_url=url,
            raw_payload=product,
        )
