import httpx

from app.adapters.base import LookupAdapter
from app.config import settings
from app.models import LookupResult
from app.normalization import normalize_product_name


class UpcItemDbAdapter(LookupAdapter):
    name = "upcitemdb"

    async def lookup(self, barcode: str) -> LookupResult | None:
        url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={barcode}"
        async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds) as client:
            response = await client.get(url, headers={"User-Agent": settings.lookup_user_agent})
        if response.status_code != 200:
            return None

        payload = response.json()
        if not payload.get("total"):
            return None

        item = payload["items"][0]
        name = item.get("title")
        if not name:
            return None

        normalized = normalize_product_name(name, brand=item.get("brand"))
        return LookupResult(
            barcode=barcode,
            name=normalized.normalized_name,
            raw_name=name,
            normalized_name=normalized.normalized_name,
            brand=normalized.brand,
            quantity=None,
            size=normalized.size,
            count=normalized.count,
            variant=normalized.variant,
            image_url=(item.get("images") or [None])[0],
            source=self.name,
            confidence=0.9,
            raw_url=url,
            raw_payload=item,
        )
