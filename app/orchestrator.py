from app.adapters.base import LookupAdapter
from app.adapters.open_facts import OpenFactsAdapter
from app.adapters.upcitemdb import UpcItemDbAdapter
from app.cache import LookupCache
from app.config import settings
from app.models import LookupResponse, LookupResult


def default_adapters() -> list[LookupAdapter]:
    adapters: list[LookupAdapter] = []
    if settings.enable_open_facts:
        adapters.extend(
            [
                OpenFactsAdapter("open_food_facts", "world.openfoodfacts.org"),
                OpenFactsAdapter("open_products_facts", "world.openproductsfacts.org"),
                OpenFactsAdapter("open_beauty_facts", "world.openbeautyfacts.org"),
                OpenFactsAdapter("open_pet_food_facts", "world.openpetfoodfacts.org"),
            ]
        )
    if settings.enable_upcitemdb:
        adapters.append(UpcItemDbAdapter())
    return adapters


class LookupOrchestrator:
    def __init__(self, adapters: list[LookupAdapter] | None = None) -> None:
        self.adapters = adapters or default_adapters()
        self.cache = LookupCache(settings.lookup_cache_path)

    async def lookup(self, barcode: str, use_cache: bool = True) -> LookupResponse:
        if use_cache:
            cached = self.cache.get(barcode)
            if cached:
                return LookupResponse(barcode=barcode, found=True, result=cached)

        candidates: list[LookupResult] = []
        for adapter in self.adapters:
            result = await adapter.lookup(barcode)
            if result:
                candidates.append(result)

        if not candidates:
            return LookupResponse(barcode=barcode, found=False)

        ranked_candidates = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        best = ranked_candidates[0]
        self.cache.set(best)
        return LookupResponse(barcode=barcode, found=True, result=best, candidates=ranked_candidates[1:])
